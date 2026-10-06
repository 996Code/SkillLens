"""P3 录制（全 raw CDP——零 Playwright）：popup 页/走查/学习全链。

背景：Playwright Node driver 在连接外部浏览器时的 dialog manager 竞态
（'No dialog is showing' uncaught）杀 driver 进程——后续 goto 全断连。
六轮实证（popup 常驻/单 driver/独立连接均不治本——dialog 来自目标页面）。
raw CDP 无页面生命周期管理，彻底避开。
"""
import asyncio
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import websockets

from app.adapters.manifest import load_adapter_dir

SERVER = "http://127.0.0.1:8710/api/v1"
CDP = "http://127.0.0.1:9222"


def mint_token() -> str:
    from app.auth import issue_token
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "admin").first()
        return issue_token(db, u.id)
    finally:
        db.close()


class CDPage:
    """单页 raw CDP 控制器（goto/fill/click 三原语——走查所需）。"""

    def __init__(self, ws):
        self.ws = ws
        self._id = 0

    async def cmd(self, method, params=None):
        self._id += 1
        await self.ws.send(json.dumps(
            {"id": self._id, "method": method, "params": params or {}}))
        while True:
            r = json.loads(await self.ws.recv())
            if r.get("id") == self._id:
                return r

    async def eval_js(self, expr, await_promise=False):
        r = await self.cmd("Runtime.evaluate", {
            "expression": expr, "returnByValue": True,
            "awaitPromise": await_promise})
        res = r.get("result", {})
        if res.get("exceptionDetails"):
            raise RuntimeError(str(res["exceptionDetails"])[:150])
        return res.get("result", {}).get("value")

    async def goto(self, url):
        await self.cmd("Page.navigate", {"url": url})
        await asyncio.sleep(3)

    async def fill(self, selector, value):
        await self.eval_js(f"""(() => {{
          const el = document.querySelector({json.dumps(selector)});
          if (!el) throw new Error('fill miss: {selector}');
          el.focus();
          el.value = {json.dumps(value)};
          el.dispatchEvent(new Event('input', {{bubbles: true}}));
          el.dispatchEvent(new Event('change', {{bubbles: true}}));
        }})()""")

    async def click(self, selector):
        await self.eval_js(f"""(() => {{
          const el = document.querySelector({json.dumps(selector)});
          if (!el) throw new Error('click miss: {selector}');
          el.click();
        }})()""")

    async def click_text(self, text):
        await self.eval_js(f"""(() => {{
          const els = [...document.querySelectorAll('button, a')]
            .filter(e => (e.textContent||'').includes({json.dumps(text)})
              && e.getBoundingClientRect().width > 0);
          if (els.length) els[els.length-1].click();
        }})()""")


async def open_page():
    """新开一个 about:blank 页并返回控制器。"""
    req = urllib.request.Request(
        f"{CDP}/json/new?about:blank", method="PUT")
    target = json.loads(urllib.request.urlopen(req).read())
    ws = await websockets.connect(
        target["webSocketDebuggerUrl"], max_size=10**7)
    page = CDPage(ws)
    await page.cmd("Page.enable")
    await page.cmd("Runtime.enable")
    return page, target["id"]


async def close_page(target_id):
    try:
        urllib.request.urlopen(
            f"{CDP}/json/close/{target_id}").read()
    except Exception:
        pass


async def sw_evaluate(expr: str):
    targets = json.loads(urllib.request.urlopen(f"{CDP}/json").read())
    sw = [t for t in targets if t.get("type") == "service_worker"
          and "chrome-extension" in t.get("url", "")]
    if not sw:
        return None
    async with websockets.connect(sw[0]["webSocketDebuggerUrl"],
                                  max_size=10**7) as ws:
        await ws.send(json.dumps({
            "id": 1, "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True,
                       "awaitPromise": True}}))
        while True:
            r = json.loads(await ws.recv())
            if r.get("id") == 1:
                return r.get("result", {}).get("result", {}).get("value")


async def start_recording(note: str) -> str:
    r = await sw_evaluate(
        "(async () => {"
        " const res = await fetch('http://127.0.0.1:8710/api/v1/sessions', {"
        "   method: 'POST', headers: {'Content-Type': 'application/json'},"
        f"   body: JSON.stringify({{target_system: 'njmind', note: {json.dumps(note)}, source: 'demo'}})}});"
        " if (!res.ok) return JSON.stringify({error: res.status});"
        " const s = await res.json();"
        " await chrome.storage.local.set({sl_recording: true,"
        "   sl_session: s.session_id, sl_note: 'p3'});"
        " return JSON.stringify({id: s.session_id});"
        "})()")
    return (json.loads(r) if r else {}).get("id", "")


