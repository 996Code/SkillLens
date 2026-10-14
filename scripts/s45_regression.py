"""s45 全量回归轮：52 格技能矩阵×2 轮 + 16 链×1 轮，真实执行页路径。

背景：差距清单清零后首个全广度回归（2026-10-14）。目的：
1. 确认 v2.8.5 收官后全库无链级损伤（对比 2026-10-06 P3 矩阵 52/52）
2. 为积压缓修批（execute() 重构/B8/B9/D7/token 换票/AK6 后续批——
   全部标注"需 52 链真机回归支撑"）建立回归安全网基线

协议：
- 矩阵 Phase A：2026-10-06 矩阵的 26 技能（4 个 superseded 已映射后继、
  166/167 同映射去重 → 25 技能）× 2 轮，无换参（与 10-06 协议一致可对比）
- 链 Phase B：16 链全量 × 1 轮（链 10 已删；8 链 10-13 刚验过，全 16 跑
  含历史链 1/13/15/18——若 dup 链失败不即时修，记录进报告转清理候选）

产出：demo/sprint45/regression-report.json（matrix+chains 两段）

用法：cd server && uv run python ../scripts/s45_regression.py [--matrix|--chains]
"""
import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx
from websockets.sync.client import connect

CDP = "http://127.0.0.1:9222"
SERVER = "http://127.0.0.1:8710/api/v1"
EXT = "chrome-extension://iifhfcajmahbdbjljhmfknfnachpcpgl/executor.html"

# 2026-10-06 matrix-ext.json 的 26 技能 → 当前库映射
SUPERSEDED_MAP = {156: 295, 166: 157, 167: 157, 168: 101}

MATRIX = {
    "snipe":   [154, 155, 295],          # 156→295
    "dolibarr": [157, 188, 189, 190, 191],  # 166/167→157 去重（原 4 技能）
    "odoo":    [178, 179, 180],
    "erpnext": [234, 235, 236],
    "ruoyi":   [256, 257, 258],
    "jeecg":   [269, 270, 271, 276],
    "zentao":  [277, 285, 287],
}

CHAINS = list(range(1, 22))  # 1-21（10 已删，脚本内跳过不存在的）


def chains_filter(argv: list[str]) -> list[int]:
    """--chain 13,15 或 --chain-from 15：支持补跑/单跑。"""
    if "--chain" in argv:
        i = argv.index("--chain")
        return [int(x) for x in argv[i + 1].split(",")]
    if "--chain-from" in argv:
        i = argv.index("--chain-from")
        return [c for c in CHAINS if c >= int(argv[i + 1])]
    return CHAINS


def get_token() -> str:
    with httpx.Client(timeout=15.0) as c:
        c.headers["X-SkillLens-Agent"] = "1"
        return c.post(f"{SERVER}/auth/plugin-session").json()["token"]


def _executor_tab() -> dict:
    tabs = httpx.get(f"{CDP}/json", timeout=10).json()
    return next((t for t in tabs if "executor.html" in t.get("url", "")), None) \
        or next(t for t in tabs if t["type"] == "page")


def _open_and_start(url: str) -> str:
    tab = _executor_tab()
    with connect(tab["webSocketDebuggerUrl"]) as w:
        w.send(json.dumps({"id": 1, "method": "Page.navigate",
                           "params": {"url": url}}))
        w.recv(); time.sleep(4)
    with connect(tab["webSocketDebuggerUrl"]) as w:
        w.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": "(function(){ const b=[...document.querySelectorAll('button')]"
                          ".find(x=>/开始执行|开始/.test(x.textContent));"
                          "if(!b) return 'NO_BUTTON'; b.click(); return 'CLICKED'; })()",
            "returnByValue": True}}))
        return json.loads(w.recv())["result"]["result"].get("value")


def _poll_run_terminal(db, skill: int, limit: float = 150.0) -> dict:
    t0 = time.time()
    while time.time() - t0 < limit:
        time.sleep(6)
        row = db.execute(
            "SELECT id, status FROM replay_run WHERE skill_id=? "
            "ORDER BY id DESC LIMIT 1", (skill,)).fetchone()
        if row and row[1] not in ("running",):
            rid, status = row
            plan = json.loads(db.execute(
                "SELECT plan FROM replay_run WHERE id=?", (rid,)).fetchone()[0])
            summary = plan.get("executor_summary") or {}
            obs = summary.get("observed") or []
            writes = [o for o in obs if o.get("method") in ("POST", "PUT", "PATCH")]
            return {"run_id": rid, "status": status, "writes": len(writes)}
    return {"status": "timeout"}


def run_matrix_cell(token: str, db, skill: int, note: str) -> dict:
    clicked = _open_and_start(f"{EXT}?skill={skill}&auto=1")
    if clicked != "CLICKED":
        return {"status": "error", "note": clicked}
    return _poll_run_terminal(db, skill)


def run_chain(token: str, db, chain_id: int) -> dict:
    # 链执行产生多个 run——记起始 run id，轮询「链执行结束」
    tab = _executor_tab()
    clicked = _open_and_start(f"{EXT}?chain={chain_id}&auto=1")
    if clicked != "CLICKED":
        return {"chain": chain_id, "verdict": "error", "note": clicked}
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
    phase = None
    if "--matrix" in sys.argv:
        phase = "matrix"
    elif "--chains" in sys.argv:
        phase = "chains"
    token = get_token()
    db = sqlite3.connect("skilllens.db")
    report = {"date": "2026-10-14", "matrix": [], "chains": []}

    if phase in (None, "matrix"):
        for sysname, skills in MATRIX.items():
            for skill in skills:
                for rnd in (1, 2):
                    print(f"[matrix/{sysname}] skill={skill} round={rnd} …", flush=True)
                    r = run_matrix_cell(token, db, skill, "")
                    r.update({"system": sysname, "skill": skill, "round": rnd})
                    report["matrix"].append(r)
                    print(f"  → {r['status']} writes={r.get('writes', '-')}", flush=True)
                    time.sleep(3)

    if phase in (None, "chains"):
        for cid in chains_filter(sys.argv):
            row = db.execute("SELECT name FROM chain WHERE id=?", (cid,)).fetchone()
            if not row:
                continue
            print(f"[chain {cid}] {row[0][:30]} …", flush=True)
            r = run_chain(token, db, cid)
            r["name"] = row[0]
            report["chains"].append(r)
            print(f"  → {r['verdict']}: {r.get('summary', r.get('note', ''))[:60]}", flush=True)
            time.sleep(4)

    out = Path("../demo/sprint45")
    out.mkdir(parents=True, exist_ok=True)
    (out / "regression-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    mpass = sum(1 for r in report["matrix"] if r["status"] == "pass")
    cpass = sum(1 for r in report["chains"] if "步通过（pass）" in str(r.get("summary")))
    print(f"\n回归完成: matrix {mpass}/{len(report['matrix'])} pass, "
          f"chains {cpass}/{len(report['chains'])} pass → demo/sprint45/regression-report.json")


if __name__ == "__main__":
    main()
