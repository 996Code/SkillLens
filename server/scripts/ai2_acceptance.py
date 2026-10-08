"""AI2 跨步传值真机验收：链 3（269 unique 建表 → 132 字典编码绑 step1 表名）。"""
import asyncio
import json
import sys
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"


def _get(u):
    return json.loads(urllib.request.urlopen(u, timeout=10).read())


async def main():
    ext = next((t["url"].split("/")[2] for t in _get(f"{CDP}/json")
                if (t.get("url") or "").startswith("chrome-extension://")
                and t.get("type") == "service_worker"), None)
    if not ext:
        print("[no ext sw] targets:", [(t.get("type"), (t.get("url") or "")[:40]) for t in _get(f"{CDP}/json")][:6])
        return
    chain_id = open("D:/tmp/chain_ai2.txt").read().strip()
    token = open("D:/tmp/sl_token").read().strip()
    ver = _get(f"{CDP}/json/version")
    url = f"chrome-extension://{ext}/executor.html?chain={chain_id}&token={token}&auto=1"
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                  "params": {"url": url}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 1:
                tid = m["result"]["targetId"]
                break
    await asyncio.sleep(3)
    tgt = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == tid)
    async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=10**7) as sw:
        await sw.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
            "expression": "document.getElementById('go')?.click(); 'clicked'"}}))
        await asyncio.wait_for(sw.recv(), 10)
    for i in range(70):
        await asyncio.sleep(5)
        tgt2 = next((t for t in _get(f"{CDP}/json/list") if t.get("id") == tid), None)
        if not tgt2:
            print("[tab closed]")
            return
        try:
            async with websockets.connect(tgt2["webSocketDebuggerUrl"], max_size=10**7) as sw:
                await sw.send(json.dumps({"id": 3, "method": "Runtime.evaluate", "params": {
                    "expression": "document.getElementById('log')?.textContent || ''"}}))
                while True:
                    m = json.loads(await asyncio.wait_for(sw.recv(), 15))
                    if m.get("id") == 3:
                        log = str(m.get("result", {}).get("result", {}).get("value", ""))
                        if "链执行结束" in log:
                            print(log[-1600:])
                            return
                        break
        except Exception:
            pass
    print("[timeout 350s]")

asyncio.run(main())
