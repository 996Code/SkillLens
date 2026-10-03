"""AG0 spike 驱动：独立浏览器加载 spike 插件，验证 chrome.debugger 四件事。

验证矩阵：
  A. attach → 可信点击（isTrusted=true+框架状态更新）→ 网络体捕获 → detach
  B. SW 保活：debugger 事件驱动期间 SW 计数连续（30s 观察窗）
  C. attach 冲突：页面开着 DevTools 时 attach 行为（预期失败/报错形态记录）

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. uv run python ../spike/ag0_drive.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from playwright.async_api import async_playwright

SPIKE_DIR = Path(__file__).resolve().parent
EXT_DIR = SPIKE_DIR / "ag0-ext"
PAGE_FILE = SPIKE_DIR / "ag0-page.html"


async def find_sw(ctx):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        for w in ctx.service_workers:
            if "ag0-ext" in w.url or "sw.js" in w.url:
                return w
        await asyncio.sleep(0.5)
    return None


async def ext_call(ctx, sw, msg):
    ext_id = sw.url.split("/")[2]
    page = await ctx.new_page()
    try:
        await page.goto(f"chrome-extension://{ext_id}/_generated_background_page.html")
    except Exception:
        pass
    try:
        return await page.evaluate(
            "(m) => new Promise(res => chrome.runtime.sendMessage(m, r => res(r)))", msg)
    finally:
        await page.close()


async def main():
    print("=== AG0 spike：chrome.debugger 四件事 ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=str(SPIKE_DIR / "ag0-profile"),
            headless=False,
            args=[f"--disable-extensions-except={EXT_DIR}", f"--load-extension={EXT_DIR}"],
        )
        ctx = browser
        # 测试页走 mock.local（route 拦截内联 HTML+API——fetch 相对路径可用）
        await ctx.route("http://mock.local/**", lambda route: (
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": "ag0-body-captured"}))
            if "/api/spike" in route.request.url else
            route.fulfill(status=200, content_type="text/html; charset=utf-8",
                          body=PAGE_FILE.read_text(encoding="utf-8"))
        ))

        sw = await find_sw(ctx)
        if sw is None:
            print("! SW 未找到（插件未加载）")
            await browser.close()
            return
        print(f"SW: {sw.url.split('/')[2]}")

        target = await ctx.new_page()
        await target.goto("http://mock.local/ag0-page")
        await target.wait_for_load_state("domcontentloaded")
        await target.wait_for_timeout(1000)

        # A: 四件事（SW 自己枚举 mock.local 的 tab）
        results = await ext_call(ctx, sw, {"type": "AG0_RUN", "testUrl": "http://mock.local/ag0-page"})
        print(json.dumps(results, ensure_ascii=False, indent=2))

        # B: SW 保活（30s 观察窗，每 5s 探一次计数）
        print("\n--- SW 保活观察（30s）---")
        counts = []
        for _ in range(7):
            r = await ext_call(ctx, sw, {"type": "AG0_KEEPALIVE"})
            counts.append((r or {}).get("keepaliveCount"))
            await asyncio.sleep(5)
        print(f"keepalive 计数序列: {counts}")
        print(f"结论: {'SW 存活（单调递增）' if all(b > a for a, b in zip(counts, counts[1:])) else 'SW 被杀重建（计数归零）'}")

        # C: attach 冲突——模拟另一调试器占用（第二次 attach 同 tab）
        conflict = await ext_call(ctx, sw, {"type": "AG0_CONFLICT", "testUrl": "http://mock.local/ag0-page"})
        print(f"\nattach 冲突形态: {conflict}")

        await browser.close()


asyncio.run(main())
