"""S21 浏览器用户层实测截图：登录页 / admin 技能页 / 评审门户 / viewer 只读提示。

用法：cd server && S21_ADMIN_PW=... S21_VIEWER_PW=... \
        uv run python ../scripts/s21_screenshots.py
账号约定：admin / viewer1（密码从环境变量读，不硬编码）。
输出：demo/sprint21/screenshots/*.png（1400x960）
"""
import asyncio
import os
from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8710"
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint21" / "screenshots"
ADMIN_PW = os.environ.get("S21_ADMIN_PW", "")
VIEWER_PW = os.environ.get("S21_VIEWER_PW", "")


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

        # ① 登录页
        await page.goto(f"{BASE}/login")
        await page.wait_for_selector("[data-testid=login-form]")
        await page.screenshot(path=str(OUT / "01-login.png"))

        # ② admin 登录后技能列表（侧边栏含当前用户/登出）
        await login(page, "admin", ADMIN_PW)
        await page.wait_for_selector("[data-testid=current-user]")
        await page.screenshot(path=str(OUT / "02-skills-admin.png"))

        # ③ 评审门户（admin 视角，展开一条待评运行）
        await page.goto(f"{BASE}/reviews-portal")
        await page.wait_for_selector("[data-testid=pending-row]")
        await page.locator("[data-testid=pending-row]").first.click()
        await page.wait_for_selector("[data-testid=review-form]")
        await page.screenshot(path=str(OUT / "03-review-portal.png"))

        # ④ viewer 只读提示
        await page.click("[data-testid=logout-btn]")
        await page.wait_for_url(f"{BASE}/login")
        await login(page, "viewer1", VIEWER_PW)
        await page.goto(f"{BASE}/reviews-portal")
        await page.wait_for_selector("[data-testid=pending-row]")
        await page.locator("[data-testid=pending-row]").first.click()
        await page.wait_for_selector("[data-testid=viewer-hint]")
        await page.screenshot(path=str(OUT / "04-viewer-readonly.png"))

        await browser.close()
        print("saved:", *[p.name for p in sorted(OUT.glob("*.png"))], sep="\n  ")


if __name__ == "__main__":
    asyncio.run(main())
