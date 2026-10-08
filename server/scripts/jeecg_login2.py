"""复用现有第一个 JeecG 登录 tab：填表→点登录→读 toast/URL。失败时截图。"""
import asyncio, base64, json, sys, urllib.request
import websockets

CDP = "http://127.0.0.1:9222"
USER, PW = "admin", "123456"

def _get(u): return json.loads(urllib.request.urlopen(u, timeout=10).read())

async def main():
    tgt = next(t for t in _get(f"{CDP}/json/list")
               if "127.0.0.1:8095" in (t.get("url") or ""))
    async with websockets.connect(tgt["webSocketDebuggerUrl"], max_size=10**7) as sw:
        i = 0
        async def ev(expr, aw=True):
            nonlocal i
            i += 1
            await sw.send(json.dumps({"id": i, "method": "Runtime.evaluate",
                "params": {"expression": expr, "awaitPromise": aw}}))
            while True:
                m = json.loads(await asyncio.wait_for(sw.recv(), 30))
                if m.get("id") == i:
                    r = m.get("result", {})
                    if r.get("exceptionDetails"):
                        return "EXC:" + str(r["exceptionDetails"])[:150]
                    return r.get("result", {}).get("value")
        r = await ev("""(async () => {
          const u = document.querySelector("input[placeholder*='账号']");
          const p = document.querySelector("input[placeholder*='密码']");
          if (!u || !p) return 'NO_INPUTS';
          const setVal = (el, v) => {
            Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')
              .set.call(el, v);
            el.dispatchEvent(new Event('input',{bubbles:true}));
          };
          setVal(u, "%s"); setVal(p, "%s");
          const btns=[...document.querySelectorAll('button')].map(b=>(b.textContent||'').trim());
          return 'FILLED btns=' + JSON.stringify(btns);
        })()""" % (USER, PW))
        print("[fill]", str(r)[:200])
        r2 = await ev("""(async () => {
          const b=[...document.querySelectorAll('button')].find(x=>/登\\s*录/.test(x.textContent||''));
          if(!b) return 'NO_BTN';
          b.click();
          await new Promise(r=>setTimeout(r,4000));
          return 'CLICKED url=' + location.href;
        })()""")
        print("[click]", str(r2)[:200])
        r3 = await ev("document.body.innerText.slice(0,400)")
        print("[body]", str(r3)[:400])
        # 截图存证
        await sw.send(json.dumps({"id": 999, "method": "Page.captureScreenshot",
                                  "params": {"format": "png"}}))
        while True:
            m = json.loads(await asyncio.wait_for(sw.recv(), 30))
            if m.get("id") == 999:
                open("D:/tmp/jeecg_login.png", "wb").write(
                    base64.b64decode(m["result"]["data"]))
                print("[shot] D:/tmp/jeecg_login.png")
                break

asyncio.run(main())
