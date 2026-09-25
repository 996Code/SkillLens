"""S12 N1：新功能增量发现列表（只读）。

GET /discoveries
  - status 过滤（new | linked | dismissed）
  - linked_delta_id 过滤（N2：报告页按 delta 查"已发现实现"）
  - observed_count 倒序，limit 默认 50
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import DiscoveredFeature

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/discoveries")
async def list_discoveries(status: str | None = None,
                           linked_delta_id: int | None = None,
                           limit: int = Query(50, ge=1, le=200),
                           db: Session = Depends(get_db)) -> list:
    q = db.query(DiscoveredFeature)
    if status:
        q = q.filter(DiscoveredFeature.status == status)
    if linked_delta_id is not None:
        q = q.filter(DiscoveredFeature.linked_delta_id == linked_delta_id)
    rows = q.order_by(DiscoveredFeature.observed_count.desc(),
                      DiscoveredFeature.id).limit(limit).all()
    return [{"id": r.id, "session_id": r.session_id,
             "api_template": r.api_template, "anchor_label": r.anchor_label,
             "observed_count": r.observed_count, "status": r.status,
             "linked_delta_id": r.linked_delta_id,
             "first_seen": r.first_seen.isoformat(),
             "last_seen": r.last_seen.isoformat()} for r in rows]
