"""S34 块 2：Odoo 数据库初始化 + 登录验证（本地 Docker 测试 ERP）。

流程：/web/database/manager 建库（master pwd 默认 admin）→ 等待初始化 →
登录验证 → 输出确认。凭据走环境变量（本地测试实例，缺省值仅本机有效）。
"""
import asyncio
import os
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ODOO = os.environ.get("ODOO_URL", "http://127.0.0.1:8069")
DB_NAME = os.environ.get("ODOO_DB", "skilllens-demo")
LOGIN = os.environ.get("ODOO_LOGIN", "admin@local.test")
PASSWORD = os.environ.get("ODOO_PASSWORD", "odoo-admin-local")


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 960})
        await page.goto(f"{ODOO}/web/database/manager")
        await page.wait_for_load_state("domcontentloaded")

        # 已有库则跳过建库
        if "/web/database/selector" not in page.url and "login" in (page.url or ""):
            print("database exists, skip creation")
        else:
            form = page.locator("form[action='/web/database/create']").first
            await form.locator("input[name='master_pwd']").fill("admin")
            await form.locator("input[name='name']").fill(DB_NAME)
            await form.locator("input[name='login']").fill(LOGIN)
            await form.locator("input[name='password']").fill(PASSWORD)
            await form.locator("input[type='submit']").first.click()
            # 建库含模块安装，最长 5 分钟；完成后跳 Odoo 主界面或登录页
            await page.wait_for_url("**/web**", timeout=300_000)
            print(f"database '{DB_NAME}' created")

        # 登录验证
        await page.goto(f"{ODOO}/web/login")
        await page.locator("input[name='login']").fill(LOGIN)
        await page.locator("input[name='password']").fill(PASSWORD)
        await page.locator("button[type='submit']").click()
        await page.wait_for_url("**/odoo/**", timeout=60_000)
        title = await page.title()
        print(f"login ok: {page.url} ({title})")

        out = Path(__file__).resolve().parent.parent / "demo" / "sprint34" / "screenshots"
        out.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(out / "05-odoo-home.png"))
        await browser.close()
    print("Odoo init PASSED")


asyncio.run(main())
