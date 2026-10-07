import asyncio
import json
import os
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.gateway import acomplete
from app.models import (Alignment, LocateProposal, OutcomeAssertion,
                      RawEvent, ReplayRun, Skill, VisualBaseline)
from app.replay.assert_eval import evaluate_assertions, path_matches
from app.replay.locate import locate
from app.replay.page_snapshot import collect_page_snapshot
from app.replay.plan import compile_skeleton_plan, requires_confirmation
from app.replay.field_types import generate_value, is_valid_value, record_success
from app.replay.repair import generate_proposals, load_repair_map, record_usage
from app.sanitize import sanitize_error
from app.replay.flow_graph import derive_states
from app.replay.visual import compare_images, dhash, visual_dir

MAX_BODY = 8192
from app.config import REPLAY_ARTIFACT_DIR as ARTIFACT_DIR
STORAGE_STATE = os.environ.get("REPLAY_STORAGE_STATE", "")


def _launch():
    return async_playwright()


def _headless() -> bool:
    # REPLAY_HEADLESS=0 → 前台可见回放（演示/人工观察用）；默认无头，行为不变
    return os.environ.get("REPLAY_HEADLESS", "1") != "0"


def _channel() -> str:
    # REPLAY_CHANNEL=chrome → 用系统真 Chrome 二进制；默认 playwright 自带 chromium
    return os.environ.get("REPLAY_CHANNEL") or "chromium"


def _cdp_url() -> str:
    # REPLAY_CDP_URL=http://127.0.0.1:9222 → 连常驻浏览器执行回放（窗口不自动关）
    return os.environ.get("REPLAY_CDP_URL", "")


async def _open_browser(p):
    """浏览器入口：真实 Playwright 为 p.chromium.launch()，
    测试替身为扁平的 p.chromium_launch()，按能力分发。"""
    if hasattr(p, "chromium"):
        if _cdp_url():
            return await p.chromium.connect_over_cdp(_cdp_url())
        return await p.chromium.launch(
            headless=_headless(), channel=None if _channel() == "chromium" else _channel())
    return await p.chromium_launch()


async def _open_context(browser):
    """CDP 模式复用常驻 profile（带登录态与插件）；否则新开 context 注入登录态。"""
    if _cdp_url() and browser.contexts:
        return browser.contexts[0]
    return await browser.new_context(storage_state=STORAGE_STATE or None)


async def _check_row_checkbox(page, cb_locator, item_name: str) -> str:
    """S43-4：Frappe multi_select_dialog 行勾选（官方 list-row-check 带
    data-item-name）。check 的稳定性等待会被行重渲打破（节点 A 校验、
    节点 B 承接点击），逐级降级并在每级后核实 :checked。"""
    import asyncio as _aio
    async def _checked(sel) -> bool:
        try:
            return await page.evaluate(
                "s => !!document.querySelector(s + ':checked')", sel)
        except Exception:
            return False
    # 1) data-item-name 属性精确锚（无该属性时退回普通选择器）。
    #    行渲染稳定化：连续两次 count 一致才动手（列表重渲窗口内
    #    check 的 actionability 校验和点击会落在不同节点实例上——
    #    手动成功路径的差异正是 wait_for(visible) 的稳定等待）
    attr_sel = f'input.list-row-check[data-item-name="{item_name}"]'
    has_attr = await page.evaluate(
        "s => !!document.querySelector(s)", attr_sel)
    sel = attr_sel if has_attr else "input.list-row-check"
    base_sel = attr_sel if has_attr else "input.list-row-check"
    loc = page.locator(base_sel)
    for _ in range(10):
        try:
            c1 = await loc.count()
            await _aio.sleep(0.3)
            c2 = await loc.count()
            if c1 == c2 and c1 > 0:
                break
        except Exception:
            pass
    # 双 rAF：渲染队列排空（重渲整块替换在帧间发生，count 探测不到）
    try:
        await page.evaluate(
            "() => new Promise(r => requestAnimationFrame("
            "() => requestAnimationFrame(r)))")
    except Exception:
        pass
    # force+check 组合：跳过 stability（modal 搜索指示器的循环动画让
    # 帧永不稳定——check 超时的真因），但仍是 CDP 可信输入（jQuery
    # 委托把选中记入 selected 集合，重渲按集合恢复勾选）
    try:
        await loc.first.check(force=True, timeout=4000)
        if await _checked(sel):
            return "force-check"
        return f"check-noeffect:{sel[:50]}"
    except Exception as e:
        check_err = f"{type(e).__name__}:{str(e)[:80]}"
    try:
        await page.evaluate(
            "s => { const el = document.querySelector(s); if (el) el.click(); }", sel)
        await _aio.sleep(0.4)
        if await _checked(sel):
            return f"native-click(l1:{check_err})"
    except Exception:
        pass
    # 2) 原生 click 翻转（isTrusted=false 但浏览器默认行为仍翻转 checkbox，
    #    jQuery prop 读到；冒泡到官方监听链）
    try:
        await page.evaluate(
            "s => { const el = document.querySelector(s); if (el) el.click(); }", sel)
        await _aio.sleep(0.4)
        if await _checked(sel):
            return "native-click"
    except Exception:
        pass
    # 3) 最终兜底：force click（CDP 可信输入；不直写 checked——change
    # 直写会触发框架请求（run_doc_method 预拉取），污染后续写按钮的
    # intercept 基线）
    try:
        await page.locator(
            attr_sel if has_attr else "input.list-row-check").first.click(
            force=True, timeout=4000)
        return "force-click"
    except Exception:
        pass
    return "none"



def _row_anchor_token(row_text: str) -> str:
    """S43-4：宿主行文本 → 行过滤锚词。中文行无空格 split() 拿整串
    （含截断尾巴匹配必败）——按 ASCII 词边界切（表名/单据号特征）。"""
    import re as _re
    toks = _re.findall(r"[A-Za-z0-9_]{4,}", row_text)
    return toks[0] if toks else row_text


async def _locate_with_repair(page, label: str,
                             repair_map: dict[str, dict] | None,
                             extra_labels: list[str] | None = None,
                             tag: str | None = None,
                             ordinal: int | None = None,
                             path: str | None = None,
                             prefer_controls: bool = False):
    """S24 块 U：定位失败时按提案库重试——返回 (locator, strategy, proposal_id)。

    无提案或提案也定位失败 → 抛 LookupError（步骤照常失败）。
    S43-4：上步交互触发的重渲染窗口（Frappe modal 勾选行后按钮瞬时
    不可见）——首轮失败后短暂重试再走修复链。
    """
    try:
        locator, strategy = await locate(
            page, label, labels=extra_labels, tag=tag, ordinal=ordinal, path=path,
            prefer_controls=prefer_controls)
        return locator, strategy, None
    except LookupError:
        for _ in range(3):
            await page.wait_for_timeout(500)
            try:
                locator, strategy = await locate(
                    page, label, labels=extra_labels, tag=tag, ordinal=ordinal,
                    path=path, prefer_controls=prefer_controls)
                return locator, strategy, None
            except LookupError:
                continue
        rep = (repair_map or {}).get(label)
        if rep is None:
            raise
    locator, strategy = await locate(page, rep["label"])
    return locator, f"repair:{strategy}", rep["id"]


