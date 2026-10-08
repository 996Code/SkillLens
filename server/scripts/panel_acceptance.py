"""AH4b 悬浮面板真机验收：popup 点空间 → JeecG 页出现面板 → 组链。"""
import asyncio
import json
import sys
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"
EXT = sys.argv[1] if len(sys.argv) > 1 else ""


def _get(u):
    return json.loads(urllib.request.urlopen(u, timeout=10).read())


async def main():
    ver = _get(f"{CDP}/json/version")
    bws = ver["webSocketDebuggerUrl"]
    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                  "params": {"url": "http://127.0.0.1:8095/system/dict"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 1:
                jid = m["result"]["targetId"]
                break
        await ws.send(json.dumps({"id": 2, "method": "Target.activateTarget",
                                  "params": {"targetId": jid}}))
        await asyncio.wait_for(ws.recv(), 10)
    await asyncio.sleep(5)  # document_idle 注入 CS

    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 3, "method": "Target.createTarget",
                                  "params": {"url": f"chrome-extension://{EXT}/popup.html"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 3:
                pid = m["result"]["targetId"]
                break
    await asyncio.sleep(2)
    p = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == pid)
    async with websockets.connect(p["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def pev(i, expr, t=30):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), t))
                if m.get("id") == i:
                    return m.get("result", {}).get("result", {}).get("value")
        # fire-and-forget：click 内含 window.close()，await 响应必断连
        await sw.send(json.dumps({"id": 4, "method": "Runtime.evaluate", "params": {
            "expression": "document.getElementById('open-space').click()"}}))
        await asyncio.sleep(2.5)
        print("[点击空间] sent")
    # popup 点击后会 window.close——p 的 ws 随之断开属预期，不再使用

    await asyncio.sleep(4)
    j = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == jid)
    async with websockets.connect(j["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def jev(i, expr, t=30):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), t))
                if m.get("id") == i:
                    return m.get("result", {}).get("result", {}).get("value")
        r = await jev(5, """(()=>{const h=document.getElementById('skilllens-space-host');
          if(!h) return 'MISSING';
          const sh=h.shadowRoot;
          return JSON.stringify({sys:sh.getElementById('sys')?.textContent,
                                 rows:sh.querySelectorAll('.sk').length})})()""")
        print("[面板]", r)
        if r != "MISSING":
            c = await jev(6, """(()=>{const sh=document.getElementById('skilllens-space-host').shadowRoot;
              const rows=[...sh.querySelectorAll('.sk')];
              const pick=(n)=>{const r=rows.find(x=>x.querySelector('.nm')?.textContent===n);
                               if(r){r.click();return true} return false};
              const a=pick('字典条目创建'); const b=pick('字典查询');
              return JSON.stringify({a,b,pk:sh.getElementById('pks')?.textContent})})()""")
            print("[组链]", c)

    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 9, "method": "Target.closeTarget",
                                  "params": {"targetId": pid}}))
        await asyncio.wait_for(ws.recv(), 10)

asyncio.run(main())
