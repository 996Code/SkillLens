"""演示基线快照导出（Task 5）：直接读 SQLite，无 server 依赖。

聚合所有 skill 的基线指标（与 GET /api/v1/baseline/skills 同构）写入
demo/baseline/<date>-baseline.json——这就是 C2「真实流量置信度 ≥ 演示基线 80%」
的对比锚数据。

用法：
    cd server && uv run python ../scripts/baseline_snapshot.py
"""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "server" / "skilllens.db"
OUT_DIR = ROOT / "demo" / "baseline"


def _load_json(raw):
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


def latest_pass_rate(conn: sqlite3.Connection, skill_id: int) -> float | None:
    """最近一条 assertion_results 非空的 replay_run 的 passed 比例（与 API 同口径）。"""
    row = conn.execute(
        "SELECT assertion_results FROM replay_run "
        "WHERE skill_id = ? AND assertion_results IS NOT NULL "
        "ORDER BY id DESC LIMIT 1", (skill_id,)).fetchone()
    if row is None:
        return None
    results = _load_json(row[0]) or []
    if not results:
        return None
    passed = sum(1 for r in results if isinstance(r, dict) and r.get("passed"))
    return round(passed / len(results), 4)


def collect_baseline(conn: sqlite3.Connection) -> list[dict]:
    items: list[dict] = []
    for skill in conn.execute(
            "SELECT id, alignment_id, name, status, confidence, evidence_count, "
            "input_variables FROM skill ORDER BY id").fetchall():
        (sid, alignment_id, name, status, confidence, evidence_count,
         input_vars_raw) = skill
        assertion_count = conn.execute(
            "SELECT COUNT(*) FROM outcome_assertion WHERE skill_id = ?",
            (sid,)).fetchone()[0]
        window_params = None
        if alignment_id is not None:
            wp_row = conn.execute(
                "SELECT window_params FROM alignment WHERE id = ?",
                (alignment_id,)).fetchone()
            if wp_row is not None:
                window_params = _load_json(wp_row[0])
        items.append({
            "skill_id": sid,
            "name": name,
            "status": status,
            "confidence": confidence,
            "evidence_count": evidence_count,
            "assertion_count": assertion_count,
            "assertion_pass_rate": latest_pass_rate(conn, sid),
            "input_var_names": [v.get("name") for v in _load_json(input_vars_raw) or []
                                if isinstance(v, dict) and v.get("name")],
            "window_params": window_params,
        })
    return items


def main() -> int:
    if not DB_PATH.exists():
        print(f"[baseline_snapshot] 数据库不存在: {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(f"file:{DB_PATH.as_posix()}?mode=ro", uri=True)
    try:
        items = collect_baseline(conn)
    finally:
        conn.close()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    out_path = OUT_DIR / f"{now:%Y-%m-%d}-baseline.json"
    payload = {
        "meta": {
            "exported_at": now.isoformat(timespec="seconds"),
            "db_path": str(DB_PATH),
            "skill_count": len(items),
        },
        "skills": items,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[baseline_snapshot] {len(items)} skills -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
