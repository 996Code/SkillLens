"""s45 单链复验：跑指定链并回显每个技能 run 判定（flaky 可见）。"""
import json
import sqlite3
import sys
import time

sys.path.insert(0, "scripts")
from s45_regression import run_chain, get_token  # noqa: E402

cid = int(sys.argv[1])
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
token = get_token()
db = sqlite3.connect("skilllens.db")
before = {r[0] for r in db.execute("SELECT id FROM replay_run").fetchall()}
r = run_chain(token, db, cid)
print(f"chain {cid}: {r['verdict']} | {r.get('summary','')[:70]}")
for rid in sorted({r0 for r0 in db.execute("SELECT id FROM replay_run")} - before):
    row = db.execute("SELECT skill_id, status, flaky FROM replay_run WHERE id=?", (rid,)).fetchone()
    print(f"  run {row[0]} skill {row[1]}: {row[2]} flaky={row[3]}")