async def stop_recording():
    await sw_evaluate(
        "(async () => {"
        " await chrome.storage.local.set({sl_recording: false});"
        " return 'ok';})()")


async def run_flow_steps(page, flow, data, manifest):
    """清单 Step 走查（goto/fill/click/select/wait 五原语 raw 版）。"""
    for step in flow.steps:
        arg = step.arg.replace("${data}", data)
        arg2 = (step.arg2 or "").replace("${data}", data)
        if step.op == "goto":
            url = arg if arg.startswith("http") else manifest.target.base_url + arg
            await page.goto(url)
        elif step.op == "fill":
            await page.fill(arg, arg2)
        elif step.op == "click":
            # playwright 式选择器：text=…/button:has-text()→ 文本点击；
            # CSS → querySelector
            if "has-text" in arg or arg.startswith("text="):
                text = arg.split("(")[-1].rstrip(")").strip("'\"")
                await page.click_text(text)
            else:
                await page.click(arg)
        elif step.op == "select":
            await page.eval_js(
                f"(() => {{ const s = document.querySelector({json.dumps(arg)});"
                f" s.value = {json.dumps(arg2)};"
                " s.dispatchEvent(new Event('change', {bubbles: true})); })()")
        elif step.op == "wait":
            await asyncio.sleep(float(arg))
        await asyncio.sleep(0.6)


async def learn(token, sids):
    async with httpx.AsyncClient(timeout=180) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        for sid in sids:
            resp = await c.post(f"{SERVER}/sessions/{sid}/process")
            if resp.status_code != 200:
                print(f"  process: {resp.status_code}")
                return None
        resp = await c.post(f"{SERVER}/align", json={"session_ids": sids})
        if resp.status_code != 200:
            print(f"  align: {resp.status_code} {resp.text[:80]}")
            return None
        aid = resp.json()["alignment_id"]
        for _ in range(3):
            try:
                resp = await c.post(f"{SERVER}/alignments/{aid}/induce")
                if resp.status_code == 200:
                    skill = resp.json()
                    await c.post(f"{SERVER}/skills/{skill['id']}/assertions")
                    return skill
            except Exception:
                await asyncio.sleep(5)
        return None


async def login_raw(page, manifest):
    """清单登录（raw 版——成功判定 url_not_contains）。"""
    if manifest.login is None:
        return True
    base = manifest.target.base_url
    await page.goto(base)
    cur = await page.eval_js("location.href")
    probe = manifest.login.success.url_not_contains
    if probe and probe not in cur:
        return True
    for step in manifest.login.steps:
        arg = step.arg.replace("${username}", manifest.credentials.username)
        arg2 = (step.arg2 or "").replace(
            "${password}", manifest.credentials.password_literal or "")
        if step.op == "goto":
            url = arg if arg.startswith("http") else base + arg
            await page.goto(url)
        elif step.op == "fill":
            await page.fill(arg, arg2)
        elif step.op == "click":
            if "has-text" in arg:
                text = arg.split("(")[-1].rstrip(")").strip("'\"")
                await page.click_text(text)
            else:
                await page.click(arg)
        await asyncio.sleep(0.6)
    await asyncio.sleep(2)
    cur = await page.eval_js("location.href")
    return probe not in cur if probe else True


async def main():
    adapter_id = sys.argv[1] if len(sys.argv) > 1 else "erpnext"
    flow_name = sys.argv[2] if len(sys.argv) > 2 else "supplier-chain"
    manifests, _ = load_adapter_dir(
        Path(__file__).resolve().parent.parent / "adapters")
    m = {x.id: x for x in manifests}[adapter_id]
    flow = next(f for f in m.flows if f.name == flow_name)
    token = mint_token()
    ts = int(time.time()) % 100000
    sids = []
    for mark in ["甲", "乙"]:
        data = f"{mark}{ts}"
        print(f"  录制 {flow.name}（{data}）", flush=True)
        sid = await start_recording(f"p3-{flow.name}")
        if not sid:
            print("  ! 无法开始录制")
            return
        page, tid = await open_page()
        try:
            ok = await login_raw(page, m)
            if not ok:
                print("  ! 登录失败")
            else:
                try:
                    await run_flow_steps(page, flow, data, m)
                except Exception as e:
                    print(f"  ! 走查异常: {type(e).__name__}: {str(e)[:100]}")
        finally:
            await asyncio.sleep(1.5)
            await stop_recording()
            await page.ws.close()
            await close_page(tid)
        await asyncio.sleep(2.5)
        sids.append(sid)
    skill = await learn(token, sids)
    if skill:
        print(f"  → skill #{skill['id']} {skill['name']} ({skill['status']})")


if __name__ == "__main__":
    asyncio.run(main())
