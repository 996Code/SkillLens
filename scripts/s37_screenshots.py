"""S37-2 浏览器实测：时间线测试活动视角 + 断言语义修正后的回放。

路径：/timeline（测试活动主行）→ recording 展开学到的流程 → test_run 展开
截图墙 → 内部事件开关 → run 详情页。截图存 demo/sprint37/screenshots/。
"""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from playwright.async_api import async_playwright  # noqa: E402

BASE = os.environ.get("SL_BASE", "http://127.0.0.1:8710")
OUT = Path(__file__).resolve().parent.parent / "demo" / "sprint37" / "screenshots"


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
        page = await (await browser.new_context(viewport={"width": 1400, "height": 960})).new_page()
        await page.goto(f"{BASE}/login")
        await page.evaluate(
            """([t]) => {
                localStorage.setItem('sl_token', t);
                localStorage.setItem('sl_user',
                    JSON.stringify({id: 1, username: 'admin', role: 'admin'}));
            }""",
            [token],
        )

        # ① 测试活动主行（默认无内部事件）
        await page.goto(f"{BASE}/timeline")
        await page.wait_for_selector("[data-testid='timeline-list']")
        await page.wait_for_timeout(800)
        types = await page.evaluate(
            """() => [...new Set(Array.from(document.querySelectorAll('.tl-item'))
                .map(e => e.dataset.testid.replace('tl-', '')))]""")
        print("[1] 主行类型:", types)
        assert set(types) <= {"test_run", "recording"}, types
        assert "test_run" in types and "recording" in types
        await page.screenshot(path=str(OUT / "01-test-activity.png"))

        # ② recording 展开学到的操作流程
        rec = page.locator("[data-testid='tl-recording']").first
        await rec.click()
        await page.wait_for_selector("[data-testid='rec-detail']")
        detail = await page.inner_text("[data-testid='rec-detail']")
        assert "学到的操作流程" in detail
        print("[2] recording 展开含学习产出清单")
        await page.screenshot(path=str(OUT / "02-recording-skills.png"))

        # ③ test_run 展开截图墙
        tr = page.locator("[data-testid='tl-test_run']").first
        await tr.click()
        await page.wait_for_timeout(2000)
        has_shots = await page.locator("[data-testid='shot-grid']").count()
        has_link = await page.locator(".shot-links a").count()
        print(f"[3] test_run 展开：截图墙={has_shots > 0} 下钻链接={has_link > 0}")
        await page.screenshot(path=str(OUT / "03-test-run-shots.png"))

        # ④ 内部事件开关
        await page.locator("[data-testid='internal-toggle'] input").check()
        await page.wait_for_timeout(1500)
        types2 = await page.evaluate(
            """() => [...new Set(Array.from(document.querySelectorAll('.tl-item'))
                .map(e => e.dataset.testid.replace('tl-', '')))]""")
        print("[4] 开内部事件后类型:", types2)
        assert "llm" in types2
        await page.screenshot(path=str(OUT / "04-internal-events.png"))

        # ⑤ run 191（断言修正后 pass 的 ERPNext run）详情页
        await page.goto(f"{BASE}/replay-runs/191")
        await page.wait_for_selector(".run-status")
        status = await page.inner_text(".run-status")
        print(f"[5] run 191 状态: {status}")
        assert status == "pass"
        await page.screenshot(path=str(OUT / "05-run-191-pass.png"))

        await browser.close()
    print("S37-2 browser verification PASSED")


asyncio.run(main())
