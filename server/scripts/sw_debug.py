"""抓扩展 SW 的 console/异常：重跑录制-停录流程时监听 service_worker target。"""
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
    ext_id = None
    for t in _get(f"{CDP}/json"):
        u = t.get("url", "")
        if u.startswith("chrome-extension://") and "service-worker" in (t.get("type") or ""):
            ext_id = u.split("/")[2]
            break
    if not ext_id:
        for t in _get(f"{CDP}/json"):
            u = t.get("url", "")
            if u.startswith("chrome-extension://"):
                ext_id = u.split("/")[2]
                break
    print("ext:", ext_id[:14] if ext_id else None)

    # SW ws target（/json/type?service_worker——经 /json/list 找）
    sw_tgt = None
    for t in _get(f"{CDP}/json/list"):
        if t.get("type") == "service_worker" and ext_id in (t.get("url") or ""):
            sw_tgt = t
            break
    if not sw_tgt:
        print("SW target not found; all targets:")
        for t in _get(f"{CDP}/json/list"):
            print(" ", t.get("type"), (t.get("url") or "")[:60])
        return
    print("SW ws:", (sw_tgt.get("webSocketDebuggerUrl") or "")[:60])

    async with websockets.connect(sw_tgt["webSocketDebuggerUrl"], max_size=10**7) as sw:
        await sw.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        await sw.send(json.dumps({"id": 2, "method": "Log.enable"}))

        async def pump(tag):
            try:
                while True:
                    m = json.loads(await asyncio.wait_for(sw.recv(), 60))
                    meth = m.get("method", "")
                    if meth == "Runtime.consoleAPICalled":
                        args = " ".join(str(a.get("value", a.get("description", ""))) for a in m["params"].get("args", []))
                        print(f"[{tag} console.{m['params']['type']}] {args[:220]}")
                    elif meth == "Runtime.exceptionThrown":
                        d = m["params"]["exceptionDetails"]
                        print(f"[{tag} EXC] {d.get('text')} {str(d.get('exception',{}).get('description',''))[:300]}")
            except Exception as e:
                print(f"[{tag} pump end] {e}")

        pump_t = asyncio.create_task(pump("sw"))

        # 驱动一次完整 stop（先拿当前 recording state；若未录制则 start→stop）
        await sw.send(json.dumps({"id": 10, "method": "Runtime.evaluate", "params": {
            "expression": "(async()=>{const s=await chrome.runtime.sendMessage({type:'GET_STATE'});return JSON.stringify(s)})()",
            "awaitPromise": True}}))
        while True:
            m = json.loads(await asyncio.wait_for(sw.recv(), 15))
            if m.get("id") == 10:
                state = m.get("result", {}).get("result", {}).get("value")
                print("[state]", state)
                break
        # 直接 start→等2s→stop，全在真实消息路径
        await sw.send(json.dumps({"id": 11, "method": "Runtime.evaluate", "params": {
            "expression": "(async()=>{await chrome.runtime.sendMessage({type:'START_RECORDING',note:'sw-debug'});return 'started'})()",
            "awaitPromise": True}}))
        while True:
            m = json.loads(await asyncio.wait_for(sw.recv(), 15))
            if m.get("id") == 11:
                print("[started]", m.get("result", {}).get("result", {}).get("value"))
                break
        await asyncio.sleep(2)
        await sw.send(json.dumps({"id": 12, "method": "Runtime.evaluate", "params": {
            "expression": "(async()=>{await chrome.runtime.sendMessage({type:'STOP_RECORDING'});return 'stopped'})()",
            "awaitPromise": True}}))
        while True:
            m = json.loads(await asyncio.wait_for(sw.recv(), 15))
            if m.get("id") == 12:
                print("[stopped]", m.get("result", {}).get("result", {}).get("value"))
                break
        # 等 autoLearn 痕迹
        await asyncio.sleep(30)
        await sw.send(json.dumps({"id": 13, "method": "Runtime.evaluate", "params": {
            "expression": "(async()=>{const {sl_last_learn:r}=await chrome.storage.local.get('sl_last_learn');return JSON.stringify(r??null)})()",
            "awaitPromise": True}}))
        while True:
            m = json.loads(await asyncio.wait_for(sw.recv(), 15))
            if m.get("id") == 13:
                print("[last_learn]", m.get("result", {}).get("result", {}).get("value"))
                break
        pump_t.cancel()

asyncio.run(main())
