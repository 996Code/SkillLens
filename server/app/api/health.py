from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import RecordingSession, RawEvent

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/health")
async def health(db: Session = Depends(get_db)) -> dict:
    """防再生④：会话质量信号——零 navigation 会话失系统派生锚
    （105 会话实证），比率可见才能发现采集退化。"""
    total = db.query(func.count(RecordingSession.id)).scalar() or 0
    with_nav = db.execute(
        select(func.count(func.distinct(RawEvent.session_id)))
        .where(RawEvent.kind == "navigation")).scalar() or 0
    no_nav = max(total - with_nav, 0)
    ratio = round(no_nav / total, 4) if total else 0.0
    return {
        "status": "ok",
        "sessions_no_navigation": {"count": no_nav, "total": total, "ratio": ratio},
    }
