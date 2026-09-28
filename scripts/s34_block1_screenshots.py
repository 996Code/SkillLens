"""S34 块 1 浏览器实测：回放 run 详情页 + 截图点击放大。

路径：/replay-runs/{id} 头部（状态/flaky/耗时）→ 步骤表 → 截图墙 →
点击缩略图 lightbox → 关闭；时间线 replay 项"下钻 run 详情"链接跳转。
截图存 demo/sprint34/screenshots/。
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from playwright.async_api import async_playwright  # noqa: E402

BASE = os.environ.get("SL_BASE", "http://127.0.0.1:8710")
RUN_ID = os.environ.get("SL_RUN_ID", "178")
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint34" / "screenshots"


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

        # ① run 详情页直达
        await page.goto(f"{BASE}/replay-runs/{RUN_ID}")
        await page.wait_for_selector(".run-status")
        text = await page.inner_text("section")
        assert f"回放 run #{RUN_ID}" in text, text[:200]
        assert "Skill #" in text
        print(f"[1] run detail header ok (run {RUN_ID})")
        await page.screenshot(path=str(OUT / "01-run-detail.png"))

        # ② 步骤表 + 截图墙
        await page.wait_for_selector("[data-testid='shot-grid'] img")
        imgs = await page.locator("[data-testid='shot-grid'] img").count()
        ok = await page.evaluate(
            """() => Array.from(document.querySelectorAll(
                "[data-testid='shot-grid'] img"))
                .every(i => i.naturalWidth > 0)""")
        assert imgs >= 3 and ok, f"imgs={imgs}, loaded={ok}"
        print(f"[2] step table + {imgs} screenshots loaded")
        await page.locator("[data-testid='shot-grid']").scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "02-shot-wall.png"))

        # ③ 点击缩略图 → lightbox → 关闭
        await page.locator(".shot-card").first.click()
        await page.wait_for_selector("[data-testid='shot-lightbox']")
        await page.screenshot(path=str(OUT / "03-lightbox.png"))
        await page.locator("[data-testid='shot-lightbox']").click()
        await page.wait_for_timeout(300)
        assert await page.locator("[data-testid='shot-lightbox']").count() == 0
        print("[3] lightbox open/close ok")

        # ④ 时间线 replay 项下钻链接
        await page.goto(f"{BASE}/timeline")
        await page.wait_for_selector("[data-testid='timeline-list']")
        await page.click("[data-testid='filter-replay']")
        await page.wait_for_timeout(300)
        target = page.locator(
            f".tl-item[data-testid='tl-replay']:has-text('回放 #{RUN_ID}')")
        await target.first.click()
        await page.wait_for_selector(".shot-links a")
        await page.click(".shot-links a")
        await page.wait_for_url(f"**/replay-runs/{RUN_ID}", timeout=10_000)
        print(f"[4] timeline drill-down ok: {page.url}")
        await page.screenshot(path=str(OUT / "04-timeline-drilldown.png"))

        await browser.close()
    print("S34 block1 browser verification PASSED")


asyncio.run(main())
