"""经扩展自己的页面（executor.html 宿主）向 SW 发真实 STOP 消息并观察。

页面→SW 的 runtime.sendMessage 是真实路径（popup 同款）；避开 SW 自发
不触发 onMessage 的坑。流程：页面里 start→stop→轮询 storage。
"""
import asyncio
import json
import sys
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"


def _get(u):
    return json.loads(urllib.request.urlopen(u, timeout=10).read())


async def main():
    ver = _get(f"{CDP}/json/version")
    bws = ver["webSocketDebuggerUrl"]
    ext_id = sys.argv[1]

    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                  "params": {"url": f"chrome-extension://{ext_id}/executor.html"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 1:
                page_id = m["result"]["targetId"]
                break
    await asyncio.sleep(2)
    page = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == page_id)

    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def ev(i, expr, timeout=30):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), timeout))
                if m.get("id") == i:
                    r = m.get("result", {})
                    if r.get("exceptionDetails"):
                        return "EXC:" + str(r["exceptionDetails"])[:200]
                    return r.get("result", {}).get("value")

        r1 = await ev(2, """(async () => {
          const s = await chrome.runtime.sendMessage({type:'START_RECORDING', note:'page-path-debug'});
          await new Promise(r=>setTimeout(r,2000));
          const st = await chrome.runtime.sendMessage({type:'GET_STATE'});
          return JSON.stringify({started:s, state:st});
        })()""")
        print("[start]", r1)
        r2 = await ev(3, """(async () => {
          const r = await chrome.runtime.sendMessage({type:'STOP_RECORDING'});
          return JSON.stringify(r);
        })()""")
        print("[stop resp]", r2)
        # 轮询 learn 结果
        for _ in range(24):
            await asyncio.sleep(5)
            r3 = await ev(4 + _ % 20, """(async () => {
              const {sl_last_learn: r} = await chrome.storage.local.get('sl_last_learn');
              return JSON.stringify(r ?? null);
            })()""")
            v = json.loads(r3) if r3 and r3 != "null" else None
            if v and v.get("status") in ("done", "error"):
                print("[learn]", json.dumps(v, ensure_ascii=False)[:250])
                break
            print("[poll]", r3[:80] if r3 else None)
        else:
            print("[learn timeout 120s]")

    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 90, "method": "Target.closeTarget",
                                  "params": {"targetId": page_id}}))
        await asyncio.wait_for(ws.recv(), 10)

asyncio.run(main())
