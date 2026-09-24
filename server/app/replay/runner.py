import asyncio
import json
import os
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.models import Alignment, OutcomeAssertion, RawEvent, ReplayRun, Skill
from app.replay.assert_eval import evaluate_assertions, path_matches
from app.replay.locate import locate
from app.replay.page_snapshot import collect_page_snapshot
from app.replay.plan import compile_skeleton_plan, requires_confirmation

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


async def run_replay(db: Session, skill_id: int, overrides: dict[str, str],
                     confirm_side_effect: bool) -> ReplayRun:
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

    try:
        async with _launch() as p:
            browser = await _open_browser(p)
            ctx = await _open_context(browser)
            page = await ctx.new_page()
            await page.goto(plan["url"])
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            assertions = [{"kind": a.kind, "payload": a.payload} for a in
                          db.query(OutcomeAssertion).filter(
                              OutcomeAssertion.skill_id == skill_id).all()]
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

            # FAIL/ERROR 时先截图并取页面 title（浏览器关闭前），归因待落库拿到 run 后再做
            screenshot_path = None
            page_title = None
            if status in ("fail", "error"):
                os.makedirs(ARTIFACT_DIR, exist_ok=True)
                screenshot_path = f"{ARTIFACT_DIR}/replay-{int(time.time() * 1000)}.png"
                await page.screenshot(path=screenshot_path)
                page_title = await page.title()
            await browser.close()
    except Exception as exc:
        # 浏览器阶段异常也必须落 error run（C3：执行审计不可缺）
        run = ReplayRun(skill_id=skill_id, mode="execute", status="error",
                        plan=plan, executed=None, assertion_results=None,
                        attribution=str(exc)[:500])
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    # T4：前后快照旁挂 plan（plan 消费方只读 url/steps，加法变更零破坏面，
    # 优于包装 executed——后者被 extract_observed 按步骤列表遍历）
    plan = {**plan, "before_snapshot": before_snapshot,
            "after_snapshot": after_snapshot}
    run = ReplayRun(skill_id=skill_id, mode="execute", status=status, plan=plan,
                    executed=result["executed"], assertion_results=results)
    db.add(run)
    db.commit()
    db.refresh(run)

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
