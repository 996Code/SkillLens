"""AI2 收尾定位：执行页运行时单点检查——链数据→resolve→plan body 全链路。"""
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
    ver = _get(f"{CDP}/json/version")
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget", "params": {
            "url": f"chrome-extension://{ext}/executor.html?chain=3&auto=1"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 1:
                tid = m["result"]["targetId"]
                break
    await asyncio.sleep(3)
    t = next(x for x in _get(f"{CDP}/json/list") if x.get("id") == tid)
    async with websockets.connect(t["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def ev(i, expr, t2=30):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate", "params": {
                "expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), t2))
                if m.get("id") == i:
                    d = m.get("result", {})
                    if d.get("exceptionDetails"):
                        return "EXC:" + str(d["exceptionDetails"])[:250]
                    return d.get("result", {}).get("value")
        # ① 链数据拉取正确性（页面视角）
        r1 = await ev(2, """(async()=>{
          const t = await (await fetch('http://127.0.0.1:8710/api/v1/chains/3', {
            headers: {Authorization: 'Bearer ' + (await chrome.storage.local.get('sl_executor_token')).sl_executor_token}
          })).json();
          return JSON.stringify(t.steps.map(s=>({id:s.skill_id, ov:s.overrides})));
        })()""")
        print("[链数据]", r1)
        # ② 拦截 plan body（等页面加载完再 patch + click）
        r2 = await ev(3, """(async()=>{
          window.__bodies = [];
          const of = window.fetch;
          window.fetch = (u, o) => {
            if (String(u).includes('/plan') && o?.body) window.__bodies.push(String(o.body));
            return of(u, o);
          };
          const go = document.getElementById('go');
          if (!go) return 'NO_GO_BTN';
          go.click();
          for (let i = 0; i < 10 && window.__bodies.length === 0; i++) {
            await new Promise(r => setTimeout(r, 800));
          }
          return window.__bodies.length ? window.__bodies[0] : 'NO_PLAN_BODY';
        })()""")
        print("[plan body]", str(r2)[:400])
        # ③ 立即停（不真跑）
        await ev(4, "document.getElementById('stop')?.click(); 'stop-req'")
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 9, "method": "Target.closeTarget", "params": {"targetId": tid}}))
        await asyncio.wait_for(ws.recv(), 10)

asyncio.run(main())
