"""njmind 自动登录并保存 Playwright storage_state。

用法：
    cd server && uv run python ../scripts/njmind_login.py [输出路径]
默认输出 /tmp/njmind-state.json。凭据读 server/.env（NJMIND_USER/NJMIND_PASS/NJMIND_LOGIN_URL），
不入库、不打印。
"""
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from playwright.async_api import async_playwright

ENV_PATH = Path(__file__).resolve().parents[1] / "server" / ".env"


async def main() -> None:
    cfg = dotenv_values(ENV_PATH)
    user = cfg.get("NJMIND_USER") or os.environ.get("NJMIND_USER", "")
    password = cfg.get("NJMIND_PASS") or os.environ.get("NJMIND_PASS", "")
    login_url = (cfg.get("NJMIND_LOGIN_URL")
                 or os.environ.get("NJMIND_LOGIN_URL", "http://192.168.99.22/mb3/1/"))
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/njmind-state.json"
    if not user or not password:
        sys.exit("缺少 NJMIND_USER/NJMIND_PASS（server/.env）")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(login_url)
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)
        # 账号/密码/验证码（内网验证码留空可直接登录，Sprint 4 已实测）
        await page.get_by_role("textbox").first.fill(user)
        await page.locator('input[type="password"]').first.fill(password)
        await page.get_by_role("button").filter(has_text="登").first.click()
        await page.wait_for_timeout(3000)
        await ctx.storage_state(path=out)
        title = await page.title()
        await browser.close()
    print(f"saved: {out}")
    print(f"title: {title}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
