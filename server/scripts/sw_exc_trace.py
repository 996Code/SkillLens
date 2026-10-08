"""SW 异常打捞：先 enable Runtime，再从页面路径触发 stop，收 console/异常。"""
import asyncio
import json
import sys
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"


def _get(u):
    return json.loads(urllib.request.urlopen(u, timeout=10).read())


async def main():
    ext_id = sys.argv[1]
    bws = _get(f"{CDP}/json/version")["webSocketDebuggerUrl"]

    sw_tgt = None
    for t in _get(f"{CDP}/json/list"):
        if t.get("type") == "service_worker" and ext_id in (t.get("url") or ""):
            sw_tgt = t
    if not sw_tgt:
        print("SW not found"); return
    print("SW:", sw_tgt["webSocketDebuggerUrl"][-20:])

    # 页面 target（驱动消息）
    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                  "params": {"url": f"chrome-extension://{ext_id}/executor.html"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 1:
                page_id = m["result"]["targetId"]; break
    await asyncio.sleep(2)
    page = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == page_id)

    # SW 连接：enable + 后台收消息任务
    sws = await websockets.connect(sw_tgt["webSocketDebuggerUrl"], max_size=10**7)
    await sws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    await asyncio.sleep(0.5)
    # 清空积压
    try:
        while True:
            await asyncio.wait_for(sws.recv(), 0.3)
    except Exception:
        pass

    async def drain(tag, seconds):
        end = asyncio.get_event_loop().time() + seconds
        while asyncio.get_event_loop().time() < end:
            try:
                m = json.loads(await asyncio.wait_for(sws.recv(), 1))
            except Exception:
                continue
            meth = m.get("method", "")
            if meth == "Runtime.consoleAPICalled":
                args = " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"].get("args", []))
                print(f"[{tag} console.{m['params']['type']}] {args[:250]}")
            elif meth == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                print(f"[{tag} EXC] {d.get('text')} :: {str(d.get('exception',{}).get('description',''))[:350]}")

    # 页面触发 start→stop（真实消息路径）
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def ev(i, expr, timeout=30):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), timeout))
                if m.get("id") == i:
                    return m.get("result", {}).get("result", {}).get("value")
        await ev(2, """(async()=>{
          await chrome.runtime.sendMessage({type:'START_RECORDING',note:'exc-trace'});
          await new Promise(r=>setTimeout(r,1500));
          return await chrome.runtime.sendMessage({type:'STOP_RECORDING'});
        })()""")
        print("[page] start+stop sent")

    await drain("sw", 45)

    await sws.close()
    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 99, "method": "Target.closeTarget",
                                  "params": {"targetId": page_id}}))
        await asyncio.wait_for(ws.recv(), 10)

asyncio.run(main())
