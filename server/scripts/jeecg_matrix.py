"""JeecG 链路矩阵驱动：CDP 开 executor.html 页签 + DB 轮询对账（v21_matrix 模式）。

用法：cd server && uv run python scripts/jeecg_matrix.py [--ids 269,263,271] [--rounds 2] [--auto]
非 --auto 模式仅开页（人工点确认）；--auto 全自动（验收授权由本脚本持有）。
"""
import argparse
import asyncio
import json
import os
import sys
import time
import urllib.request
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SERVER = os.environ.get("SL_BASE", "http://127.0.0.1:8710")
CDP = os.environ.get("CDP_URL", "http://127.0.0.1:9222")
URLOPEN_TIMEOUT = 10

import urllib.request as _u


def _get(url: str):
    return json.loads(_u.urlopen(url, timeout=URLOPEN_TIMEOUT).read())


def _post(url: str, body: dict, token: str = "") -> dict:
    req = _u.Request(url, data=json.dumps(body).encode(), method="POST",
                     headers={"content-type": "application/json",
                              **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        return json.loads(_u.urlopen(req, timeout=URLOPEN_TIMEOUT).read())
    except _u.HTTPError as e:
        return {"_status": e.code, "_detail": e.read().decode()[:300]}


def login() -> str:
    pw = os.environ.get("SL_ADMIN_PW", "")
    if not pw:
        sys.exit("need SL_ADMIN_PW")
    r = _post(f"{SERVER}/api/v1/auth/login", {"username": "admin", "password": pw})
    if "token" not in r:
        sys.exit(f"login failed: {r}")
    return r["token"]


def open_and_run(url: str, watch_s: int = 30) -> str:
    """开页 + 注入点击「开始执行」（auto 模式下 C1 由调用方持有；
    页面设计 auto=1 只跳 confirm 弹窗、仍需点击按钮——验收驱动在此代点）。"""
    import websockets

    async def _run():
        ver = _get(f"{CDP}/json/version")
        async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=10 ** 7) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Target.createTarget",
                                      "params": {"url": url}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if msg.get("id") == 1:
                    return msg["result"]["targetId"]

    tid = asyncio.run(_run())
    time.sleep(2.5)  # 等页面加载+技能元数据预取

    async def _click():
        tgt = _get(f"{CDP}/json/list")
        t = next((x for x in tgt if x.get("id") == tid), None)
        if not t:
            print("  [warn] 执行页签已消失（可能立刻失败/被关闭）")
            return
        async with websockets.connect(t["webSocketDebuggerUrl"], max_size=10 ** 7) as sw:
            await sw.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
                "expression": "(document.getElementById('go')||{}).click && document.getElementById('go').click()"}}))
            await asyncio.wait_for(sw.recv(), 10)

    asyncio.run(_click())
    return tid


def close_tab(target_id: str) -> None:
    import websockets

    async def _close():
        ver = _get(f"{CDP}/json/version")
        async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=10 ** 7) as ws:
            await ws.send(json.dumps({"id": 1, "method": "Target.closeTarget",
                                      "params": {"targetId": target_id}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if msg.get("id") == 1:
                    return

    asyncio.run(_close())


def wait_run(token: str, skill_id: int, since_id: int, timeout_s: int = 420) -> dict:
    """轮询该 skill 的最新 executor run（run.skill_id+executor=extension），
    id > since_id 且 status 终态即返回。SQLite 快照隔离：session 必须每轮
    新开（开在循环外会钉死在旧快照，永远看不到新 run——v21_matrix 同款处理）。"""
    from app.db import SessionLocal
    from app.models import ReplayRun

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        db = SessionLocal()
        try:
            row = (db.query(ReplayRun)
                   .filter(ReplayRun.skill_id == skill_id,
                           ReplayRun.executor == "extension",
                           ReplayRun.id > since_id)
                   .order_by(ReplayRun.id.desc()).first())
            if row and row.status in ("pass", "fail", "error", "aborted"):
                return {"id": row.id, "status": row.status,
                        "executed": row.executed or [],
                        "assertions": row.assertion_results or []}
        finally:
            db.close()
        time.sleep(3)
    return {"id": None, "status": "timeout"}


def last_run_id(skill_id: int):
    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    try:
        row = (db.query(ReplayRun)
               .filter(ReplayRun.skill_id == skill_id,
                       ReplayRun.executor == "extension")
               .order_by(ReplayRun.id.desc()).first())
        return row.id if row else 0
    finally:
        db.close()


def _ext_id() -> str:
    """插件 id 运行时从 CDP 目标列表发现（插件重载后 id 会变——从常驻浏览器
    实际加载的扩展目标反查才可靠；manifest 的 name 不是 id）。"""
    for t in _get(f"{CDP}/json"):
        u = t.get("url", "")
        if u.startswith("chrome-extension://"):
            return u.split("/")[2]
    raise SystemExit(f"CDP {CDP} 未发现 chrome-extension:// 目标——常驻浏览器未起或插件未加载")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="269,263,271,118,74,261")
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--fills", default="", help="skillId:orig=new,orig2=new2;...")
    ap.add_argument("--keep", action="store_true", help="不关执行页签（人工观察）")
    args = ap.parse_args()

    token = login()
    ext_id = _ext_id()
    print(f"[login ok] token={token[:8]}…  ext={ext_id[:12]}…")

    fills: dict[str, dict[str, str]] = {}
    for part in args.fills.split(";"):
        if not part or ":" not in part:
            continue
        sid, kv = part.split(":", 1)
        fills[sid] = {p.split("=")[0]: p.split("=")[1]
                      for p in kv.split(",") if "=" in p}

    results = []
    for sid_str in args.ids.split(","):
        sid = int(sid_str)
        for rnd in range(1, args.rounds + 1):
            since = last_run_id(sid)
            q = {"skill": str(sid), "token": token}
            if args.auto:
                q["auto"] = "1"
            for k, v in fills.get(sid_str, {}).items():
                q[f"fill_{k}"] = v
            url = (f"chrome-extension://{ext_id}/executor.html?"
                   + "&".join(f"{k}={quote(str(v))}" for k, v in q.items()))
            print(f"\n=== skill #{sid} round {rnd} ===")
            print(f"[open] {url[:110]}…")
            tid = open_and_run(url)
            run = wait_run(token, sid, since)
            if not args.keep:
                close_tab(tid)
            ok = run["status"] == "pass"
            n_exec = len(run.get("executed") or [])
            n_assert = len(run.get("assertions") or [])
            n_fail_a = sum(1 for a in run.get("assertions") or []
                           if a.get("passed") is not True and not a.get("skipped"))
            mark = "PASS" if ok else run["status"].upper()
            print(f"  -> run #{run['id']} [{mark}] steps={n_exec} asserts={n_assert}(fail={n_fail_a})")
            if not ok:
                for st in (run.get("executed") or []):
                    if not st.get("ok"):
                        print(f"     X step: {st.get('kind')} {st.get('label') or st.get('name') or ''} err={str(st.get('error'))[:120]}")
                for a in run.get("assertions") or []:
                    if a.get("passed") is not True and not a.get("skipped"):
                        print(f"     X assert[{a.get('kind')}] {str(a.get('payload'))[:110]} -> {a.get('result')}")
            results.append((sid, rnd, run["status"]))
            time.sleep(2)

    print("\n===== 汇总 =====")
    npass = sum(1 for _, _, s in results if s == "pass")
    print(f"{npass}/{len(results)} pass")
    for sid, rnd, s in results:
        print(f"  #{sid} r{rnd}: {s}")
    with open("D:/tmp/jeecg_matrix_result.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
