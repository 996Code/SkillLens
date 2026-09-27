"""S24 浏览器实测截图：自愈提案区块（失败→归因→提案→验证链）+ viewer 角色对比。

用法：cd server && S21_ADMIN_PW=... S21_VIEWER_PW=... uv run python ../scripts/s24_screenshots.py
"""
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8710"
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint24" / "screenshots"
ADMIN_PW = os.environ.get("S21_ADMIN_PW", "")
VIEWER_PW = os.environ.get("S21_VIEWER_PW", "")
SKILL_ID = os.environ.get("S24_SKILL_ID", "8")


async def login(page, username: str, password: str) -> None:
    await page.goto(f"{BASE}/login")
    await page.fill("[data-testid=login-username]", username)
    await page.fill("[data-testid=login-password]", password)
    await page.click("[data-testid=login-submit]")
    await page.wait_for_url(f"{BASE}/skills", timeout=10_000)


async def main() -> None:
    if not ADMIN_PW or not VIEWER_PW:
        raise SystemExit("需要环境变量 S21_ADMIN_PW / S21_VIEWER_PW（不硬编码凭据）")
    OUT.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 960})

        # admin：提案区块（含归因链与否决按钮）
        await login(page, "admin", ADMIN_PW)
        await page.goto(f"{BASE}/skills/{SKILL_ID}")
        await page.wait_for_selector("[data-testid=proposal-section]", timeout=10_000)
        await page.locator("[data-testid=proposal-section]").scroll_into_view_if_needed()
        await page.wait_for_timeout(400)
        await page.screenshot(path=str(OUT / "01-proposal-section.png"))

        # viewer：无否决按钮
        await page.click("[data-testid=logout-btn]")
        await page.wait_for_url(f"{BASE}/login")
        await login(page, "viewer1", VIEWER_PW)
        await page.goto(f"{BASE}/skills/{SKILL_ID}")
        await page.wait_for_selector("[data-testid=proposal-section]", timeout=10_000)
        await page.locator("[data-testid=proposal-section]").scroll_into_view_if_needed()
        await page.wait_for_timeout(400)
        await page.screenshot(path=str(OUT / "02-viewer-no-reject.png"))

        await browser.close()
        print("saved:", *[q.name for q in sorted(OUT.glob("*.png"))], sep="\n  ")


if __name__ == "__main__":
    asyncio.run(main())
