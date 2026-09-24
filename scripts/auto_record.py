"""带 SkillLens 插件自动采集 njmind 操作（CDP 闭环实测/固化）。

流程：launch_persistent_context(--load-extension) → 找到扩展 SW 页 →
runtime.sendMessage START_RECORDING → CDP 语义操作表单（输入+保存）→
STOP_RECORDING → 轮询 server 确认事件落库。

用法：
    cd server && uv run python ../scripts/auto_record.py [--note 备注]
环境：server 需在 127.0.0.1:8710 运行；登录态自动经插件所在浏览器内完成
（复用 njmind_login 的表单逻辑，凭据读 server/.env，不入库不打印）。
"""
import asyncio
import json
import sys
import urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
EXT_DIST = ROOT / "extension" / "dist"
SERVER = "http://127.0.0.1:8710"
FORM_URL = "http://192.168.99.22/mb3/1/mind-designer/field-edit?formCode=ceshi000001"
NOTE = "auto-record-e2e"


async def login_in_page(page, user: str, password: str, login_url: str) -> None:
    """条件式登录：profile 可能已带 njmind 会话（goto 直接进主界面），
    仅当页面上存在密码框时才执行登录表单流程。"""
    await page.goto(login_url)
    await page.wait_for_load_state("domcontentloaded", timeout=15000)
    await page.wait_for_timeout(2000)
    pwd = page.locator('input[type="password"]')
    if await pwd.count() == 0:
        return  # 已登录（profile 复用会话）
    await page.get_by_role("textbox").first.fill(user)
    await pwd.first.fill(password)
    await page.get_by_role("button").filter(has_text="登").first.click()
    await page.wait_for_timeout(3000)


async def find_service_worker(ctx) -> object:
    for _ in range(20):
        for w in ctx.service_workers:
            if "service-worker-loader" in w.url or "uploader" in w.url:
                return w
        await asyncio.sleep(0.5)
    raise RuntimeError("extension service worker 未找到")


async def ext_call(ctx, sw, msg: dict) -> object:
    """从扩展自身页面（popup 同源）发 runtime 消息——SW 自发自收不触发
    onMessage，必须经扩展页面上下文中转。"""
    ext_id = sw.url.split("/")[2]
    page = await ctx.new_page()
    try:
        await page.goto(f"chrome-extension://{ext_id}/popup.html")
        return await page.evaluate(
            """(m) => new Promise(res => chrome.runtime.sendMessage(m, r => res(r)))""",
            msg)
    finally:
        await page.close()


async def main() -> None:
    from dotenv import dotenv_values
    cfg = dotenv_values(ROOT / "server" / ".env")
    user = cfg.get("NJMIND_USER") or ""
    password = cfg.get("NJMIND_PASS") or ""
    login_url = cfg.get("NJMIND_LOGIN_URL") or "http://192.168.99.22/mb3/1/"
    if "--note" in sys.argv:
        NOTE = sys.argv[sys.argv.index("--note") + 1]

    try:
        async with async_playwright() as p:
            ctx = await p.chromium.launch_persistent_context(
                str(Path("/tmp/skilllens-ext-profile")),
                headless=False,
                args=[
                    f"--disable-extensions-except={EXT_DIST}",
                    f"--load-extension={EXT_DIST}",
                ],
                timeout=60000,
            )
            sw = await find_service_worker(ctx)

            # 1) 同浏览器内先登录（拿到 njmind 会话 cookie，后续表单页可访问）
            login_page = await ctx.new_page()
            await login_in_page(login_page, user, password, login_url)

            # 2) 开录制
            r = await ext_call(ctx, sw, {"type": "START_RECORDING", "note": NOTE})
            print("start_recording:", r)
            sid = (r or {}).get("id")

            # 3) CDP 语义操作表单：改表单名 + 保存（与回放同款语义定位）
            page = await ctx.new_page()
            await page.goto(FORM_URL)
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
            # 表单名输入框 = 第一个"请输入"（disabled 的 code 框不可填）
            await page.get_by_placeholder("请输入").first.fill(f"auto-{NOTE}")
            await page.get_by_role("button", name="保存").click()
            await page.wait_for_timeout(3000)

            # 4) 停录制（SW 内先终报再清标记）
            r = await ext_call(ctx, sw, {"type": "STOP_RECORDING"})
            print("stop_recording:", r)
            await ctx.close()
    finally:
        import subprocess
        subprocess.run(["pkill", "-f", "skilllens-ext-profile"],
                       capture_output=True)

    # 5) 落库验证：server 无事件查询端点，直接查 SQLite（与 server 同目录）
    import sqlite3
    db = sqlite3.connect(ROOT / "server" / "skilllens.db")
    n = db.execute("SELECT COUNT(*) FROM raw_event WHERE session_id=?",
                   (sid,)).fetchone()[0]
    kinds = db.execute(
        "SELECT kind, COUNT(*) FROM raw_event WHERE session_id=? GROUP BY kind",
        (sid,)).fetchall()
    sample = db.execute(
        "SELECT kind, substr(payload,1,120) FROM raw_event WHERE session_id=? "
        "AND kind='action' LIMIT 3", (sid,)).fetchall()
    db.close()
    print(f"raw_event 总数: {n}")
    print(f"分类: {kinds}")
    for k, s in sample:
        print(f"  {k}: {s}")
    if n == 0:
        sys.exit("FAIL: 零事件落库——CDP 事件未被采集层捕获")


if __name__ == "__main__":
    asyncio.run(main())
