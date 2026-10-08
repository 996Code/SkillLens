"""P0 深挖：badge 点击 + 页面 console 全捕获 + detectSystem 逐步。"""
import asyncio
import json
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"


def _get(u):
    return json.loads(urllib.request.urlopen(u, timeout=10).read())


async def main():
    ver = _get(f"{CDP}/json/version")
    bws = ver["webSocketDebuggerUrl"]
    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {
            "url": "http://127.0.0.1:8095/system/dict"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 1:
                jid = m["result"]["targetId"]
                break
        await ws.send(json.dumps({"id": 2, "method": "Target.activateTarget",
                                  "params": {"targetId": jid}}))
        await asyncio.wait_for(ws.recv(), 10)
    await asyncio.sleep(5)
    j = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == jid)
    async with websockets.connect(j["webSocketDebuggerUrl"], max_size=10**7) as sw:
        # enable console
        await sw.send(json.dumps({"id": 10, "method": "Runtime.enable"}))
        await asyncio.sleep(0.5)
        try:
            while True:
                await asyncio.wait_for(sw.recv(), 0.3)
        except Exception:
            pass

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

        # 逐步：badge 在吗
        b = await ev(1, "!!document.getElementById('skilllens-badge-host')")
        print("[badge]", b)
        # 点击
        await ev(2, """document.getElementById('skilllens-badge-host')
          ?.shadowRoot.querySelector('button')?.click(); 'clicked'""")
        await asyncio.sleep(3)
        # 面板宿主在吗
        h = await ev(3, "!!document.getElementById('skilllens-space-host')")
        print("[面板宿主]", h)
        # 逐项检查 shadow 内部
        detail = await ev(4, """(()=>{const h=document.getElementById('skilllens-space-host');
          if(!h) return 'NO_HOST';
          const sh=h.shadowRoot;
          return JSON.stringify({
            sys: sh.getElementById('sys')?.textContent,
            listChildren: sh.getElementById('list')?.children.length,
            listHtml: (sh.getElementById('list')?.innerHTML||'').slice(0,80),
          })})()""")
        print("[面板详情]", detail)
        # 收 console
        print("--- console ---")
        end = asyncio.get_event_loop().time() + 8
        while asyncio.get_event_loop().time() < end:
            try:
                m = json.loads(await asyncio.wait_for(sw.recv(), 1))
                meth = m.get("method", "")
                if meth == "Runtime.consoleAPICalled":
                    args = " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"].get("args", []))
                    print(f"[{m['params']['type']}] {args[:200]}")
                elif meth == "Runtime.exceptionThrown":
                    d = m["params"]["exceptionDetails"]
                    print(f"[EXC] {d.get('text')} {str(d.get('exception',{}).get('description',''))[:200]}")
            except Exception:
                continue

asyncio.run(main())
