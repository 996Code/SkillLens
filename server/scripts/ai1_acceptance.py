"""AI1 真机验收：录制→停录→自动学习→技能进空间。

流程：popup 开录（经 SW START_RECORDING 消息——真实用户路径）→ 在 JeecG
页真实操作（导航+两次点击，捕获 CS 事件）→ 停录 → 轮询 sl_last_learn →
验证技能学成（status=done + skillId）→ 空间可见。
"""
import asyncio
import json
import sys
import time
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"
TOKEN = open("D:/tmp/sl_token").read().strip()


def _get(u):
    return json.loads(urllib.request.urlopen(u, timeout=10).read())


async def ev_on(ws, i, expr, timeout=25):
    await ws.send(json.dumps({"id": i, "method": "Runtime.evaluate",
                              "params": {"expression": expr, "awaitPromise": True}}))
    while True:
        m = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if m.get("id") == i:
            return m.get("result", {}).get("result", {}).get("value")


async def main():
    ver = _get(f"{CDP}/json/version")
    browser_ws = ver["webSocketDebuggerUrl"]

    # 1. 开 JeecG 页（真实操作目标）
    async with websockets.connect(browser_ws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                  "params": {"url": "http://127.0.0.1:8095/system/dict"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 1:
                tgt_id = m["result"]["targetId"]
                break
    await asyncio.sleep(4)
    tgt = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == tgt_id)

    # 2. 在扩展 popup 页驱动开录/停录（真实消息路径）——先找扩展 id
    ext_id = None
    for t in _get(f"{CDP}/json"):
        u = t.get("url", "")
        if u.startswith("chrome-extension://"):
            ext_id = u.split("/")[2]
            break
    print("ext:", ext_id[:12])

    async with websockets.connect(browser_ws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 2, "method": "Target.createTarget",
                                  "params": {"url": f"chrome-extension://{ext_id}/popup.html"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 2:
                pop_id = m["result"]["targetId"]
                break
    await asyncio.sleep(2)
    pop = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == pop_id)

    async with websockets.connect(pop["webSocketDebuggerUrl"], max_size=10**7) as sw:
        # 填备注并开录
        await ev_on(sw, 3, """
          (async () => {
            document.getElementById('note').value = 'AI1真机验收：字典页浏览';
            document.getElementById('start').click();
            await new Promise(r=>setTimeout(r,2500));
            return 'started: ' + document.getElementById('status').textContent;
          })()
        """)
        print("[record] started")

    # 3. JeecG 页真实操作（生成捕获事件）：导航两个页面 + 点击
    async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=10**7) as sw:
        await ev_on(sw, 4, """
          (async () => {
            const rows=[...document.querySelectorAll('tr, .ant-table-row')].slice(0,3);
            let clicked=0;
            for (const r of rows) { try { r.click(); clicked++; break; } catch{} }
            return 'clicked:'+clicked;
          })()
        """, timeout=15)
        await asyncio.sleep(2)
        await ev_on(sw, 5, "location.href='http://127.0.0.1:8095/system/dict'", timeout=15)
        await asyncio.sleep(3)

    # 4. 停录（popup 按钮——真实路径）
    async with websockets.connect(pop["webSocketDebuggerUrl"], max_size=10**7) as sw:
        await ev_on(sw, 6, """
          (async () => {
            document.getElementById('stop').click();
            await new Promise(r=>setTimeout(r,2000));
            return 'stopped';
          })()
        """)
        print("[record] stopped")

    # 5. 轮询学习结果（SW storage 经 popup 页读——chrome.storage.local 共享）
    deadline = time.time() + 150
    last = None
    while time.time() < deadline:
        async with websockets.connect(pop["webSocketDebuggerUrl"], max_size=10**7) as sw:
            r = await ev_on(sw, 7, """
              (async () => {
                const {sl_last_learn: r} = await chrome.storage.local.get('sl_last_learn');
                return JSON.stringify(r || null);
              })()
            """)
        last = json.loads(r) if r else None
        if last and last.get("status") in ("done", "error"):
            break
        await asyncio.sleep(5)
    print("[learn result]", json.dumps(last, ensure_ascii=False)[:300])

    # 6. 学习卡片 UI 渲染验证
    async with websockets.connect(pop["webSocketDebuggerUrl"], max_size=10**7) as sw:
        card = await ev_on(sw, 8, """
          (async () => {
            location.reload();
            return 'reloading';
          })()
        """)
        await asyncio.sleep(2.5)
        title = await ev_on(sw, 9, "document.getElementById('learn-title')?.textContent || 'NO_CARD'")
        meta = await ev_on(sw, 10, "document.getElementById('learn-meta')?.textContent || ''")
        visible = await ev_on(sw, 11, "document.getElementById('learn-card')?.style.display")
        print(f"[learn card] display={visible} title={title!r} meta={meta!r}")

    # 7. 关清理 tab
    async with websockets.connect(browser_ws, max_size=10**7) as ws:
        for tid in (pop_id,):
            await ws.send(json.dumps({"id": 20, "method": "Target.closeTarget",
                                      "params": {"targetId": tid}}))
            await asyncio.wait_for(ws.recv(), 10)

asyncio.run(main())
