import asyncio
import json
import os
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.models import Alignment, OutcomeAssertion, RawEvent, ReplayRun, Skill, VisualBaseline
from app.replay.assert_eval import evaluate_assertions, path_matches
from app.replay.locate import locate
from app.replay.page_snapshot import collect_page_snapshot
from app.replay.plan import compile_skeleton_plan, requires_confirmation
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


async def execute_plan(page: Page, plan: dict, timeout_ms: int = 5000,
                       awaited_templates: list[str] | None = None,
                       settle_timeout_ms: int = 10000) -> dict:
    observed: list[dict] = []

    # 同步壳 + create_task：Playwright 的 on() 对 async 回调支持不稳（版本相关，
    # 可能静默不调用或调用不等待），同步回调内自建 task 最稳。
    def on_response(response):
        async def collect():
            try:
                body = await response.text()
            except Exception:
                body = ""
            observed.append({"url": response.url, "status": response.status,
                             "body": body[:MAX_BODY]})
        asyncio.get_running_loop().create_task(collect())

    page.on("response", on_response)
    executed: list[dict] = []
    failed = False
    for step in plan.get("steps", []):
        if failed:
            executed.append({**step, "ok": False, "error": "not attempted"})
            continue
        try:
            if step["kind"] == "click":
                locator, strategy = await locate(page, step["label"])
                await locator.click(timeout=timeout_ms)
                executed.append({**step, "strategy": strategy, "ok": True})
            elif step["kind"] == "input":
                locator, strategy = await locate(page, step["name"])
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
                executed.append({**step, "strategy": strategy, "ok": True})
            else:
                executed.append({**step, "ok": False, "error": f"unknown kind {step['kind']}"})
                failed = True
        except Exception as exc:
            executed.append({**step, "ok": False, "error": str(exc)[:200]})
            failed = True
    # 收尾：断言关心的模板全部命中即止，否则等满 settle_timeout_ms。
    # 固定短窗口会漏掉保存后的链式请求（njmind 实测 saveTableConfig 晚于 1.5s）。
    if awaited_templates:
        deadline = time.monotonic() + settle_timeout_ms / 1000
        while time.monotonic() < deadline:
            hit = [t for t in awaited_templates
                   if any(path_matches(o["url"], t) for o in observed)]
            if len(hit) == len(awaited_templates):
                break
            await page.wait_for_timeout(200)
    else:
        try:
            await page.wait_for_timeout(1500)  # 无目标模板时退回固定收尾
        except Exception:
            pass
    return {"executed": executed, "observed": observed}


async def _close_ctx_quietly(ctx) -> None:
    """批回放逐 skill 收尾：关本次 context（替身无 close 时跳过；关闭异常不掩盖已落库结果）。"""
    closer = getattr(ctx, "close", None)
    if closer is None:
        return
    try:
        await closer()
    except Exception:
        pass


async def _execute_skill(db: Session, browser, skill_id: int,
                         overrides: dict[str, str],
                         confirm_side_effect: bool) -> ReplayRun:
    """单 skill 回放执行体——browser 已由调用方开启，本函数不碰浏览器生命周期。

    shadow 门控在内：shadow 直接落库返回，不触 browser/context。
    计划编译异常（如 skill 不存在）向上抛——与重构前 run_replay 语义一致
    （run_graph 依赖该异常收敛图状态为 error，见 test_run_graph_error_captured）。
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
    ctx = None
    try:
        ctx = await _open_context(browser)
        page = await ctx.new_page()
        await page.goto(plan["url"])
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
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
        # T4：执行前采 before 快照（水合竞态防护在 execute_plan 的 fill 确认内，
        # 不与本采集竞争）
        before_snapshot = await collect_page_snapshot(page, phase="before")
        result = await execute_plan(
            page, plan,
            awaited_templates=[a["payload"]["api_template"] for a in assertions
                               if "api_template" in a["payload"]])
        # T4：断言评估前采 after 快照（ui_text 用它对比）
        after_snapshot = await collect_page_snapshot(page, phase="after")

        results = evaluate_assertions(assertions, result["observed"],
                                      after_snapshot=after_snapshot)
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
    except Exception as exc:
        # 执行阶段异常也必须落 error run（C3：执行审计不可缺）
        run = ReplayRun(skill_id=skill_id, mode="execute", status="error",
                        plan=plan, executed=None, assertion_results=None,
                        attribution=str(exc)[:500])
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    finally:
        if ctx is not None and not shared_ctx:
            await _close_ctx_quietly(ctx)

    # T4：前后快照旁挂 plan（plan 消费方只读 url/steps，加法变更零破坏面，
    # 优于包装 executed——后者被 extract_observed 按步骤列表遍历）
    plan = {**plan, "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot}
    run = ReplayRun(skill_id=skill_id, mode="execute", status=status, plan=plan,
                    executed=result["executed"], assertion_results=results)
    db.add(run)
    db.commit()
    db.refresh(run)

    # S22 块 T：建基线补表行（run 落库后才有 source_run_id）。
    # 截图文件无效（如替身写入非图像内容）→ 放弃建基线，不破坏已判定的 run
    # （与采集阶段同 fail-open 语义）。
    if baseline_created:
        try:
            from PIL import Image
            bpath = str(vdir / "baseline.png")
            with Image.open(bpath) as img:
                width, height = img.size
            db.add(VisualBaseline(skill_id=skill_id, file_path=bpath,
                                  image_hash=f"{dhash(bpath):016x}",
                                  width=width, height=height, source_run_id=run.id))
            db.commit()
        except Exception:
            pass

    if status in ("fail", "error"):
        failed_steps = [s for s in result["executed"] if not s.get("ok")]
        failed_asserts = [r for r in results if not r.get("passed")]
        prompt = (
            f"回放失败归因。页面标题：{page_title}\n"
            f"失败的步骤：{json.dumps(failed_steps, ensure_ascii=False)}\n"
            f"失败的断言：{json.dumps(failed_asserts, ensure_ascii=False)}\n"
            "只输出一段中文归因，不超过 100 字。"
        )
        r = complete(db, "replay_failure_attribution", prompt)
        run.attribution = r.text
        run.artifact_path = screenshot_path or ""
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
