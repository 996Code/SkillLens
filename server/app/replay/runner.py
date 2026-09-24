from playwright.async_api import Page

from app.replay.locate import locate

MAX_BODY = 8192


async def execute_plan(page: Page, plan: dict, timeout_ms: int = 5000) -> dict:
    observed: list[dict] = []

    async def on_response(response):
        try:
            body = await response.text()
        except Exception:
            body = ""
        observed.append({"url": response.url, "status": response.status,
                         "body": body[:MAX_BODY]})

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
        await page.wait_for_timeout(500)  # 收尾等待尾随响应
    except Exception:
        pass
    return {"executed": executed, "observed": observed}
