import asyncio
import json
import os
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.models import (Alignment, LocateProposal, OutcomeAssertion,
                      RawEvent, ReplayRun, Skill, VisualBaseline)
from app.replay.assert_eval import evaluate_assertions, path_matches
from app.replay.locate import locate
from app.replay.page_snapshot import collect_page_snapshot
from app.replay.plan import compile_skeleton_plan, requires_confirmation
from app.replay.repair import generate_proposals, load_repair_map, record_usage
from app.replay.visual import compare_images, dhash, visual_dir

MAX_BODY = 8192
ARTIFACT_DIR = os.environ.get(
    "REPLAY_ARTIFACT_DIR", str(Path(__file__).resolve().parents[2] / "artifacts"))
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


async def _locate_with_repair(page, label: str,
                             repair_map: dict[str, dict] | None,
                             extra_labels: list[str] | None = None,
                             tag: str | None = None,
                             ordinal: int | None = None,
                             path: str | None = None,
                             prefer_controls: bool = False):
    """S24 块 U：定位失败时按提案库重试——返回 (locator, strategy, proposal_id)。

    无提案或提案也定位失败 → 抛 LookupError（步骤照常失败）。
    """
    try:
        locator, strategy = await locate(
            page, label, labels=extra_labels, tag=tag, ordinal=ordinal, path=path,
            prefer_controls=prefer_controls)
        return locator, strategy, None
    except LookupError:
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


async def execute_plan(page: Page, plan: dict, timeout_ms: int = 5000,
                       awaited_templates: list[str] | None = None,
                       settle_timeout_ms: int = 10000,
                       repair_map: dict[str, dict] | None = None,
                       shot_dir: Path | None = None) -> dict:
    observed: list[dict] = []

    # S23 块 V：request/response 配对测 API 延迟（request 对象做键）
    req_times: dict = {}

    def on_request(request):
        req_times[request] = time.monotonic()

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
                             "body": body[:MAX_BODY], "latency_ms": latency_ms})
        asyncio.get_running_loop().create_task(collect())

    page.on("request", on_request)
    page.on("response", on_response)
    executed: list[dict] = []
    failed = False
    for i, step in enumerate(plan.get("steps", []), start=1):
        if failed:
            executed.append({**step, "ok": False, "error": "not attempted"})
            continue
        try:
            if step["kind"] == "click":
                locator, strategy, rep_id = await _locate_with_repair(
                    page, step["label"], repair_map,
                    extra_labels=step.get("labels"), tag=step.get("tag"),
                    ordinal=step.get("ordinal"), path=step.get("path"))
                await locator.click(timeout=timeout_ms)
                entry = {**step, "strategy": strategy,
                         **({"repair_proposal_id": rep_id} if rep_id else {}),
                         "ok": True}
                executed.append(entry)
                await _shot_step(page, shot_dir, i, entry)
            elif step["kind"] == "input":
                locator, strategy, rep_id = await _locate_with_repair(
                    page, step["name"], repair_map,
                    extra_labels=step.get("labels"), tag=step.get("tag"),
                    ordinal=step.get("ordinal"), path=step.get("path"),
                    prefer_controls=True)
                # 水合竞态防护：SPA 可能在 fill 后回写旧值（njmind 实测，
                # 值被改回则保存的脏检查跳过、不发请求），确认值真的写入
                filled = False
                for _ in range(3):
                    await locator.fill(step["value"], timeout=timeout_ms)
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
            entry = {**step, "ok": False, "error": str(exc)[:200]}
            executed.append(entry)
            await _shot_step(page, shot_dir, i, entry)
            failed = True
    # S37 断言语义根治：toast 瞬态——settle 窗口内轮询常见 toast 容器，
    # 捕获的文本经 observed_toasts 供断言判定（after 快照时机必然错过瞬态元素）
    observed_toasts: list[str] = []

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

    # 收尾：断言关心的模板全部命中即止，否则等满 settle_timeout_ms。
    # 固定短窗口会漏掉保存后的链式请求（njmind 实测 saveTableConfig 晚于 1.5s）。
    if awaited_templates:
        deadline = time.monotonic() + settle_timeout_ms / 1000
        while time.monotonic() < deadline:
            hit = [t for t in awaited_templates
                   if any(path_matches(o["url"], t) for o in observed)]
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


def _flaky_rerun() -> bool:
    # S24 块 U：REPLAY_FLAKY_RERUN=0 关闭 fail 自动重试；调用时读 env（可测试）
    return os.environ.get("REPLAY_FLAKY_RERUN", "1") == "1"


async def _attempt(db: Session, browser, skill_id: int, plan: dict,
                   assertions: list[dict], shared_ctx: bool,
                   repair_map: dict[str, dict] | None = None,
                   has_overrides: bool = False) -> dict:
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
            repair_map=repair_map, shot_dir=shot_dir)
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
                                      observed_toasts=result.get("observed_toasts"))
        any_ok_step = any(s.get("ok") for s in result["executed"])
        if not any_ok_step:
            status = "error"
        elif all(r["passed"] for r in results):
            status = "pass"
        else:
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

    shadow = requires_confirmation(skill.skeleton) and not confirm_side_effect
    if shadow:
        run = ReplayRun(skill_id=skill_id, mode="shadow", status="shadow",
                        plan=plan, executed=None, assertion_results=None)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

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
    attempt = await _attempt(db, browser, skill_id, plan, assertions, shared_ctx,
                             repair_map, has_overrides=has_overrides)
    flaky = False
    if (attempt["status"] == "fail" and _flaky_rerun()):
        # flaky 语义=真实非确定性；重试沿用同一 repair_map——本次新生成的提案
        # 留给下一轮回放（自愈是跨回放的，不与 flaky 混淆）
        retry = await _attempt(db, browser, skill_id, plan, assertions, shared_ctx,
                               repair_map, has_overrides=has_overrides)
        if retry["status"] == "pass":
            flaky = True
            # C3：首次失败明细嵌入（重试通过时失败尝试不单独落 run，但可审计）
            retry["first_attempt"] = {"status": attempt["status"],
                                      "executed": attempt["result"]["executed"],
                                      "assertion_results": attempt["results"]}
            attempt = retry

    if attempt["status"] == "error" and attempt["error_text"] is not None:
        # 执行阶段异常也必须落 error run（C3：执行审计不可缺）
        run = ReplayRun(skill_id=skill_id, mode="execute", status="error",
                        plan=plan, executed=None, assertion_results=None,
                        attribution=attempt["error_text"])
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
            "api_latencies": result.get("api_latencies") or {}}
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
    if attempt["repair_used_ids"]:
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
        r = complete(db, "replay_failure_attribution", prompt)
        run.attribution = r.text
        run.artifact_path = attempt["screenshot_path"] or ""
        db.commit()
        db.refresh(run)
    return run


def _error_run(db: Session, skill_id: int, exc: Exception) -> ReplayRun:
    """启动阶段异常的兜底 error run（C3：此阶段 plan 未编译，落 None）。"""
    run = ReplayRun(skill_id=skill_id, mode="execute", status="error",
                    plan=None, executed=None, assertion_results=None,
                    attribution=str(exc)[:500])
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