async def _shot_step(page, shot_dir, idx: int, entry: dict) -> None:
    """S33：步骤截图（fail-open）——采集能力缺失（替身 page）静默跳过，
    不影响步骤判定；成功/失败步骤都拍（失败画面是归因关键证据）。"""
    if shot_dir is None:
        return
    try:
        name = f"step-{idx:02d}.png"
        await page.screenshot(path=str(Path(shot_dir) / name))
        entry["screenshot"] = name
    except Exception:
        pass


# S42-7：表单校验错误探测——主流框架的校验提示元素约定 + HTML5 原生。
# 点击提交后校验不过（无 API 请求、表单不关）是回放常见失败态，
# 确定性捕获错误文本供归因与字段类型自愈。
_VALIDATION_SEL = (
    ".ant-form-item-explain-error, .el-form-item__error, .invalid-feedback, "
    ".field-error, .help-block.error, .error-message, [role='alert'].error, "
    # S43-4：Frappe 桌面端校验/业务提示弹层（Save 假阳性根因——点击
    # 成功但 "Please select Quotation" 拦住后续，步骤需判失败给归因）
    ".msgprint, .modal .indicator"
)
_PROBE_JS = """() => {
    const out = [];
    document.querySelectorAll(%SEL%).forEach(el => {
        const t = (el.textContent || '').trim();
        if (t) out.push(t.slice(0, 100));
    });
    document.querySelectorAll('form :invalid').forEach(el => {
        if (el.validationMessage) out.push(el.validationMessage.slice(0, 100));
    });
    return [...new Set(out)].slice(0, 10);
}""".replace("%SEL%", repr(_VALIDATION_SEL))


async def collect_validation_errors(page) -> list[str]:
    """点击后短暂探测页面校验错误文本（跨 frame，fail-open）。

    S43-4：含 Frappe 桌面端 msgprint/indicator 弹层，但须语义过滤——
    成功 toast（Saved/Submitted/成功）不是校验错误，只有拦截语义
    （Please/mandatory/required/不能为空/Error 等）才计入。"""
    texts: list[str] = []
    for fr in page.frames:
        try:
            errs = await fr.evaluate(_PROBE_JS)
            texts.extend(errs or [])
        except Exception:
            continue
    # S43-4：语义过滤——只留拦截类提示（含 Frappe msgprint 成功 toast
    # 的排除：Saved/成功 是业务结果不是校验错误）
    bad_words = ("please", "mandatory", "required", "must ", "不能为空",
                 "必须", "请填写", "请选择", "请在列表", "请先", "至少",
                 "not allowed", "invalid", "error", "错误", "失败")
    ok_words = ("saved", "submitted", "成功", "created", "updated", "完成")
    out = []
    for t in texts:
        low = t.lower()
        if any(b in low for b in bad_words) and not any(o in low for o in ok_words):
            out.append(t)
        if len(out) >= 10:
            break
    return out


