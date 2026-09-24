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
from app.replay.assert_eval import evaluate_assertions
from app.replay.locate import locate
from app.replay.plan import compile_skeleton_plan, requires_confirmation

MAX_BODY = 8192
ARTIFACT_DIR = os.environ.get(
    "REPLAY_ARTIFACT_DIR", str(Path(__file__).resolve().parents[2] / "artifacts"))
STORAGE_STATE = os.environ.get("REPLAY_STORAGE_STATE", "")


def _launch():
    return async_playwright()


async def _open_browser(p):
    """浏览器入口：真实 Playwright 为 p.chromium.launch()，
    测试替身为扁平的 p.chromium_launch()，按能力分发。"""
    if hasattr(p, "chromium"):
        return await p.chromium.launch()
    return await p.chromium_launch()


async def execute_plan(page: Page, plan: dict, timeout_ms: int = 5000) -> dict:
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
                await locator.fill(step["value"], timeout=timeout_ms)
                executed.append({**step, "strategy": strategy, "ok": True})
            else:
                executed.append({**step, "ok": False, "error": f"unknown kind {step['kind']}"})
                failed = True
        except Exception as exc:
            executed.append({**step, "ok": False, "error": str(exc)[:200]})
            failed = True
    try:
        await page.wait_for_timeout(1500)  # 收尾等待尾随响应（njmind 保存链实测 ~600ms+）
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

    async with _launch() as p:
        browser = await _open_browser(p)
        ctx = await browser.new_context(storage_state=STORAGE_STATE or None)
        page = await ctx.new_page()
        await page.goto(plan["url"])
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        result = await execute_plan(page, plan)

        assertions = [{"kind": a.kind, "payload": a.payload} for a in
                      db.query(OutcomeAssertion).filter(
                          OutcomeAssertion.skill_id == skill_id).all()]
        results = evaluate_assertions(assertions, result["observed"])
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
