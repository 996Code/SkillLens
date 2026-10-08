"""AH4c 两入口制真机验收：popup=纯录制控制台 + 面板=测试工作台。"""
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
    bws = ver["webSocketDebuggerUrl"]

    # ① popup 瘦身验证：无技能列表/无学习卡/有录制控件+指引
    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                  "params": {"url": f"chrome-extension://{EXT}/popup.html"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 1:
                pid = m["result"]["targetId"]
                break
    await asyncio.sleep(2.5)
    p = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == pid)
    async with websockets.connect(p["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def pev(i, expr, t=20):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), t))
                if m.get("id") == i:
                    return m.get("result", {}).get("result", {}).get("value")
        r = await pev(2, """(()=>({
          start: !!document.getElementById('start'),
          stop: !!document.getElementById('stop'),
          execList: !!document.getElementById('exec-list'),
          learnCard: !!document.getElementById('learn-card'),
          spaceBtn: !!document.getElementById('open-space'),
          guide: document.body.innerText.includes('SL 空间面板'),
        }))()""")
        print("[popup]", r)
        # 录制路径仍通：start→计数→stop
        s1 = await pev(3, """(async()=>{
          document.getElementById('note').value='合并验收';
          document.getElementById('start').click();
          await new Promise(r=>setTimeout(r,2500));
          return document.getElementById('status').textContent;
        })()""")
        print("[录制]", s1)

    # ② JeecG 页操作（录点事件）+ 面板验证
    async with websockets.connect(bws, max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 4, "method": "Target.createTarget",
                                  "params": {"url": "http://127.0.0.1:8095/system/dict"}}))
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if m.get("id") == 4:
                jid = m["result"]["targetId"]
                break
    await asyncio.sleep(5)
    j = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == jid)
    async with websockets.connect(j["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def jev(i, expr, t=25):
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), t))
                if m.get("id") == i:
                    d = m.get("result", {})
                    if d.get("exceptionDetails"):
                        return "EXC:" + str(d["exceptionDetails"])[:150]
                    return d.get("result", {}).get("value")
        # 页面上点一行（生成录制事件）
        await jev(5, "[...document.querySelectorAll('tr')].slice(1,2).forEach(r=>r.click()); 'ok'")
        await asyncio.sleep(2)
        # 停录（经 popup——真实路径）
        async with websockets.connect(p["webSocketDebuggerUrl"], max_size=10**7) as pw:
            await pw.send(json.dumps({"id": 6, "method": "Runtime.evaluate", "params": {
                "expression": "(async()=>{document.getElementById('stop').click();"
                              "await new Promise(r=>setTimeout(r,2000));return 'stopped'})()",
                "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(pw.recv(), 20))
                if m.get("id") == 6:
                    print("[停录]", m.get("result", {}).get("result", {}).get("value"))
                    break
        # 面板：徽标→展开→验证（录制徽标应亮过/系统/技能/单执行钮/待学提示）
        b = await jev(7, """(()=>{const h=document.getElementById('skilllens-badge-host');
          return h?'BADGE_OK':'BADGE_MISSING'})()""")
        print("[徽标]", b)
        await jev(8, """(()=>{document.getElementById('skilllens-badge-host')
          .shadowRoot.querySelector('button').click();'opened'})()""")
        await asyncio.sleep(4)
        r2 = await jev(9, """(()=>{const h=document.getElementById('skilllens-space-host'); if(!h) return 'MISSING';
          const sh=h.shadowRoot;
          return JSON.stringify({
            sys:sh.getElementById('sys')?.textContent,
            rows:sh.querySelectorAll('.sk').length,
            oneBtn: !!sh.querySelector('.sk .one'),
            recdot: sh.getElementById('recdot')?.className || '',
            note: sh.getElementById('nt')?.textContent || '',
          })})()""")
        print("[面板]", r2)

    # 清理
    async with websockets.connect(bws, max_size=10**7) as ws:
        for tid in (pid,):
            await ws.send(json.dumps({"id": 90, "method": "Target.closeTarget",
                                      "params": {"targetId": tid}}))
        await asyncio.wait_for(ws.recv(), 10)

asyncio.run(main())
