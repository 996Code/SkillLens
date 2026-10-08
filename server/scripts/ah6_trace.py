"""AH6 定位：面板页发 EXECUTOR_RUN_ON_TAB，SW console 抓 [AH6] 入口日志。"""
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
    print("ext:", (ext or "NONE")[:12])
    sw_tgt = next((t for t in _get(f"{CDP}/json/list")
                   if t.get("type") == "service_worker" and ext in (t.get("url") or "")), None)
    ver = _get(f"{CDP}/json/version")
    bws = ver["webSocketDebuggerUrl"]

    # SW console 抓取
    sws = await websockets.connect(sw_tgt["webSocketDebuggerUrl"], max_size=10**7)
    await sws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
    await asyncio.sleep(0.5)
    try:
        while True:
            await asyncio.wait_for(sws.recv(), 0.3)
    except Exception:
        pass

    async def drain(seconds):
        end = asyncio.get_event_loop().time() + seconds
        while asyncio.get_event_loop().time() < end:
            try:
                m = json.loads(await asyncio.wait_for(sws.recv(), 1))
            except Exception:
                continue
            meth = m.get("method", "")
            if meth == "Runtime.consoleAPICalled":
                args = " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"].get("args", []))
                print(f"[console.{m['params']['type']}] {args[:250]}")
            elif meth == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                print(f"[EXC] {d.get('text')} :: {str(d.get('exception',{}).get('description',''))[:300]}")

    # JeecG 页开面板并发消息（真实路径：面板按钮的 sendMessage）
    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 2, "method": "Target.createTarget", "params": {
            "url": "http://127.0.0.1:8095/system/dict"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 2:
                jid = m["result"]["targetId"]
                break
    await asyncio.sleep(5)
    j = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == jid)
    async with websockets.connect(j["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def ev(i, expr, t=30):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
                "expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), t))
                if m.get("id") == i:
                    d = m.get("result", {})
                    if d.get("exceptionDetails"):
                        return "EXC:" + str(d["exceptionDetails"])[:200]
                    return d.get("result", {}).get("value")
        # 面板挂载（徽标点击）
        r = await ev(3, """(()=>{const b=document.getElementById('skilllens-badge-host');
          if(!b) return 'NO_BADGE'; b.shadowRoot.querySelector('button').click(); return 'opened'})()""")
        print("[面板]", r)
        await asyncio.sleep(3)
        # 直接从页面上下文发消息（content script 的 runtime.sendMessage 等价）
        r2 = await ev(4, """(async()=>{
          const resp = await new Promise(res=>{
            chrome.runtime.sendMessage({type:'EXECUTOR_RUN_ON_TAB', skillId:118}, res);
            setTimeout(()=>res('RESP_TIMEOUT'), 5000);
          });
          return JSON.stringify(resp);
        })()""")
        print("[消息响应]", r2)

    await drain(30)
    await sws.close()

asyncio.run(main())
