"""S32 链路时间线浏览器实测：真实用户路径操作 + 截图入库。

流程：注入 token（本地铸的 admin 测试 token，不经登录页）→
  ① /timeline 时间轴渲染（类型徽标/摘要/计数 chip）
  ② 类型过滤（点 LLM chip 只剩 llm 项）
  ③ LLM 项点击展开完整 prompt/response（IO 全留存核心验收）
  ④ skill 项展开下钻链接 → 跳 Skill 详情
截图存 demo/sprint32/screenshots/。
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from playwright.async_api import async_playwright  # noqa: E402

BASE = os.environ.get("SL_BASE", "http://127.0.0.1:8710")
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint32" / "screenshots"


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

        # 先开一次域再注入 localStorage（token + user）
        await page.goto(f"{BASE}/login")
        await page.evaluate(
            """([t]) => {
                localStorage.setItem('sl_token', t);
                localStorage.setItem('sl_user',
                    JSON.stringify({id: 1, username: 'admin', role: 'admin'}));
            }""",
            [token],
        )

        # ① 时间轴渲染
        await page.goto(f"{BASE}/timeline")
        await page.wait_for_selector("[data-testid='timeline-list']")
        items = await page.locator(".tl-item").count()
        print(f"[1] timeline items rendered: {items}")
        assert items > 0, "timeline empty"
        text = await page.inner_text("[data-testid='timeline-list']")
        assert "Skill #" in text or "采集" in text, "no recognizable titles"
        await page.screenshot(path=str(OUT / "01-timeline.png"), full_page=False)

        # ② 类型过滤
        await page.click("[data-testid='filter-llm']")
        await page.wait_for_timeout(300)
        llm_only = await page.locator(".tl-item").count()
        print(f"[2] after llm filter: {llm_only} items (all llm)")
        assert llm_only > 0
        llm_items = await page.locator(".tl-item[data-testid='tl-llm']").count()
        assert llm_items == llm_only, f"non-llm items leaked: {llm_items}/{llm_only}"
        await page.screenshot(path=str(OUT / "02-filter-llm.png"))
        await page.click("[data-testid='filter-llm']")  # 取消过滤
        await page.wait_for_timeout(300)

        # ③ LLM 项展开完整 IO
        await page.click("[data-testid='tl-llm']")
        await page.wait_for_selector("[data-testid='llm-detail']")
        await page.wait_for_timeout(500)
        detail = await page.inner_text("[data-testid='llm-detail']")
        assert "prompt" in detail and "response" in detail, "llm io missing"
        print(f"[3] llm detail expanded, chars: {len(detail)}")
        await page.locator("[data-testid='llm-detail']").scroll_into_view_if_needed()
        await page.screenshot(path=str(OUT / "03-llm-io.png"))

        # ④ skill 项下钻
        await page.click("[data-testid='tl-skill']")
        await page.wait_for_selector(".tl-links a")
        await page.click(".tl-links a")
        await page.wait_for_url("**/skills/*", timeout=10_000)
        print(f"[4] drill-down ok: {page.url}")
        await page.screenshot(path=str(OUT / "04-skill-drilldown.png"))

        await browser.close()
    print("S32 browser verification PASSED")


asyncio.run(main())
