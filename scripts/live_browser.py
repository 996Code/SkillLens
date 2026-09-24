"""常驻可视化浏览器（演示/观察用）。

一个一直开着的 Chrome 窗口：带 SkillLens 插件、自动登录 njmind、暴露 CDP 端口。
回放/采集经 REPLAY_CDP_URL / RECORD_CDP_URL 连进这个窗口执行，不再另开临时窗口。

用法：
    cd server && uv run python ../scripts/live_browser.py [端口，默认 9222]
配合：
    REPLAY_CDP_URL=http://127.0.0.1:9222  → server 回放复用此窗口
    RECORD_CDP_URL=http://127.0.0.1:9222  → auto_record 采集复用此窗口
凭据读 server/.env（与 auto_record 同款条件式登录，不入库不打印）。
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
EXT_DIST = ROOT / "extension" / "dist"


async def login_in_page(page, user: str, password: str, login_url: str) -> None:
    await page.goto(login_url)
    await page.wait_for_load_state("domcontentloaded", timeout=15000)
    await page.wait_for_timeout(2000)
    pwd = page.locator('input[type="password"]')
    if await pwd.count() == 0:
        return  # profile 已带会话
    await page.get_by_role("textbox").first.fill(user)
    await pwd.first.fill(password)
    await page.get_by_role("button").filter(has_text="登").first.click()
    await page.wait_for_timeout(3000)


async def main() -> None:
    from dotenv import dotenv_values
    cfg = dotenv_values(ROOT / "server" / ".env")
    login_url = cfg.get("NJMIND_LOGIN_URL") or "http://192.168.99.22/mb3/1/"
    port = sys.argv[1] if len(sys.argv) > 1 else "9222"

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            str(Path("/tmp/skilllens-live-profile")),
            headless=False,
            args=[
                f"--disable-extensions-except={EXT_DIST}",
                f"--load-extension={EXT_DIST}",
                f"--remote-debugging-port={port}",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            timeout=60000,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await login_in_page(page, cfg.get("NJMIND_USER") or "",
                            cfg.get("NJMIND_PASS") or "", login_url)
        print(f"常驻浏览器已就绪：CDP http://127.0.0.1:{port}（Ctrl+C 关闭）")
        while True:
            await asyncio.sleep(3600)


if __name__ == "__main__":
    asyncio.run(main())
