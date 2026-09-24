"""evidence_edge 同步（Sprint 10 T4）。

边语义（v1）：
- session → action：type="contains"（会话包含锚点动作）
- action → api：type="calls"（锚点动作调用 API 模板）
- api → state：type="yields"——v1 暂不生成（state 信号需查 semantic_action，
  避免过度解析 signature；S12 Impact Analysis 落地时补）。

边是全局证据资产（非 skill 私有）：re-induce 不清边，计数累加（幂等 upsert）。
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alignment, EvidenceEdge


def _parse_signature_apis(signature: str) -> list[str]:
    """signature 形如 'click:保存|GET:/a,POST:/b' → 取方法:路径段列表。"""
    if "|" not in signature:
        return []
    api_part = signature.split("|", 1)[1]
    return [seg for seg in api_part.split(",") if seg]


def _parse_signature_action(signature: str) -> str:
    return signature.split("|", 1)[0]


def _upsert_edge(db: Session, src: str, dst: str, edge_type: str) -> None:
    row = db.execute(
        select(EvidenceEdge).where(EvidenceEdge.src == src, EvidenceEdge.dst == dst,
                                   EvidenceEdge.type == edge_type)
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row is None:
        db.add(EvidenceEdge(src=src, dst=dst, type=edge_type,
                            evidence_count=1, first_seen=now, last_seen=now))
    else:
        row.evidence_count += 1
        row.last_seen = now


def sync_evidence_edges(db: Session, alignment: Alignment) -> int:
    """从对齐骨架生成边（幂等累加），返回新增+更新的边数。"""
    touched = 0
    for step in alignment.skeleton or []:
        signature = step.get("signature", "")
        if not signature:
            continue
        action = _parse_signature_action(signature)
        apis = _parse_signature_apis(signature)
        for sid in (step.get("session_window_seqs") or {}):
            _upsert_edge(db, sid, action, "contains")
            touched += 1
        for api in apis:
            _upsert_edge(db, action, api, "calls")
            touched += 1
    return touched
