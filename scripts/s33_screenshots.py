"""S33 步骤截图浏览器实测：/timeline 展开 replay 项 → 步骤截图墙上屏。

前置：已跑一次带截图的 execute 回放（run 178，skill #5 动态值）。
截图存 demo/sprint33/screenshots/。
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from playwright.async_api import async_playwright  # noqa: E402

BASE = os.environ.get("SL_BASE", "http://127.0.0.1:8710")
RUN_ID = os.environ.get("SL_RUN_ID", "178")
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint33" / "screenshots"


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
        ctx = await browser.new_context(viewport={"width": 1400, "height": 960})
        page = await ctx.new_page()
        await page.goto(f"{BASE}/login")
        await page.evaluate(
            """([t]) => {
                localStorage.setItem('sl_token', t);
                localStorage.setItem('sl_user',
                    JSON.stringify({id: 1, username: 'admin', role: 'admin'}));
            }""",
            [token],
        )

        await page.goto(f"{BASE}/timeline")
        await page.wait_for_selector("[data-testid='timeline-list']")

        # 过滤 replay 类型，展开目标 run
        await page.click("[data-testid='filter-replay']")
        await page.wait_for_timeout(300)
        target = page.locator(
            f".tl-item[data-testid='tl-replay']:has-text('回放 #{RUN_ID}')")
        await target.first.click()
        await page.wait_for_selector("[data-testid='replay-detail']")
        await page.wait_for_selector("[data-testid='shot-grid'] img")
        await page.wait_for_timeout(800)

        imgs = await page.locator("[data-testid='shot-grid'] img").count()
        captions = await page.locator(
            "[data-testid='shot-grid'] figcaption").all_inner_texts()
        print(f"[1] replay #{RUN_ID} expanded: {imgs} screenshots")
        assert imgs >= 3, f"expected >=3 step screenshots, got {imgs}"
        assert "起始页" in captions, captions
        print(f"[2] captions: {captions}")
        # 图片真实加载（naturalWidth > 0）
        ok = await page.evaluate(
            """() => Array.from(document.querySelectorAll(
                "[data-testid='shot-grid'] img"))
                .every(i => i.naturalWidth > 0)""")
        assert ok, "some screenshots failed to load"
        print("[3] all images loaded (naturalWidth > 0)")

        await page.locator("[data-testid='shot-grid']").scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "01-replay-shot-wall.png"))

        await browser.close()
    print("S33 browser verification PASSED")


asyncio.run(main())
