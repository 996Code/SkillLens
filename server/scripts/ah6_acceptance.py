"""AH6 页内执行真机验收：面板点执行→SW attach 本页驱动→进度回流面板。

验证：① 面板发起（EXECUTOR_RUN_ON_TAB）② 本页 URL 被导航（goto 生效）
③ 面板进度区收到 SL_PROGRESS ④ run 落库 pass。
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
        # 开面板（徽标点击）
        await ev(1, """(()=>{const b=document.getElementById('skilllens-badge-host');
          if(!b) return 'NO_BADGE'; b.shadowRoot.querySelector('button').click(); return 'opened'})()""")
        await asyncio.sleep(4)
        # 面板就绪 + 发起页内执行（单技能 118——只读链最稳）
        r = await ev(2, """(()=>{const h=document.getElementById('skilllens-space-host');
          if(!h) return 'NO_PANEL';
          const sh=h.shadowRoot;
          const rows=[...sh.querySelectorAll('.sk')];
          const row=rows.find(x=>x.querySelector('.nm')?.textContent==='字典查询');
          if(!row) return 'NO_SKILL';
          const btn=row.querySelector('.one');
          if(!btn) return 'NO_BTN';
          btn.click();
          return 'LAUNCHED'})()""")
        print("[发起]", r)
    # 等执行（本页被驱动+进度回流）
    await asyncio.sleep(45)
    j2 = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == jid)
    async with websockets.connect(j2["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def ev2(i, expr, t=30):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
                "expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), t))
                if m.get("id") == i:
                    return m.get("result", {}).get("result", {}).get("value")
        r2 = await ev2(3, """(()=>{const h=document.getElementById('skilllens-space-host');
          if(!h) return 'NO_PANEL';
          const sh=h.shadowRoot;
          return JSON.stringify({
            url: location.href.slice(0, 60),
            progVisible: sh.getElementById('pg')?.style.display,
            progTitle: sh.getElementById('pgt')?.textContent,
            progLog: (sh.getElementById('pgl')?.textContent || '').slice(-300),
          })})()""")
        print("[面板+进度]", r2)

asyncio.run(main())
