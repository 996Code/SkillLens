"""AF4 真机收口：清单驱动走查录制（禅道 QA 首验证）。

链路：adapters/zentao.yaml → login（AF3）→ 每 flow：SW START_RECORDING →
run_steps 走查（${data} 按轮次注入"甲/乙"）→ STOP → process/align/induce
（学习管道，同 s43 模式）。

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/af4_record.py [adapter_id]
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from playwright.async_api import async_playwright

from app.adapters.flows import build_flow_script
from app.adapters.manifest import load_adapter_dir
from app.adapters.steps import run_step, login as adapter_login

SERVER = "http://127.0.0.1:8710/api/v1"
CDP = "http://127.0.0.1:9222"


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


async def find_sw(ctx):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        for w in ctx.service_workers:
            if "uploader" in w.url or "service-worker-loader" in w.url:
                return w
        await asyncio.sleep(1)
    return None


async def ext_call(ctx, sw, msg):
    ext_id = sw.url.split("/")[2]
    page = await ctx.new_page()
    try:
        await page.goto(f"chrome-extension://{ext_id}/popup.html")
        return await page.evaluate(
            "(m) => new Promise(res => chrome.runtime.sendMessage(m, r => res(r)))", msg)
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def record_flow(token, ctx, page, manifest, flow, data):
    print(f"  录制 {flow['flow']}（{data}）")
    sw = await find_sw(ctx)
    if not sw:
        print("  ! SW 未找到")
        return None
    r = await ext_call(ctx, sw, {"type": "START_RECORDING",
                                 "note": f"af4-{flow['flow']}"})
    sid = (r or {}).get("id", "")
    if not sid:
        print("  ! 无法开始录制")
        return None
    try:
        for step in flow["steps"]:
            # ${data} 轮次注入（甲/乙——同 s43 语义）
            if step.arg2 == "${data}":
                step = step.model_copy(update={"arg2": data})
            elif step.arg == "${data}":
                step = step.model_copy(update={"arg": data})
            await run_step(page, manifest, step)
    except Exception as e:
        print(f"  ! 走查异常: {type(e).__name__}: {str(e)[:100]}")
    await asyncio.sleep(1.5)
    await ext_call(ctx, sw, {"type": "STOP_RECORDING"})
    await asyncio.sleep(2.5)
    async with httpx.AsyncClient(timeout=120) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        resp = await c.get(f"{SERVER.replace('/api/v1', '')}/api/v1/audit/sessions")
        target = [s for s in resp.json() if s["session_id"] == sid]
        if not target:
            print("  ! 会话未落库")
            return None
        print(f"  事件数: {target[0]['event_count']}")
        return sid


async def learn(token, sids):
    async with httpx.AsyncClient(timeout=180) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        for sid in sids:
            resp = await c.post(f"{SERVER}/sessions/{sid}/process")
            if resp.status_code != 200:
                print(f"  process: {resp.status_code} {resp.text[:80]}")
                return None
        resp = await c.post(f"{SERVER}/align", json={"session_ids": sids})
        if resp.status_code != 200:
            print(f"  align: {resp.status_code}")
            return None
        aid = resp.json()["alignment_id"]
        for _ in range(3):
            try:
                resp = await c.post(f"{SERVER}/alignments/{aid}/induce")
                if resp.status_code == 200:
                    break
            except Exception:
                await asyncio.sleep(5)
        else:
            return None
        skill = resp.json()
        await c.post(f"{SERVER}/skills/{skill['id']}/assertions")
        return skill


async def main():
    adapter_id = sys.argv[1] if len(sys.argv) > 1 else "zentao"
    print(f"=== AF4 清单驱动走查录制：{adapter_id} ===")
    manifests, _ = load_adapter_dir(Path(__file__).resolve().parent.parent / "adapters")
    m = {x.id: x for x in manifests}[adapter_id]
    flows = build_flow_script(m)
    if not flows:
        print("清单无 flows——该系统走人工走查模式（设计原则③）")
        return
    token = mint_token()
    ts = int(time.time()) % 100000
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = ctx.pages[0]
        if not await adapter_login(page, m):
            print("! 登录失败")
            return
        for flow in flows:
            sids = []
            for mark in ["甲", "乙"]:
                sid = await record_flow(token, ctx, page, m, flow, f"{mark}{ts}")
                if sid:
                    sids.append(sid)
            if sids:
                skill = await learn(token, sids)
                if skill:
                    print(f"  → skill #{skill['id']} {skill['name']} ({skill['status']})")


if __name__ == "__main__":
    asyncio.run(main())
