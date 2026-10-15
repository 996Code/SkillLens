"""AR6 deterministic backfill utilities.

用法（生产库副本先验）：
  cd server && uv run python -m scripts.ar_backfill [--dry-run] [--limit N]
产出：artifacts/migrations/ar-backfill-summary.json（不含敏感 URL/值）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from app.change.failure_class import classify_run
from app.models import ReplayRun


def _run_payload(row: ReplayRun) -> dict:
    plan = row.plan or {}
    executed = plan.get("executor_state", {}).get("received") \
        or plan.get("steps") or []
    # 服务端 runner 的失败证据常在 attribution（错误摘要列）——把它作为
    # 一条合成步骤错误喂给分类器（与 classify_run 的证据形态对齐）
    if row.attribution:
        executed = list(executed) + [{"kind": "summary",
                                      "ok": False,
                                      "error": row.attribution}]
    return {
        "status": row.status,
        "attribution": row.attribution,
        "assertions": row.assertion_results or [],
        "executed": executed,
    }


def backfill_failure_classes(db: Session, *, dry_run: bool = False,
                             limit: int | None = None,
                             batch: int = 100) -> dict:
    """fail/error 且 failure_class 为空的行按确定性 classify_run 重算。

    已有分类不覆盖（人工/历史判定保留）；无证据行保持 None（不猜）。
    """
    q = db.query(ReplayRun).filter(
        ReplayRun.status.in_(("fail", "error")),
        ReplayRun.failure_class.is_(None),
    ).order_by(ReplayRun.id)
    rows = q.all() if limit is None else q.limit(limit).all()

    stats = {"processed": 0, "changed": 0, "unclassified": 0,
             "by_class": {}, "dry_run": dry_run}
    for row in rows:
        stats["processed"] += 1
        cls = classify_run(_run_payload(row))
        if cls is None:
            stats["unclassified"] += 1
            continue
        stats["by_class"][cls] = stats["by_class"].get(cls, 0) + 1
        if not dry_run:
            row.failure_class = cls
        stats["changed"] += 1
    if not dry_run and stats["changed"]:
        db.commit()

    out_dir = Path("artifacts/migrations")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "ar-backfill-summary.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=1), encoding="utf-8")
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    from app.db import SessionLocal
    stats = backfill_failure_classes(SessionLocal(), dry_run=args.dry_run,
                                     limit=args.limit)
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    if stats["processed"] == 0:
        sys.exit(0)


if __name__ == "__main__":
    main()
