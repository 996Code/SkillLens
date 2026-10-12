"""全量链回归轮：六系统业务链真实执行页路径复跑。

背景：2026-10-10/11 大量 executor 改动（select2 分支/name 匹配前置/
input[submit] 五通道/写证据即记/假 pass 收口）——单点全验过，本轮回
归确认无链级损伤。选链原则：每系统 1 条代表链+AN 两条（新机制）。

用法：cd server && uv run python ../scripts/chain_regression.py
"""
import json
import sys
import time
from pathlib import Path

import httpx
from websockets.sync.client import connect

CDP = "http://127.0.0.1:9222"
SERVER = "http://127.0.0.1:8710/api/v1"
EXT = "chrome-extension://iifhfcajmahbdbjljhmfknfnachpcpgl/executor.html"

CHAINS = [
    (2, "JeecG 建表+建字典(unique)"),
    (3, "JeecG AI2 跨步绑定"),
    (7, "禅道 Bug 流"),
    (10, "Odoo 报价链"),
    (11, "JeecG 字典流"),
    (14, "AN 行锚注入验收"),
    (16, "Snipe 生命周期（跨步绑定版）"),
    (17, "Dolibarr 订单全链"),
]


def get_token() -> str:
    with httpx.Client(timeout=15.0) as c:
        c.headers["X-SkillLens-Agent"] = "1"
        return c.post(f"{SERVER}/auth/plugin-session").json()["token"]


def run_chain(token: str, chain_id: int) -> dict:
    tabs = httpx.get(f"{CDP}/json", timeout=10).json()
    tab = next((t for t in tabs if "executor.html" in t.get("url", "")), None) \
        or next(t for t in tabs if t["type"] == "page")
    with connect(tab["webSocketDebuggerUrl"]) as w:
        w.send(json.dumps({"id": 1, "method": "Page.navigate",
                           "params": {"url": f"{EXT}?chain={chain_id}&auto=1"}}))
        w.recv(); time.sleep(4)
    with connect(tab["webSocketDebuggerUrl"]) as w:
        w.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": "(function(){ const b=[...document.querySelectorAll('button')]"
                          ".find(x=>/开始执行|开始/.test(x.textContent));"
                          "if(!b) return 'NO_BUTTON'; b.click(); return 'CLICKED'; })()",
            "returnByValue": True}}))
        clicked = json.loads(w.recv())["result"]["result"].get("value")
    if clicked != "CLICKED":
        return {"chain": chain_id, "verdict": "error", "note": clicked}
    # 轮询执行页结果卡（链结束显示「链执行结束」）
    t0 = time.time()
    with connect(tab["webSocketDebuggerUrl"]) as w:
        while time.time() - t0 < 480:
            time.sleep(8)
            w.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
                "expression": "(document.getElementById('log')||{}).textContent||''",
                "returnByValue": True}}))
            log = str(json.loads(w.recv())["result"]["result"].get("value"))
            if "链执行结束" in log:
                tail = log[log.rindex("链执行结束"):]
                return {"chain": chain_id, "verdict": "done",
                        "summary": tail[:80].replace("\n", " | ")}
        return {"chain": chain_id, "verdict": "timeout"}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    token = get_token()
    results = []
    for cid, name in CHAINS:
        print(f"[链 {cid}] {name} …", flush=True)
        r = run_chain(token, cid)
        r["name"] = name
        results.append(r)
        print(f"  → {r['verdict']}: {r.get('summary', r.get('note', ''))[:70]}", flush=True)
        time.sleep(4)
    out = Path("../demo/sprint44/chain-regression.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    npass = sum(1 for r in results if "步通过（pass）" in str(r.get("summary")))
    print(f"\n回归完成: {npass}/{len(results)} 链整体 pass → {out}")


if __name__ == "__main__":
    main()