async def execute_plan(page: Page, plan: dict, timeout_ms: int = 5000,
                       awaited_templates: list[str] | None = None,
                       settle_timeout_ms: int = 10000,
                       repair_map: dict[str, dict] | None = None,
                       shot_dir: Path | None = None,
                       row_anchor_hints: list[str] | None = None) -> dict:
    observed: list[dict] = []

    # S23 块 V：request/response 配对测 API 延迟（request 对象做键）
    req_times: dict = {}

    def on_request(request):
        req_times[request] = time.monotonic()

    # S37 断言语义根治：toast 瞬态——轮询常见 toast 容器，捕获文本经
    # observed_toasts 供断言判定（after 快照时机必然错过瞬态元素）。
    # S43-4：提升到循环前——点击间的写等待窗口也要轮询（串行等待会
    # 吃掉 600ms 级 toast 的存活窗口）
    observed_toasts: list[str] = []
    # S43-4：非写按钮点击引发的框架写请求水位（如勾选触发 Frappe
    # run_doc_method 预拉）——写按钮判定失败时回看该水位放行
    recent_write_mark = 0
    entry_pending_note = ""

    async def _poll_toasts():
        try:
            texts = await page.evaluate("""() => {
              const sels = ['.toast', '.toast-message', '.alert', '[role=alert]',
                '.ant-message-notice', '.el-message', '.o-notification', '.msg',
                '.sweet-alert', '.noty', '.toastify', '.alert-message'];
              const out = [];
              for (const s of sels) {
                for (const el of document.querySelectorAll(s)) {
                  if (el.offsetParent !== null) {
                    const t = el.textContent.trim().slice(0, 100);
                    if (t) out.push(t);
                  }
                }
              }
              return out;
            }""")
            for t in texts:
                if t not in observed_toasts:
                    observed_toasts.append(t)
        except Exception:
            pass

    # 同步壳 + create_task：Playwright 的 on() 对 async 回调支持不稳（版本相关，
    # 可能静默不调用或调用不等待），同步回调内自建 task 最稳。
    def on_response(response):
        async def collect():
            try:
                body = await response.text()
            except Exception:
                body = ""
            start = req_times.pop(response.request, None)
            latency_ms = (int((time.monotonic() - start) * 1000)
                          if start is not None else None)
            observed.append({"url": response.url, "status": response.status,
                             "method": response.request.method,
                             "body": body[:MAX_BODY], "latency_ms": latency_ms})
        asyncio.get_running_loop().create_task(collect())

    page.on("request", on_request)
    page.on("response", on_response)
    executed: list[dict] = []
    failed = False
    early_submitted = False
    for i, step in enumerate(plan.get("steps", []), start=1):
        if failed:
            executed.append({**step, "ok": False, "error": "not attempted"})
            continue
        if early_submitted:
            executed.append({**step, "ok": True,
                             "skipped": "表单已由日期控件 Enter 提前提交，步骤跳过（结果由断言判定）"})
            continue
        try:
            if step["kind"] == "goto":
                # S43-4：多页流程的导航步（plan 编译从 navigation 事件
                # 插入）——URL 归一化同 _plan_url 规则由编译侧保证
                await page.goto(step["url"])
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
                executed.append({**step, "ok": True})
                await _shot_step(page, shot_dir, i, {**step, "ok": True})
            elif step["kind"] == "click":
                locator, strategy, rep_id = await _locate_with_repair(
                    page, step["label"], repair_map,
                    extra_labels=step.get("labels"), tag=step.get("tag"),
                    ordinal=step.get("ordinal"), path=step.get("path"))
                # S43-4：checkbox 用 check()——结果列表渲染时 checkbox
                # 反复重建，普通 click 的 stability 等待会超时；check 幂等
                # 且自带等待
                # S43-4：多行同 label 触发器（行操作"更多"下拉）——labels
                # 带宿主行文本（采集端 hostRowText）时按行过滤点目标行
                # 行文本信号须含 ASCII 字母/数字（实体名/表名特征）——
                # 纯中文提示（"未选中任何数据"空表文案）不是行内容
                # S43-5：row_anchor_hints 优先（换参注入的新实体名）——
                # labels 是录制时行文本，跨轮换参必然陈旧（JeecG 链式）
                row_texts = ([h for h in (row_anchor_hints or [])
                              if len(h) > 6 and
                              any(c.isascii() and c.isalnum() for c in h)]
                             or [l for l in (step.get("labels") or [])
                                 if len(l) > 6 and l != (step.get("label") or "")
                                 and any(c.isascii() and c.isalnum() for c in l)])
                if row_texts:
                        rt = row_texts[0]
                        try:
                            row = page.locator(
                                ".ant-table-row, .list-item, .grid-row, tr"
                            ).filter(has_text=_row_anchor_token(rt)).first
                            if await row.count():
                                trig = row.get_by_text(
                                    step.get("label") or "", exact=True).first
                                if await trig.count():
                                    await trig.click(
                                        timeout=max(timeout_ms, 10000), force=True)
                                    await page.wait_for_timeout(800)
                                    entry = {**step, "strategy": "row-trigger",
                                             **({"repair_proposal_id": rep_id} if rep_id else {}),
                                             "ok": True}
                                    try:
                                        if entry_pending_note:
                                            entry["checkbox_mode"] = entry_pending_note
                                            entry_pending_note = ""
                                    except NameError:
                                        pass
                                    executed.append(entry)
                                    await _shot_step(page, shot_dir, i, entry)
                                    continue
                        except Exception:
                            pass
                # S43-4（Frappe 官方 save 命令：intercept+wait）：写类按钮
                # 点击前记录观测基线——点击后等写响应到达，超时即"提交
                # 被拦"判失败（POST 是否发出是普适判据，toast 文案是
                # 归因证据）。base 必须在点击前取：点击到判定的窗口内
                # 请求可能已完成入 observed
                # S43-4：整词匹配（词边界）——"Get Items From"（开菜单）
                # 不得命中 "getitems"（确认动作）；精确区分打开类与提交类
                import re as _re
                label_norm = "".join(
                    (step.get("label") or "").lower().split())
                write_exact = {"getitems", "yes", "create"}
                write_sub = ("save", "submit", "确认", "保存", "提交")
                write_like = (any(w in label_norm for w in write_sub)
                              or label_norm in write_exact)
                # S43-4：两步提交流（Submit→Yes 确认）——Submit 只开确认
                # 弹窗不发请求，写请求由下步 Yes 发出。plan 全量已知：
                # 下一步是确认词则本步豁免写判定（判定移交 Yes 步）
                steps_all = plan.get("steps", [])
                next_lbl = ""
                if i < len(steps_all):
                    next_lbl = "".join(
                        (steps_all[i].get("label") or "").lower().split())
                next_is_confirm = next_lbl in write_exact or next_lbl in ("确定", "ok", "是")
                write_base = (len(observed)
                              if write_like and not next_is_confirm else None)
                is_checkbox = False
                try:
                    is_checkbox = await locator.evaluate(
                        "el => el.tagName === 'INPUT' && el.type === 'checkbox'")
                except Exception:
                    pass
                if is_checkbox:
                    # Frappe 官方 Cypress 命令（select_listview_row_checkbox）
                    # 对行勾选框用普通 click 而非 check()——JS 托管的勾选
                    # 状态 check() 的写入-校验会误报 did not change。
                    # S43-4：多行 checkbox 按 labels 里的宿主行文本过滤
                    # （采集端 hostRowText）——不过滤时 input-value 命中
                    # 首行（最老单据），Get Items 拉错数据
                    # 行区分信号优先级：本流程最近的搜索词（含 override
                    # 换参值——checkbox 步骤 labels 是录制时行文本，跨轮
                    # 必然陈旧）> row_anchor_hints 换参注入 > 步骤自身
                    # labels 的宿主行文本
                    row_texts = []
                    for prev in reversed(plan.get("steps", [])[:i]):
                        if prev.get("kind") == "input" and prev.get("value")                                 and len(str(prev["value"])) > 6:
                            row_texts.append(str(prev["value"]))
                            break
                    if not row_texts and row_anchor_hints:
                        row_texts = [h for h in row_anchor_hints if len(h) > 6]
                    if not row_texts:
                        row_texts = [l for l in (step.get("labels") or [])
                                     if len(l) > 6 and l not in ("on", "off")]
                    cb_locator = locator
                    row_pinned = False
                    if row_texts:
                        rt = row_texts[0]
                        try:
                            row = page.locator(
                                ".list-item, .grid-row, tr, [role=row]"
                            ).filter(has_text=_row_anchor_token(rt)).first
                            # 搜索结果渲染有 1-2s 延迟——行未到先等
                            # （不等则 fallback 到表头框勾错对象）
                            for _ in range(8):
                                if await row.count():
                                    break
                                await page.wait_for_timeout(400)
                            if await row.count():
                                cb_locator = row.locator(
                                    'input[type="checkbox"]').first
                                row_pinned = True
                        except Exception:
                            pass
                    scene_note = ""
                    try:
                        scene_note = await page.evaluate(
                            "() => { const area = document.querySelector("
                            "'[data-fieldname=results_area]'); const rows = area ? "
                            "area.querySelectorAll('.list-item:not(.list-item--head)').length : -1; "
                            "const checked = document.querySelectorAll("
                            "'.list-row-check:checked, input[type=checkbox]:checked').length; "
                            "return `rows=${rows} checked=${checked}`; }")
                    except Exception:
                        pass
                    if row_pinned:
                        # 官方锚点：Frappe modal 行勾选框带 data-item-name
                        # （multi_select_dialog.js）——按属性钉死唯一节点，
                        # 逐步降级：check → 原生 click（el.click() 翻转
                        # checkbox 并冒泡，jQuery .prop 读 DOM 状态生效）
                        # 勾选必须走真实 CDP 事件（jQuery 委托把选中
                        # 记入 selected 集合，重渲按集合恢复勾选；合成
                        # el.click() 只翻 DOM 不进集合，重渲即还原——
                        # map_docs 因此不发）。重渲平息判定：双 rAF 帧
                        # 后行仍存在再 check
                        mode = await _check_row_checkbox(
                            page, cb_locator, row_texts[0].split()[0])
                        entry_pending_note = mode
                    else:
                        try:
                            await cb_locator.click(force=True, timeout=max(timeout_ms, 10000))
                        except Exception:
                            await locator.evaluate("el => el.click()")
                    await page.wait_for_timeout(800)
                    # S43-4：勾选后校验——未生效直接失败并带现场（说真话）
                    try:
                        checked_now = await page.evaluate(
                            "() => document.querySelectorAll("
                            "'.list-row-check:checked, input[type=checkbox]:checked').length")
                        if not checked_now:
                            rows_now = await page.evaluate(
                                "() => { const a = document.querySelector("
                                "'[data-fieldname=results_area]'); return a ? "
                                "a.querySelectorAll('.list-item:not(.list-item--head)').length : -1; }")
                            raise RuntimeError(
                                f"勾选未生效 before={scene_note} rows_now={rows_now}")
                    except RuntimeError:
                        raise
                    except Exception:
                        pass
                else:
                    try:
                        await locator.click(timeout=timeout_ms)
                    except Exception:
                        # S43-4：重渲型 UI（modal/表格定时刷新）stability
                        # 等待超时——force 点击（可信输入，同上）
                        await locator.click(force=True, timeout=timeout_ms)
                entry = {**step, "strategy": strategy,
                         **({"repair_proposal_id": rep_id} if rep_id else {}),
                         "ok": True}
                try:
                    if entry_pending_note:
                        entry["checkbox_mode"] = entry_pending_note
                        entry_pending_note = ""
                except NameError:
                    pass
                # S42-7：点击后探测表单校验错误（拦截文案作归因证据，
                # fail-open 记录不判定）
                try:
                    await page.wait_for_timeout(300)
                    v_errs = await collect_validation_errors(page)
                    if v_errs:
                        entry["validation_errors"] = v_errs
                except Exception:
                    pass
                # S43-4：写类按钮等待写响应（基线在点击前记录）——
                # 无 POST = 提交被拦，判失败；拦截文案进 error 供归因
                if write_base is not None:
                    try:
                        await page.evaluate(
                            "() => { if (window.__sl_cb_lock) {"
                            "window.__sl_cb_lock.disconnect(); "
                            "window.__sl_cb_lock = null; } }")
                    except Exception:
                        pass
                    deadline = time.monotonic() + 6
                    saw_write = False
                    while time.monotonic() < deadline:
                        await _poll_toasts()
                        recent = [o for o in observed[write_base:]
                                  if o.get("method") in ("POST", "PUT", "PATCH")]
                        if recent:
                            saw_write = True
                            break
                        await page.wait_for_timeout(300)
                    if not saw_write and len(observed) > recent_write_mark:
                        # 预拉放行：前一交互（勾选）已触发框架写请求
                        # （run_doc_method 预拉），按钮点击无新请求是
                        # 框架去重，业务动作已发生——非拦截
                        saw_write = True
                    if not saw_write:
                        hint = ""
                        try:
                            errs = await collect_validation_errors(page)
                            if errs:
                                hint = f" 提示: {errs[0][:100]}"
                        except Exception:
                            pass
                        entry = {**step, "ok": False,
                                 "error": f"点击后无写请求（提交被拦）{hint}"}
                        executed.append(entry)
                        await _shot_step(page, shot_dir, i, entry)
                        failed = True
                        continue
                # S43-4：写请求（POST/PATCH/PUT）在途时等它落地（异步
                # 拉单/保存 ERPNext map_docs ~2-4s，完成前页面结构未变
                # 后续定位必失败）。等待与 toast 快照并行——串行等待会
                # 吃掉瞬态 toast 的存活窗口（600ms toast vs 300+400ms）
                base = len(req_times)
                url_before = page.url
                obs_base = len(observed)
                t0 = time.monotonic()
                while time.monotonic() - t0 < 8:
                    await page.evaluate(
                        "() => {}")
                    pend_writes = [r for r in list(req_times)[base:]
                                   if r.method in ("POST", "PUT", "PATCH")]
                    await _poll_toasts()
                    if not pend_writes and time.monotonic() - t0 > 0.4:
                        break
                    await page.wait_for_timeout(300)
                # 框架预拉水位更新（本窗口出现过写响应即记录）
                if any(o.get("method") in ("POST", "PUT", "PATCH")
                       for o in observed[obs_base:]):
                    recent_write_mark = len(observed)
                # S43-4：写后 SPA 跳转（Save→详情页）——url 变化时等
                # 新文档加载完，否则后续 locate 在导航窗口空转
                if page.url != url_before:
                    try:
                        await page.wait_for_load_state(
                            "domcontentloaded", timeout=10000)
                        await page.wait_for_timeout(1000)
                    except Exception:
                        pass
                executed.append(entry)
                await _shot_step(page, shot_dir, i, entry)
            elif step["kind"] == "input":
                # S43-4：脱敏占位值（插件密码脱敏通道）——不回填假值
                # （fill "[REDACTED]" 必被目标系统拒），跳过并把判定交断言
                if str(step.get("value", "")) == "[REDACTED]":
                    executed.append({**step, "ok": True,
                                     "skipped": "脱敏字段不回放（凭据由编排注入）"})
                    continue
                locator, strategy, rep_id = await _locate_with_repair(
                    page, step["name"], repair_map,
                    extra_labels=step.get("labels"), tag=step.get("tag"),
                    ordinal=step.get("ordinal"), path=step.get("path"),
                    prefer_controls=True)
                # S43-4：类型守卫——重渲窗口内 locate 可能命中字段包装
                # div（fill 必抛错）。命中不可填元素时限定 input/textarea
                # 重定位（labels 轮转已含字段名变体）
                try:
                    tag_name = await locator.evaluate("el => el.tagName")
                except Exception:
                    tag_name = ""
                if tag_name not in ("INPUT", "TEXTAREA"):
                    for lbl in [step["name"], *(step.get("labels") or [])]:
                        try:
                            alt = page.locator(
                                f'input[data-fieldname="{lbl}"], '
                                f'textarea[data-fieldname="{lbl}"], '
                                f'input[placeholder="{lbl}"]')
                            if await alt.count() and await alt.first.is_visible():
                                locator = alt.first
                                strategy = "data-fieldname-typed"
                                break
                        except Exception:
                            continue
                # 水合竞态防护：SPA 可能在 fill 后回写旧值（njmind 实测，
                # 值被改回则保存的脏检查跳过、不发请求），确认值真的写入
                # S42-12：命中原生 <select>（zui picker 的 pick-value 承载
                # select）时 fill 必抛错——走 select_option
                filled = False
                tag_name = await locator.evaluate("el => el.tagName")
                # S43-4：select2 下拉（name=宿主 select 名）——fill 无效，
                # 须开容器→搜索→点结果（Snipe-IT 等 bootstrap 系）
                is_select2 = await locator.evaluate(
                    "el => !!(el.closest('.select2-container')"
                    " || el.querySelector('.select2-container')"
                    " || (el.classList && el.classList.contains('select2-container'))"
                    " || (el.tagName === 'SELECT' && el.nextElementSibling"
                    "     && el.nextElementSibling.classList.contains('select2-container')))")
                if is_select2:
                    if tag_name == "SELECT":
                        container = locator.locator(
                            "xpath=..").locator(".select2-container").first
                    else:
                        container = locator
                    # 前置 click 步（"Select Status"）可能已开弹层——
                    # 已开则不重复点（重开会闪断选项渲染）
                    already_open = await page.locator(
                        ".select2-container--open .select2-results__option").count()
                    if not already_open:
                        await container.click(timeout=timeout_ms, force=True)
                        await page.wait_for_timeout(800)
                    # 本地数据下拉（statuslabels 等）无搜索框——直接点
                    # 匹配选项；AJAX 下拉（models/users）先搜索再点
                    search = page.locator("input.select2-search__field:visible").first
                    if await search.count():
                        await search.fill(step["value"], timeout=timeout_ms)
                        await page.wait_for_timeout(900)
                    opt = page.locator(
                        ".select2-results__option",
                        has_text=step["value"]).first
                    await opt.click(timeout=timeout_ms)
                    await page.wait_for_timeout(600)
                    filled = True
                elif tag_name == "SELECT":
                    await locator.select_option(step["value"], timeout=timeout_ms)
                    filled = await locator.input_value() == step["value"]
                else:
                    for attempt in range(3):
                        # S43-4：fill 后补一次无害 keyup——Frappe 等框架
                        # 搜索框监听 keyup（fill 只发 input 事件不发键序），
                        # search_widget 不触发则列表出全量旧数据，后续
                        # 选项点击选错单据。End 键不改动值只产生 keyup/
                        # keydown 事件流。弹层搜索框另等结果渲染（modal
                        # 刚开时监听器未挂，fill 的 input 事件被吞——
                        # 实测 00089 Open 可转单但 results_area 0 行）
                        await locator.fill(step["value"], timeout=timeout_ms)
                        await locator.press("End", timeout=timeout_ms)
                        in_modal = await locator.evaluate(
                            "el => !!el.closest('.modal, [role=dialog]')")
                        if in_modal:
                            await page.wait_for_timeout(1200)
                            try:
                                rows = await page.evaluate(
                                    "() => document.querySelectorAll("
                                    "'[data-fieldname=results_area] .list-item:not(.list-item--head)').length")
                                if rows == 0:
                                    # 监听器迟到：重发 input 事件（React 合成
                                    # 事件对 el.value 直写不触发，须 setter）
                                    await locator.evaluate(
                                        "el => { const s = Object.getOwnPropertyDescriptor("
                                        "el.__proto__, 'value').set; s.call(el, el.value); "
                                        "el.dispatchEvent(new Event('input', {bubbles: true})); }")
                                    await page.wait_for_timeout(1500)
                            except Exception:
                                pass
                        # S42-12：日期控件 fill 不触发框架同步（zui 隐藏
                        # 承载域由 Enter 提交，禅道实测 fill 后直接保存报
                        # "计划完成不能为空"；Tab 失焦对范围日期不生效）。
                        # Enter 可能连带提交整个表单（下拉未开时）——表单
                        # 已提前提交则剩余步骤跳过，判定交给断言（说真话：
                        # 业务结果已发生，POST 响应可判）
                        in_date_picker = await locator.evaluate(
                            "el => !!(el.closest('.pick, [class*=date-picker], .ant-picker, "
                            "[data-fieldtype]'))")
                        # S43-4：值写入后统一补 Enter——Frappe 行内编辑
                        # （grid/row-form 的 date 字段）fill 不提交值，值停在
                        # 控件里 Save 仍报 mandatory（手动成功路径靠 Enter）
                        await locator.press("Enter", timeout=timeout_ms)
                        if in_date_picker:
                            await page.wait_for_timeout(800)
                            try:
                                connected = await locator.evaluate("el => el.isConnected")
                            except Exception:
                                connected = False
                            if not connected:
                                early_submitted = True
                                filled = True  # 表单已提交，值已被消费
                                break
                        for _ in range(4):
                            await page.wait_for_timeout(250)
                            if await locator.input_value() == step["value"]:
                                filled = True
                                break
                        if filled:
                            break
                if not filled:
                    raise RuntimeError(f"输入 {step['name']} 被页面回写覆盖")
                entry = {**step, "strategy": strategy,
                         **({"repair_proposal_id": rep_id} if rep_id else {}),
                         "ok": True}
                executed.append(entry)
                await _shot_step(page, shot_dir, i, entry)
            else:
                executed.append({**step, "ok": False, "error": f"unknown kind {step['kind']}"})
                failed = True
        except Exception as exc:
            # S43-4：失败现场文本证据（url+可见按钮）——截图不可机读，
            # 归因需要确定性 DOM 摘要
            scene = ""
            try:
                btns = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('button'))"
                    ".filter(b => b.getBoundingClientRect().width > 0)"
                    ".map(b => b.textContent.trim().slice(0, 18))"
                    ".filter(Boolean).slice(0, 14)")
                scene = f" @ {page.url[-60:]} btns={btns}"
            except Exception:
                pass
            entry = {**step, "ok": False, "error": str(exc)[:200] + scene}
            executed.append(entry)
            await _shot_step(page, shot_dir, i, entry)
            failed = True
    # 收尾：断言关心的模板全部命中即止，否则等满 settle_timeout_ms。
    # 固定短窗口会漏掉保存后的链式请求（njmind 实测 saveTableConfig 晚于 1.5s）。
    # S42-12：只认"步骤执行后新到达"的响应——模板可能已被步骤前的
    # 页面加载命中（禅道 /index.php 页面加载先于保存 POST），旧语义
    # 立即 break，保存写响应还在途就进断言判定（result 字段缺失假失败）
    base = len(observed)
    if awaited_templates:
        deadline = time.monotonic() + settle_timeout_ms / 1000
        while time.monotonic() < deadline:
            hit = [t for t in awaited_templates
                   if any(path_matches(o["url"], t) for o in observed[base:])]
            if len(hit) == len(awaited_templates):
                break
            await _poll_toasts()
            await page.wait_for_timeout(200)
    else:
        try:
            for _ in range(5):
                await _poll_toasts()
                await page.wait_for_timeout(300)  # 无目标模板时退回固定收尾
        except Exception:
            pass
    # S23 块 V：关键 API 延迟按断言模板聚合（多次命中取中位数，与基线语义一致）
    api_latencies: dict[str, int] = {}
    for tpl in (awaited_templates or []):
        lats = sorted(o["latency_ms"] for o in observed
                      if o.get("latency_ms") is not None and path_matches(o["url"], tpl))
        if lats:
            mid = len(lats) // 2
            api_latencies[tpl] = (lats[mid] if len(lats) % 2 == 1
                                   else (lats[mid - 1] + lats[mid]) // 2)
    return {"executed": executed, "observed": observed,
            "api_latencies": api_latencies, "observed_toasts": observed_toasts}


async def _close_ctx_quietly(ctx) -> None:
    """批回放逐 skill 收尾：关本次 context（替身无 close 时跳过；关闭异常不掩盖已落库结果）。"""
    closer = getattr(ctx, "close", None)
    if closer is None:
        return
    try:
        await closer()
    except Exception:
        pass


def _heal_plan_inputs(db, plan: dict) -> tuple[dict, list[dict]]:
    """S42-7：按字段类型知识库修复 plan 的 input 步值。

    只改"类型可判定且当前值不合法"的字段（宁缺毋滥——未知类型不动，
    合法值不动）；返回 (新 plan, 修复字段清单)，无修复返回 (原 plan, [])。
    """
    healed: list[dict] = []
    steps = []
    # 同类型共享生成值：密码/确认密码必须一致（各自随机必"密码不一致"）
    gen_by_type: dict[str, str] = {}
    from app.replay.field_types import resolve_type
    for step in plan.get("steps") or []:
        if step.get("kind") == "input":
            name = str(step.get("name") or step.get("label") or "")
            value = str(step.get("value") or "")
            if name and not is_valid_value(db, name, value):
                rule = resolve_type(db, name)
                if rule is not None:
                    ftype = rule["field_type"]
                    if ftype in gen_by_type:
                        new_val = gen_by_type[ftype]
                    else:
                        new_val = generate_value(db, name)
                    if new_val is not None:
                        gen_by_type[ftype] = new_val
                        healed.append({"name": name, "old": value, "value": new_val})
                        steps.append({**step, "value": new_val})
                        continue
        steps.append(step)
    if not healed:
        return plan, []
    return {**plan, "steps": steps}, healed


def _flaky_rerun() -> bool:
    # S24 块 U：REPLAY_FLAKY_RERUN=0 关闭 fail 自动重试；调用时读 env（可测试）
    return os.environ.get("REPLAY_FLAKY_RERUN", "1") == "1"


async def _heal_with_llm_attribution(
        db, plan: dict, v_errs: list[str] | None = None) -> tuple[dict, list[dict]]:
    """S43-3 层 3：规则自愈不命中 → LLM 归因未知字段 → 再走确定性生成。

    LLM 只做字段类型分类（输出须在类型枚举内才落库 source=llm）；
    值生成/校验仍走确定性规则（宪法：判定无 LLM）。
    归因范围：校验错误文本提到的字段（确定性关联）——自由文本字段
    不因 LLM 误归因被破坏性换值（"备注"被当 phone 的实测教训）。
    """
    from app.replay.field_types import llm_attribute_type, resolve_type
    for step in plan.get("steps") or []:
        if step.get("kind") != "input":
            continue
        name = str(step.get("name") or step.get("label") or "")
        if not name or resolve_type(db, name) is not None:
            continue
        if v_errs and not any(name in e for e in v_errs):
            continue
        try:
            await llm_attribute_type(db, name)
        except Exception:
            pass
    return _heal_plan_inputs(db, plan)


async def _attempt(db: Session, browser, skill_id: int, plan: dict,
                   assertions: list[dict], shared_ctx: bool,
                   repair_map: dict[str, dict] | None = None,
                   has_overrides: bool = False,
                   row_anchor_hints: list[str] | None = None) -> dict:
    """S24 块 U：单次执行尝试（无 DB 写）——_execute_skill 编排重试的基础。

    异常收敛为 error attempt（不抛）；返回键：
    status/result/results/before_snapshot/after_snapshot/duration_ms/
    visual_result/baseline_created/vdir/screenshot_path/page_title/error_text。
    """
    ctx = None
    try:
        ctx = await _open_context(browser)
        page = await ctx.new_page()
        await page.goto(plan["url"])
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        before_snapshot = await collect_page_snapshot(page, phase="before")
        # S33：起始页截图 + 步骤截图目录（fail-open：替身无 screenshot 能力
        # → shot_dir 置 None，整轮不采步骤截图，不影响判定）
        shot_dir = None
        start_shot = None
        try:
            d = Path(ARTIFACT_DIR) / f"steps-{skill_id}-{int(time.time() * 1000)}"
            os.makedirs(d, exist_ok=True)
            await page.screenshot(path=str(d / "start.png"))
            shot_dir = d
            start_shot = "start.png"
        except Exception:
            shot_dir = None
            start_shot = None
        t0 = time.monotonic()
        result = await execute_plan(
            page, plan,
            awaited_templates=[a["payload"]["api_template"] for a in assertions
                               if "api_template" in a["payload"]],
            repair_map=repair_map, shot_dir=shot_dir,
            row_anchor_hints=row_anchor_hints)
        duration_ms = int((time.monotonic() - t0) * 1000)
        after_snapshot = await collect_page_snapshot(page, phase="after")

        # S24 块 U：定位失败 → LLM 提案 + 确定性验证（页面还开着，仍可 locate 实测）
        repair_used_ids = [s["repair_proposal_id"] for s in result["executed"]
                           if s.get("ok") and s.get("repair_proposal_id")]
        failed_locate = []
        for s in result["executed"]:
            if s.get("ok") or "semantic locate failed" not in (s.get("error") or ""):
                continue
            failed_locate.append(s.get("label") or s.get("name") or "")
        repair_created_ids: list[int] = []
        if failed_locate:
            try:
                created = await generate_proposals(
                    db, page, skill_id, [l for l in failed_locate if l])
                repair_created_ids = [r.id for r in created]
            except Exception:
                pass  # 提案生成失败不破坏回放判定（fail-open）

        results = evaluate_assertions(assertions, result["observed"],
                                      after_snapshot=after_snapshot,
                                      observed_toasts=result.get("observed_toasts"),
                                      executed_steps=result.get("executed") or [])
        any_ok_step = any(s.get("ok") for s in result["executed"])
        if not any_ok_step:
            status = "error"
        elif all(r["passed"] for r in results):
            status = "pass"
        else:
            status = "fail"
        # S42-7 说真话：点击后被表单校验拦截（提交未发生）不得判 pass——
        # 断言可能不覆盖提交（录制时提交就没成功过），但校验错误是
        # 确定性证据：业务动作没有发生。
        # S43-4 时序豁免：校验错误之后的步骤若已成功（select2 打开瞬间
        # 的"请选择"提示被后续 input 步修复并成功提交），历史错误不再
        # 拦截——只拦"错误是最后状态"的运行
        if status == "pass":
            last_err_idx = -1
            last_ok_idx = -1
            for i, s in enumerate(result["executed"]):
                if s.get("ok"):
                    last_ok_idx = i
                elif s.get("validation_errors"):
                    last_err_idx = i
            if last_err_idx > last_ok_idx:
                status = "fail"

        # S22 块 T：视觉回归（确定性，无 LLM）——截图须在 ctx 关闭前完成。
        # 无基线且 PASS → 建基线（run 落库后补表行）；有基线 → 比对追加断言。
        # 采集能力缺失（如替身 page 无 screenshot）→ 整体跳过不计失败
        # （与 assert_eval 无快照 fail-open 同语义）。
        visual_result = None
        baseline_created = False
        vdir = visual_dir(ARTIFACT_DIR, skill_id)
        try:
            baseline = db.query(VisualBaseline).filter_by(skill_id=skill_id).first()
            if baseline is None:
                if status == "pass":
                    os.makedirs(vdir, exist_ok=True)
                    await page.screenshot(path=str(vdir / "baseline.png"))
                    baseline_created = True
            else:
                os.makedirs(vdir, exist_ok=True)
                await page.screenshot(path=str(vdir / "latest.png"))
                cmp = compare_images(baseline.file_path, str(vdir / "latest.png"))
                visual_result = {"payload": {"kind": "visual_baseline", **cmp},
                                "observed_status": None, "passed": cmp["passed"]}
        except Exception:
            visual_result = None
            baseline_created = False
        if visual_result is not None:
            # S37 断言语义根治：换参数据回放时页面内容变化是预期行为
            # （模拟人工用不同数据操作），视觉差异记录不判定——消除假阴性
            if has_overrides and not visual_result["passed"]:
                visual_result = {**visual_result, "passed": True,
                                 "skipped": "换参数据回放：视觉差异为预期，已记录不判定"}
            results.append(visual_result)
            if not visual_result["passed"] and status == "pass":
                status = "fail"

        # FAIL/ERROR 时先截图并取页面 title（context 关闭前），归因待落库拿到 run 后再做
        screenshot_path = None
        page_title = None
        if status in ("fail", "error"):
            os.makedirs(ARTIFACT_DIR, exist_ok=True)
            screenshot_path = f"{ARTIFACT_DIR}/replay-{int(time.time() * 1000)}.png"
            await page.screenshot(path=screenshot_path)
            page_title = await page.title()
        return {"status": status, "result": result, "results": results,
                "before_snapshot": before_snapshot, "after_snapshot": after_snapshot,
                "duration_ms": duration_ms, "visual_result": visual_result,
                "baseline_created": baseline_created, "vdir": vdir,
                "screenshot_path": screenshot_path, "page_title": page_title,
                "shot_dir": shot_dir, "start_shot": start_shot,
                "repair_used_ids": repair_used_ids,
                "repair_created_ids": repair_created_ids,
                "error_text": None}
    except Exception as exc:
        return {"status": "error", "result": None, "results": None,
                "before_snapshot": None, "after_snapshot": None,
                "duration_ms": None, "visual_result": None,
                "baseline_created": False, "vdir": None,
                "screenshot_path": None, "page_title": None,
                "shot_dir": None, "start_shot": None,
                "repair_used_ids": [], "repair_created_ids": [],
                "error_text": str(exc)[:500]}
    finally:
        if ctx is not None and not shared_ctx:
            await _close_ctx_quietly(ctx)


async def _execute_skill(db: Session, browser, skill_id: int,
                         overrides: dict[str, str],
                         confirm_side_effect: bool) -> ReplayRun:
    """单 skill 回放执行体——browser 已由调用方开启，本函数不碰浏览器生命周期。

    shadow 门控在内：shadow 直接落库返回，不触 browser/context。
    计划编译异常（如 skill 不存在）向上抛——与重构前 run_replay 语义一致
    （run_graph 依赖该异常收敛图状态为 error，见 test_run_graph_error_captured）。
    S24 块 U：fail 自动重试一次（REPLAY_FLAKY_RERUN）——重试 pass 标 flaky，
    首次失败明细嵌入 plan.first_attempt（C3 审计）。
    """
    skill = db.get(Skill, skill_id)
    alignment = db.get(Alignment, skill.alignment_id)
    ref_sid = alignment.session_ids[0]
    rows = db.execute(select(RawEvent).where(RawEvent.session_id == ref_sid)
                      .order_by(RawEvent.ts, RawEvent.seq)).scalars().all()
    events = [{"seq": r.seq, "ts": r.ts, "kind": r.kind, "payload": r.payload or {}} for r in rows]
    plan = compile_skeleton_plan(events, skill.skeleton, ref_sid, overrides or {},
                                 skill.input_variables)

    # CDP 常驻 context 由 _open_context 复用返回，逐 skill 收尾时不能关
    shared_ctx = bool(_cdp_url() and getattr(browser, "contexts", None))
    assertions = [{"kind": a.kind, "payload": a.payload} for a in
                  db.query(OutcomeAssertion).filter(
                      OutcomeAssertion.skill_id == skill_id).all()]
    # 被覆盖变量的 ui_text 期望跟随覆盖值（录制值是旧参数的 UI 状态，
    # 换参回放时按注入值判定——否则换参必 FAIL，语义错误）
    for a in assertions:
        if a["kind"] == "ui_text":
            label = a["payload"].get("label")
            if label in (overrides or {}):
                a["payload"] = {**a["payload"],
                                "after": overrides[label]}

    repair_map = load_repair_map(db, skill_id)
    has_overrides = any(str(v).strip() for v in (overrides or {}).values())
    # S43-5：换参值即行锚提示——行点击步 labels 的宿主行文本是录制时
    # 实体名，跨轮换参必然陈旧（JeecG 链式 Sync/Fill 根因）
    row_hints = [str(v) for v in (overrides or {}).values() if str(v).strip()]
    attempt = await _attempt(db, browser, skill_id, plan, assertions, shared_ctx,
                             repair_map, has_overrides=has_overrides,
                             row_anchor_hints=row_hints)
    flaky = False
    field_healed = False
    healed_fields: list[dict] = []
    # S42-7 字段类型自愈：JS 校验拦截（点击 ok 但表单校验不过、无提交请求）
    # → 按字段类型知识库生成合法值换值重试；成功反哺知识库
    if attempt["status"] == "fail":
        v_errs = [e for s in (attempt["result"] or {}).get("executed") or []
                  for e in (s.get("validation_errors") or [])]
        if v_errs:
            healed_plan, healed_fields = _heal_plan_inputs(db, plan)
            if not healed_fields:
                # S43-3 层 3：规则全不命中 → LLM 归因回填知识库再生成
                healed_plan, healed_fields = await _heal_with_llm_attribution(
                    db, plan, v_errs)
            if healed_fields:
                retry = await _attempt(db, browser, skill_id, healed_plan,
                                       assertions, shared_ctx, repair_map,
                                       has_overrides=has_overrides,
                                       row_anchor_hints=row_hints)
                if retry["status"] == "pass":
                    field_healed = True
                    retry["first_attempt"] = {"status": attempt["status"],
                                              "executed": attempt["result"]["executed"],
                                              "assertion_results": attempt["results"],
                                              "validation_errors": v_errs}
                    attempt = retry
                    for f in healed_fields:
                        record_success(db, f["name"], f["value"], skill_id)
    if (attempt["status"] == "fail" and _flaky_rerun()):
        # flaky 语义=真实非确定性；重试沿用同一 repair_map——本次新生成的提案
        # 留给下一轮回放（自愈是跨回放的，不与 flaky 混淆）
        retry = await _attempt(db, browser, skill_id, plan, assertions, shared_ctx,
                               repair_map, has_overrides=has_overrides,
                               row_anchor_hints=row_hints)
        if retry["status"] == "pass":
            flaky = True
            # C3：首次失败明细嵌入（重试通过时失败尝试不单独落 run，但可审计）
            retry["first_attempt"] = {"status": attempt["status"],
                                      "executed": attempt["result"]["executed"],
                                      "assertion_results": attempt["results"]}
            attempt = retry

    if attempt["status"] == "error" and attempt["error_text"] is not None:
        # 执行阶段异常也必须落 error run（C3：执行审计不可缺）；
        # 安全红线：error_text 落库前 URL 脱敏
        run = ReplayRun(skill_id=skill_id, mode="execute", status="error",
                        plan=plan, executed=None, assertion_results=None,
                        attribution=sanitize_error(attempt["error_text"]))
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    result = attempt["result"]
    results = attempt["results"]
    status = attempt["status"]

    # T4：前后快照旁挂 plan（plan 消费方只读 url/steps，加法变更零破坏面，
    # 优于包装 executed——后者被 extract_observed 按步骤列表遍历）
    # S23 块 V：API 延迟同样旁挂（api_latencies 键，替身 execute_plan 无此键时跳过）
    plan = {**plan, "before_snapshot": attempt["before_snapshot"],
            "after_snapshot": attempt["after_snapshot"],
            "api_latencies": result.get("api_latencies") or {},
            # S38 业务状态（流程图基座）：观测响应派生，确定性规则
            "business_states": derive_states(result.get("observed") or [])}
    # S33：步骤截图清单旁挂（起始页 + 每步一张；fail-open 无截图不挂键）
    shot_files = []
    if attempt.get("start_shot"):
        shot_files.append(attempt["start_shot"])
    shot_files += [s["screenshot"] for s in (result.get("executed") or [])
                   if s.get("screenshot")]
    if shot_files and attempt.get("shot_dir"):
        plan = {**plan, "step_screenshots": {"dir": str(attempt["shot_dir"]),
                                             "files": shot_files}}
    if "first_attempt" in attempt:
        plan = {**plan, "first_attempt": attempt["first_attempt"]}
    if field_healed:
        plan = {**plan, "field_healed": True,
                "healed_fields": healed_fields}
    run = ReplayRun(skill_id=skill_id, mode="execute", status=status, plan=plan,
                    executed=result["executed"], assertion_results=results,
                    duration_ms=attempt["duration_ms"], flaky=flaky)
    db.add(run)
    db.commit()
    db.refresh(run)

    # S22 块 T：建基线补表行（run 落库后才有 source_run_id）。
    # 截图文件无效（如替身写入非图像内容）→ 放弃建基线，不破坏已判定的 run
    # （与采集阶段同 fail-open 语义）。
    if attempt["baseline_created"]:
        try:
            from PIL import Image
            bpath = str(attempt["vdir"] / "baseline.png")
            with Image.open(bpath) as img:
                width, height = img.size
            db.add(VisualBaseline(skill_id=skill_id, file_path=bpath,
                                  image_hash=f"{dhash(bpath):016x}",
                                  width=width, height=height, source_run_id=run.id))
            db.commit()
        except Exception:
            pass

    # S24 块 U：自愈成功计数（≥N 自动晋升）+ 新提案关联源 run（U3 归因链）
    # S43-1：只在 run 整体 pass 时计数——状态依赖失败（前置条件缺失）下
    # LLM 会从空状态页面选出无关元素且 locate 验证通过（禅道实证：无
    # 激活 Bug 时"解决"→"搜索"），失败运行反复计数把它晋升成污染技能。
    # 修复后的步骤 ok 但断言未过 ≠ 自愈成功；run pass 才算数。
    if attempt["repair_used_ids"] and status == "pass":
        record_usage(db, attempt["repair_used_ids"])
    if attempt["repair_created_ids"]:
        db.query(LocateProposal).filter(
            LocateProposal.id.in_(attempt["repair_created_ids"])
        ).update({"source_run_id": run.id},
                 synchronize_session=False)
        db.commit()

    if status in ("fail", "error"):
        failed_steps = [s for s in result["executed"] if not s.get("ok")]
        failed_asserts = [r for r in results if not r.get("passed")]
        prompt = (
            f"回放失败归因。页面标题：{attempt['page_title']}\n"
            f"失败的步骤：{json.dumps(failed_steps, ensure_ascii=False)}\n"
            f"失败的断言：{json.dumps(failed_asserts, ensure_ascii=False)}\n"
            "只输出一段中文归因，不超过 100 字。"
        )
        # S42：归因失败不得把已落库的 fail run 变成重复 error run
        # （异常传到 run_replay 兜底会再落一条 error，时间线重复计数）。
        try:
            r = await acomplete(db, "replay_failure_attribution", prompt)
            run.attribution = r.text
        except Exception as exc:
            run.attribution = f"归因调用失败：{sanitize_error(exc)}"
        run.artifact_path = attempt["screenshot_path"] or ""
        db.commit()
        db.refresh(run)
    return run


def _error_run(db: Session, skill_id: int, exc: Exception) -> ReplayRun:
    """启动阶段异常的兜底 error run（C3：此阶段 plan 未编译，落 None）。
    安全红线：attribution 落库前 URL 脱敏（异常常内嵌目标系统地址）。"""
    run = ReplayRun(skill_id=skill_id, mode="execute", status="error",
                    plan=None, executed=None, assertion_results=None,
                    attribution=sanitize_error(exc))
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


async def _shadow_run_if_gated(db: Session, skill_id: int,
                               confirm_side_effect: bool) -> ReplayRun | None:
    """C1 前置门控：shadow 在开浏览器之前判定并落库（Sprint 4 验收语义：
    shadow 未确认绝不启浏览器）。非 shadow 场景返回 None 由调用方继续执行。
    计划编译纯 DB 无浏览器依赖；skill 不存在向上抛（与 _execute_skill 一致）。"""
    skill = db.get(Skill, skill_id)
    if not requires_confirmation(skill.skeleton) or confirm_side_effect:
        return None
    alignment = db.get(Alignment, skill.alignment_id)
    ref_sid = alignment.session_ids[0]
    rows = db.execute(select(RawEvent).where(RawEvent.session_id == ref_sid)
                      .order_by(RawEvent.ts, RawEvent.seq)).scalars().all()
    events = [{"seq": r.seq, "ts": r.ts, "kind": r.kind, "payload": r.payload or {}} for r in rows]
    plan = compile_skeleton_plan(events, skill.skeleton, ref_sid, {}, skill.input_variables)
    run = ReplayRun(skill_id=skill_id, mode="shadow", status="shadow",
                    plan=plan, executed=None, assertion_results=None)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


async def run_replay(db: Session, skill_id: int, overrides: dict[str, str],
                     confirm_side_effect: bool) -> ReplayRun:
    shadow_run = await _shadow_run_if_gated(db, skill_id, confirm_side_effect)
    if shadow_run is not None:
        return shadow_run  # C1：shadow 未确认不启浏览器
    try:
        # 执行必须整体在 _launch() 上下文内——with 块退出即断开 Playwright
        # 连接，浏览器对象随之失效（S13 重构曾把执行移出 with 块导致
        # 真实 execute 回放必 error，S15 公网实测抓出）
        async with _launch() as p:
            browser = await _open_browser(p)
            try:
                return await _execute_skill(db, browser, skill_id, overrides,
                                            confirm_side_effect)
            finally:
                # 关闭异常不掩盖已落库结果/原始异常
                try:
                    await browser.close()
                except Exception:
                    pass
    except Exception as exc:
        # 启动/执行阶段异常都落 error run（C3：执行审计不可缺）
        return _error_run(db, skill_id, exc)


async def run_replay_batch(db: Session, skill_ids: list[int],
                           overrides_map: dict[int, dict],
                           confirm_side_effect: bool) -> list[ReplayRun]:
    """S13 F3 批回放：browser 实例复用——一次 launch，逐 skill 新 context 串行执行。

    C1：confirm_side_effect 批级——false 时各 skill 独立走 shadow 门控；
    shadow 项前置落库不触浏览器（全 shadow 批次零 launch）。
    单 skill 异常（如 skill 不存在）不中断批次：落 error run 继续（C3）。
    """
    runs: list[ReplayRun] = []
    pending: list[int] = []
    for sid in skill_ids:
        try:
            shadow_run = await _shadow_run_if_gated(db, sid, confirm_side_effect)
            if shadow_run is not None:
                runs.append(shadow_run)
            else:
                pending.append(sid)
        except Exception as exc:
            runs.append(_error_run(db, sid, exc))
    if not pending:
        return runs  # 全 shadow：不启浏览器
    try:
        # 同 run_replay：执行必须整体在 _launch() 上下文内（连接生命周期）
        async with _launch() as p:
            browser = await _open_browser(p)
            try:
                for sid in pending:
                    try:
                        runs.append(await _execute_skill(
                            db, browser, sid, (overrides_map or {}).get(sid) or {},
                            confirm_side_effect))
                    except Exception as exc:  # 计划编译等前置异常：落 error run 继续
                        runs.append(_error_run(db, sid, exc))
                return runs
            finally:
                try:
                    await browser.close()
                except Exception:
                    pass
    except Exception as exc:
        runs.extend(_error_run(db, sid, exc) for sid in pending)
        return runs
