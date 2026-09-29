"""S37-3 浏览器实测：测试套件全流程（真机一键执行）。

路径：/suites 新建套件（勾选 2 个操作流程）→ 一键执行（预演模式）→
执行汇总（结果表+run 链接）→ 执行历史。截图存 demo/sprint37/screenshots/。
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from playwright.async_api import async_playwright  # noqa: E402

BASE = os.environ.get("SL_BASE", "http://127.0.0.1:8710")
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint37" / "screenshots"


def mint_token() -> str:
    from app.auth import issue_token
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "admin").first()
        return issue_token(db, u.id)
    finally:
        db.close()


async def main() -> None:
    token = mint_token()
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await (await browser.new_context(viewport={"width": 1400, "height": 960})).new_page()
        await page.goto(f"{BASE}/login")
        await page.evaluate(
            """([t]) => {
                localStorage.setItem('sl_token', t);
                localStorage.setItem('sl_user',
                    JSON.stringify({id: 1, username: 'admin', role: 'admin'}));
            }""",
            [token],
        )

        # ① 套件页 + 新建（勾选 2 个操作流程）
        await page.goto(f"{BASE}/suites")
        await page.wait_for_selector("[data-testid='skill-picker']")
        rows = page.locator(".pick-row input")
        n = await rows.count()
        print(f"[1] 操作流程可选数: {n}")
        await page.locator("[data-testid='suite-name']").fill("S37 冒烟套件")
        await rows.nth(0).check()
        await rows.nth(1).check()
        await page.locator("[data-testid='suite-create']").click()
        await page.wait_for_timeout(1500)
        await page.screenshot(path=str(OUT / "06-suite-created.png"))
        print("[2] 套件已创建")

        # ② 一键执行（预演模式：不勾副作用确认）
        run_btn = page.locator("[data-testid='suite-run-1']")
        if not await run_btn.count():
            run_btn = page.locator("[data-testid^='suite-run-']").first
        await run_btn.click()
        await page.wait_for_timeout(30000)
        summary = page.locator("[data-testid='suite-run-summary']")
        await summary.wait_for(timeout=60000)
        text = await summary.inner_text()
        print(f"[3] 执行汇总: {text[:120]}".replace("\n", " | "))
        assert "通过" in text or "预演" in text
        await page.screenshot(path=str(OUT / "07-suite-run-summary.png"))

        # ③ 执行历史
        btns = page.locator(".suite-card .btn-secondary")
        await btns.first.click()
        await page.wait_for_timeout(1500)
        hist = page.locator("[data-testid='suite-history']")
        assert await hist.count()
        print("[4] 执行历史上屏")
        await page.screenshot(path=str(OUT / "08-suite-history.png"))

        await browser.close()
    print("S37-3 browser verification PASSED")


asyncio.run(main())
