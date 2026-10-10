"""AN E2E 第二轮：录制 Snipe「查找点行」+「行内 Update」技能对。

验收场景（docs/specs/2026-10-10-an-cross-step-state.md §五）：
- 技能 A（查找点行）：搜索 eate25244乙 → 点击行 tag 链接（row-trigger
  → pickedRow="eate25244乙"）
- 技能 B（行内 Update）：goto /hardware → 点首行 Update（录制锚=首行
  SN-eate25514甲）
- 链 A→B（row_anchor_from=1）：B 的行锚注入 A 的 pickedRow → B 应点
  eate25244乙 行的 Update（非录制时的首行）——URL 可验证。

用法：cd server && RECORD_CDP_URL=http://127.0.0.1:9222 uv run python
../scripts/an_snipe_record.py
"""
import asyncio
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
SERVER = "http://127.0.0.1:8710/api/v1"
HARDWARE = "http://127.0.0.1:8081/hardware"
TAG_A = "eate25244乙"  # A 搜索并点击的行（列表末位——远离首行）


async def find_service_worker(ctx):
    for _ in range(30):
        for w in ctx.service_workers:
            if "service-worker-loader" in w.url or "uploader" in w.url:
                return w
        await asyncio.sleep(1)
    raise RuntimeError("extension service worker 未找到")


async def ext_call(ctx, sw, msg: dict):
    ext_id = sw.url.split("/")[2]
    page = await ctx.new_page()
    try:
        await page.goto(f"chrome-extension://{ext_id}/popup.html")
        return await page.evaluate(
            "(m) => new Promise(res => chrome.runtime.sendMessage(m, r => res(r)))",
            msg)
    finally:
        await page.close()


async def get_token() -> str:
    import httpx
    async with httpx.AsyncClient(timeout=15.0) as c:
        c.headers["X-SkillLens-Agent"] = "1"
        r = await c.post(f"{SERVER}/auth/plugin-session")
        return r.json()["token"]


async def record_flow(ctx, page, note: str, flow) -> str | None:
    sw = await find_service_worker(ctx)
    r = await ext_call(ctx, sw, {"type": "START_RECORDING", "note": note,
                                 "source": "demo"})
    sid = (r or {}).get("id", "")
    if not sid:
        print("  ! 无法开始录制")
        return None
    try:
        await flow(page)
    except Exception as e:
        print(f"  ! 操作异常: {type(e).__name__}: {str(e)[:120]}")
    await page.wait_for_timeout(1500)
    await ext_call(ctx, sw, {"type": "STOP_RECORDING"})
    await page.wait_for_timeout(2500)
    return sid


async def flow_a(page) -> None:
    """技能 A：goto /hardware → 点击 eate25244乙 行的 tag 链接（进资产详情）。
    （搜索框 fill 超时不可用——列表全量下 locator 直达行链接，录制语义
    同等：row-trigger 命中即产出 pickedRow）"""
    await page.goto(HARDWARE)
    await page.wait_for_timeout(3000)
    link = page.locator("table tbody tr a", has_text=TAG_A).first
    await link.click()
    await page.wait_for_timeout(2500)


async def flow_b(page) -> None:
    """技能 B：goto /hardware → 点首行 Update（录制锚=首行 SN-eate25514甲）。"""
    await page.goto(HARDWARE)
    await page.wait_for_timeout(3000)
    # 首行的 Update 行操作链接
    row = page.locator("table tbody tr").first
    await row.locator("a", has_text="Update").first.click()
    await page.wait_for_timeout(2500)


async def process_and_learn(token: str, sids: list[str]):
    import httpx
    async with httpx.AsyncClient(timeout=180.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        for sid in sids:
            resp = await c.post(f"{SERVER}/sessions/{sid}/process")
            print(f"  process {sid[:8]}: {resp.status_code}")
        # 单会话技能：align 需 ≥2——同会话双列（_seed_skill 同款）
        resp = await c.post(f"{SERVER}/align", json={"session_ids": [sids[0], sids[0]]})
        aid = resp.json()["alignment_id"]
        print(f"  align: {resp.status_code} aid={aid}")
        skill = None
        for _ in range(3):
            resp = await c.post(f"{SERVER}/alignments/{aid}/induce")
            if resp.status_code == 200:
                skill = resp.json()
                break
        if not skill:
            print("  ! induce 失败")
            return None
        print(f"  induce: skill #{skill['id']} {skill['name']}")
        resp = await c.post(f"{SERVER}/skills/{skill['id']}/assertions")
        print(f"  assertions: {resp.status_code}")
        return skill["id"]


async def main() -> None:
    cdp = "http://127.0.0.1:9222"
    token = await get_token()
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp)
        ctx = next((c for c in browser.contexts if c.service_workers),
                   browser.contexts[0])
        page = await ctx.new_page()

        print("== 录制 A（查找点行）==")
        sid_a = await record_flow(ctx, page, "an-snipe-search-click", flow_a)
        print("== 录制 B（行内 Update）==")
        sid_b = await record_flow(ctx, page, "an-snipe-row-update", flow_b)
        await page.close()

        if not (sid_a and sid_b):
            sys.exit("录制失败")
        print("== 学习 A ==")
        sk_a = await process_and_learn(token, [sid_a])
        print("== 学习 B ==")
        sk_b = await process_and_learn(token, [sid_b])
        if not (sk_a and sk_b):
            sys.exit("学习失败")
        print(f"\n技能对就绪: A=#{sk_a} B=#{sk_b}")
        print(f"建链: POST /chains steps=[A, B(row_anchor_from=1)]")
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as c:
            c.headers["Authorization"] = f"Bearer {token}"
            r = await c.post(f"{SERVER}/chains", json={
                "name": "AN验收2：查找点行→行内Update（行锚注入）",
                "system": "Snipe 资产",
                "steps": [
                    {"skill_id": sk_a, "overrides": {}},
                    {"skill_id": sk_b, "overrides": {}, "row_anchor_from": 1},
                ],
            })
            print("建链:", r.status_code, r.json().get("id"))


if __name__ == "__main__":
    asyncio.run(main())
