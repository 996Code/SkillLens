"""P0 验证：模拟新用户（无 token）→ 面板登录 → 系统识别+列表加载。"""
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
        async def ev(i, expr, t=30):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
                "expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), t))
                if m.get("id") == i:
                    d = m.get("result", {})
                    if d.get("exceptionDetails"):
                        return "EXC:" + str(d["exceptionDetails"])[:150]
                    return d.get("result", {}).get("value")

        # ① 清 token（模拟新用户）
        await ev(1, """(async()=>{
          await chrome.storage.local.remove('sl_executor_token');
          return 'token cleared'})()""")
        print("[1] token 已清（模拟新用户）")
        # ② 面板挂载
        await ev(2, """(()=>{const b=document.getElementById('skilllens-badge-host');
          if(!b) return 'NO_BADGE'; b.shadowRoot.querySelector('button').click(); return 'opened'})()""")
        await asyncio.sleep(4)
        r = await ev(3, """(()=>{const h=document.getElementById('skilllens-space-host');
          if(!h) return 'NO_PANEL'; const sh=h.shadowRoot;
          return JSON.stringify({sys:sh.getElementById('sys')?.textContent,
                                 hasLogin:!!sh.querySelector('input[type=password]')})})()""")
        print("[2] 未登录态]", r)
        # ③ 面板内登录
        r2 = await ev(4, """(async()=>{
          const sh=document.getElementById('skilllens-space-host').shadowRoot;
          const [u,p]=sh.querySelectorAll('.body input');
          u.value='admin'; p.value='admin-local-2026';
          sh.querySelector('.body button').click();
          await new Promise(r=>setTimeout(r,3000));
          return sh.querySelector('.body div:last-child')?.textContent || '?';
        })()""")
        print("[3] 登录结果]", r2)
    await asyncio.sleep(3)  # reload 后
    j2 = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == jid)
    async with websockets.connect(j2["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def ev5(i, expr, t=30):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
                "expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), t))
                if m.get("id") == i:
                    return m.get("result", {}).get("result", {}).get("value")
        # ④ reload 后重新开面板验证
        await ev5(5, """(()=>{const b=document.getElementById('skilllens-badge-host');
          if(b) b.shadowRoot.querySelector('button').click(); return 'reopened'})()""")
        await asyncio.sleep(4)
        r3 = await ev5(6, """(()=>{const h=document.getElementById('skilllens-space-host');
          if(!h) return 'NO_PANEL'; const sh=h.shadowRoot;
          return JSON.stringify({sys:sh.getElementById('sys')?.textContent,
                                 rows:sh.querySelectorAll('.sk').length})})()""")
        print("[4] 登录后面板]", r3)

asyncio.run(main())
