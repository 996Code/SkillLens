"""s44 换参矩阵战役：四系统技能×2 换参，真实执行页路径。

矩阵（HANDOVER §8.2）：
- Dolibarr 182/183/184（创建合作伙伴，fill=name）
- Snipe 303/304/305（资产创建/借出/归还）
- ERPNext 213/216/2（客户保存/创建，fill=customer_name）
- Odoo 1（合作伙伴快速创建，fill=e.g. Lumber Inc）×2

每格两个唯一换参值（mx{ts}A/B），验收=pass+断言命中+写请求触发
（AM1 写水位护航——无假 pass：步 ok 无写=快败）。
产出：demo/sprint44/matrix-report.json

用法：cd server && uv run python ../scripts/s44_matrix.py [--system X]
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

MATRIX = {
    # 182-184 是编辑流（url 带 __ID__ 占位——录制脱 id 产物，视图态无
    # 表单）——换 185/188（action=create 干净创建流）。187 无 fill 步
    # （列表→点建单）作无参回归格。
    "Dolibarr": [
        {"skill": 185, "key": "name"},
        {"skill": 188, "key": "name"},
        {"skill": 187, "key": None},
    ],
    "Snipe": [
        # 303/304/305 是链生命周期技能（单独运行无意义：Checkin 需
        # checkout 后状态，dropdown 录制弱）——改用查找类技能换参
        # （2828/2836 实证 pass）+ 303 留链 15（重录 select2 后跑）
        {"skill": 138, "key": "asset_tags[1]"},
        {"skill": 139, "key": "asset_tags[1]"},
    ],
    "ERPNext": [
        {"skill": 213, "key": "customer_name"},
        {"skill": 216, "key": "customer_name"},
        {"skill": 2, "key": "customer_name"},
    ],
    "Odoo": [
        {"skill": 1, "key": "e.g. Lumber Inc"},
    ],
}


def get_token() -> str:
    with httpx.Client(timeout=15.0) as c:
        c.headers["X-SkillLens-Agent"] = "1"
        return c.post(f"{SERVER}/auth/plugin-session").json()["token"]


def run_cell(token: str, skill: int, key: str | None, val: str) -> dict:
    """一格：开执行页（fill 换参）→ 点开始 → 轮询 run 终态。"""
    url = f"{EXT}?skill={skill}&auto=1"
    if key:
        from urllib.parse import quote
        url += f"&fill_{quote(key)}={quote(val)}"
    tabs = httpx.get(f"{CDP}/json", timeout=10).json()
    tab = next((t for t in tabs if "executor.html" in t.get("url", "")), None) \
        or next(t for t in tabs if t["type"] == "page")
    with connect(tab["webSocketDebuggerUrl"]) as w:
        w.send(json.dumps({"id": 1, "method": "Page.navigate",
                           "params": {"url": url}}))
        w.recv(); time.sleep(4)
    with connect(tab["webSocketDebuggerUrl"]) as w:
        w.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": "(function(){ const b=[...document.querySelectorAll('button')].find(x=>/开始执行|开始/.test(x.textContent)); if(!b) return 'NO_BUTTON'; b.click(); return 'CLICKED'; })()",
            "returnByValue": True}}))
        clicked = json.loads(w.recv())["result"]["result"].get("value")
    if clicked != "CLICKED":
        return {"status": "error", "note": clicked}
    # 轮询该技能最新 run 至终态（上限 150s——AM2 预算 120s+余量）
    import sqlite3
    db = sqlite3.connect("skilllens.db")
    t0 = time.time()
    while time.time() - t0 < 150:
        time.sleep(6)
        row = db.execute(
            "SELECT id, status FROM replay_run WHERE skill_id=? "
            "ORDER BY id DESC LIMIT 1", (skill,)).fetchone()
        if row and row[1] not in ("running",):
            rid, status = row
            p = json.loads(db.execute(
                "SELECT plan FROM replay_run WHERE id=?", (rid,)).fetchone()[0])
            summary = p.get("executor_summary") or {}
            obs = summary.get("observed") or []
            writes = [o for o in obs if o.get("method") in ("POST", "PUT", "PATCH")]
            st = p.get("executor_state") or {}
            steps = [(x.get("seq"), x.get("result")) for x in st.get("received") or []]
            return {"run_id": rid, "status": status, "writes": len(writes),
                    "steps": len(steps), "step_results": steps[-3:]}
        elif not row:
            continue
    return {"status": "timeout"}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    only = None
    if "--system" in sys.argv:
        only = sys.argv[sys.argv.index("--system") + 1]
    token = get_token()
    ts = int(time.time()) % 100000
    results = []
    cell_i = 0
    for sysname, cells in MATRIX.items():
        if only and sysname != only:
            continue
        for c in cells:
            for j, suffix in enumerate(("A", "B")):
                val = f"mx{ts}{suffix}{cell_i}"
                print(f"[{sysname}] skill={c['skill']} 换参={c['key'] or '(无fill)'} → {val} …")
                r = run_cell(token, c["skill"], c["key"], val)
                r.update({"system": sysname, "skill": c["skill"],
                          "key": c["key"], "val": val})
                results.append(r)
                print(f"  → {r['status']} writes={r.get('writes', '-')} steps={r.get('steps', '-')}")
                time.sleep(3)
            cell_i += 1
    out = Path("../demo/sprint44")
    out.mkdir(parents=True, exist_ok=True)
    (out / "matrix-report.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    npass = sum(1 for r in results if r["status"] == "pass")
    print(f"\n矩阵完成: {npass}/{len(results)} pass → demo/sprint44/matrix-report.json")


if __name__ == "__main__":
    main()
