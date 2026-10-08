"""调试：CDP 开 executor.html 并实时采集 console/页面日志/DOM。"""
import asyncio
import json
import os
import sys
import urllib.request
from urllib.parse import quote

CDP = "http://127.0.0.1:9222"
URL = sys.argv[1] if len(sys.argv) > 1 else "about:blank"
WATCH_S = int(sys.argv[2]) if len(sys.argv) > 2 else 30

import websockets


def _get(u):
    return json.loads(urllib.request.urlopen(u, timeout=10).read())


async def main():
    ver = _get(f"{CDP}/json/version")
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=10**7) as ws:

        async def cmd(i, method, params=None):
            await ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))

        events = []

        async def pump():
            while True:
                msg = json.loads(await ws.recv())
                if "method" in msg:
                    events.append(msg)

        pump_t = asyncio.create_task(pump())
        await cmd(1, "Target.createTarget", {"url": URL})
        await asyncio.sleep(3)
        # 找新 target
        targets = _get(f"{CDP}/json/list")
        tgt = next((t for t in targets if "executor.html" in (t.get("url") or "")), None)
        if not tgt:
            print("!! executor tab not found; targets:")
            for t in targets:
                print("  ", t.get("type"), (t.get("url") or "")[:80])
            pump_t.cancel()
            return
        tid = tgt["id"]
        print(f"[tab] {tgt['url'][:110]}")
        # attach 到该 target 抓 console + 网络 + DOM
        sid_holder = {}

        async def session_pump():
            async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=10**7) as sw:
                sid_holder["ws"] = sw
                await sw.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
                await sw.send(json.dumps({"id": 2, "method": "Log.enable"}))
                await sw.send(json.dumps({"id": 3, "method": "Network.enable"}))
                while True:
                    m = json.loads(await sw.recv())
                    meth = m.get("method", "")
                    if meth == "Runtime.consoleAPICalled":
                        args = " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"].get("args", []))
                        print(f"[console.{m['params']['type']}] {args[:200]}")
                    elif meth == "Runtime.exceptionThrown":
                        d = m["params"]["exceptionDetails"]
                        print(f"[EXC] {d.get('text')} {str(d.get('exception',{}).get('description',''))[:300]}")
                    elif meth == "Network.responseReceived":
                        u = m["params"]["response"]["url"]
                        if "/api/" in u:
                            print(f"[net] {m['params']['response']['status']} {u[:110]}")
                    elif meth == "Network.loadingFailed":
                        print(f"[netFAIL] {m['params'].get('errorText')} {m['params'].get('blockedReason','') or ''}")

        sp = asyncio.create_task(session_pump())
        await asyncio.sleep(WATCH_S)
        # 读页面日志区 DOM
        try:
            async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=10**7) as sw:
                await sw.send(json.dumps({"id": 9, "method": "Runtime.evaluate", "params": {
                    "expression": "document.getElementById('log')?.textContent || document.body.innerText.slice(0,1500)"}}))
                while True:
                    m = json.loads(await sw.recv())
                    if m.get("id") == 9:
                        print("\n===== 页面日志 DOM =====")
                        print(str(m["result"]["result"].get("value", ""))[:2000])
                        break
        except Exception as e:
            print("dom read fail:", e)
        pump_t.cancel()
        sp.cancel()

asyncio.run(main())
