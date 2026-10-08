"""CDP 驱动 JeecG 登录（适配器清单 login steps 同语义）：
goto / → fill 账号/密码 → 点击登录 → 等待跳转。凭据读 server/adapters/jeecg.yaml。"""
import asyncio
import json
import sys
import urllib.request

CDP = "http://127.0.0.1:9222"
BASE = "http://127.0.0.1:8095"

import websockets


def _get(u):
    return json.loads(urllib.request.urlopen(u, timeout=10).read())


def creds():
    sys.path.insert(0, ".")
    from pathlib import Path
    from app.adapters.manifest import load_adapter_dir
    ms, _lints = load_adapter_dir(Path("adapters"))
    m = next(x for x in ms if getattr(x, "id", "") == "jeecg")
    return m.credentials.username, m.credentials.password_literal


async def main():
    user, pw = creds()
    print(f"[creds] user={user}")
    ver = _get(f"{CDP}/json/version")
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=10**7) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                  "params": {"url": f"{BASE}/"}}))
        while True:
            m = json.loads(await ws.recv())
            if m.get("id") == 1:
                tid = m["result"]["targetId"]; break
    await asyncio.sleep(4)
    tgt = next(t for t in _get(f"{CDP}/json/list") if t.get("id") == tid)
    async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=10**7) as sw:
        async def ev(expr, wait=1.5, i=[0]):
            i[0] += 1
            await sw.send(json.dumps({"id": i[0], "method": "Runtime.evaluate",
                                      "params": {"expression": expr, "awaitPromise": True}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), 30))
                if m.get("id") == i[0]:
                    return m.get("result", {}).get("result", {}).get("value")
        # 填账号/密码（JeecG 登录页 placeholder 定位——与 jeecg.yaml login steps 同语义）
        r1 = await ev(f"""
          (async () => {{
            const u = document.querySelector("input[placeholder*='账号']");
            const p = document.querySelector("input[placeholder*='密码']");
            if (!u || !p) return 'NO_INPUTS:' + document.title;
            // Vue 受控输入：走原生 value setter（绕过框架重写的原型 setter）
            // 再派发 input/change，框架状态才会接住新值（u.value= 会被覆盖）
            const setVal = (el, v) => {{
              const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
              setter.call(el, v);
              el.dispatchEvent(new Event('input', {{bubbles:true}}));
              el.dispatchEvent(new Event('change', {{bubbles:true}}));
            }};
            setVal(u, "{user}");
            setVal(p, "{pw}");
            return 'FILLED:' + u.value.length + ':' + p.value.length;
          }})()
        """)
        print("[fill]", r1)
        if r1 != "FILLED":
            return
        await ev("""
          [...document.querySelectorAll('button')].find(
            b => (b.textContent||'').replace(/\\s/g,'').includes('登'))?.click()
        """)
        await asyncio.sleep(4)
        url = await ev("location.href")
        print("[after login] url =", url)
        # 验证登录成功（不再是 /login）
        if "/login" in str(url):
            body = await ev("document.body.innerText.slice(0,300)")
            print("[login page body]", str(body)[:200])
        else:
            print("[LOGIN OK]")

asyncio.run(main())
