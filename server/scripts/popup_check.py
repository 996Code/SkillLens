import asyncio
import json
import sys
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"
EXT = sys.argv[1]


def _get(u):
    return json.loads(urllib.request.urlopen(u, timeout=10).read())


async def main():
    ver = _get(f"{CDP}/json/version")
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                  "params": {"url": f"chrome-extension://{EXT}/popup.html"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 1:
                tid = m["result"]["targetId"]
                break
    await asyncio.sleep(3)
    tgt = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == tid)
    async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=10**7) as sw:
        await sw.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {
            "expression": "document.getElementById('exec-list')?.innerText || 'NO_LIST'"}}))
        while True:
            m = json.loads(await asyncio.wait_for(sw.recv(), 15))
            if m.get("id") == 2:
                print(str(m.get("result", {}).get("result", {}).get("value"))[:800])
                break
    # 关掉 popup tab
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 3, "method": "Target.closeTarget",
                                  "params": {"targetId": tid}}))

asyncio.run(main())
