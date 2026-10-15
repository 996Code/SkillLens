import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import ALLOWED_ORIGINS
from app.db import SessionLocal
from app.models import RawEvent, RecordingSession
from app.schemas import RawEventIn

router = APIRouter()

# 单批事件上限：逐条 commit 的实现下，超大批会把 worker 钉死数分钟并写入
# 任意多行——本端点豁免鉴权（插件直连），必须有确定性的体量闸门。
# 插件侧 BATCH=50（background/uploader.ts），此处留 40x 余量。
MAX_EVENTS_PER_BATCH = 2000


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ingest_guard(x_skilllens_agent: str | None = Header(default=None)) -> None:
    """跨域污染守卫（评审 #4）：CORS 默认 * 叠加本路由豁免鉴权——任意网页
    可向本机 POST 伪造会话。共享 header 插件侧必带（与 C2 采集零耦合）。
    配置显式收紧（非 *）时豁免——Origin 已由 CORS 管住。"""
    if "*" in ALLOWED_ORIGINS and x_skilllens_agent != "1":
        raise HTTPException(403, "missing X-SkillLens-Agent header")


class SessionCreate(BaseModel):
    target_system: str = ""
    note: str = ""
    # S10 C2：来源标记——popup 用户开录 real_traffic；auto_record/旧客户端
    # 缺省 demo；AP1 常驻采集 ambient（分轨——不污染 real_traffic 学习口径）
    source: Literal["demo", "real_traffic", "ambient"] = "demo"


@router.post("/sessions", dependencies=[Depends(_ingest_guard)])
async def create_session(body: SessionCreate, db: Session = Depends(get_db)) -> dict:
    session_id = str(uuid.uuid4())
    db.add(RecordingSession(id=session_id, target_system=body.target_system,
                            note=body.note, source=body.source))
    db.commit()
    return {"session_id": session_id}


@router.post("/sessions/{session_id}/events", dependencies=[Depends(_ingest_guard)])
async def ingest_events(session_id: str, events: list[RawEventIn],
                        db: Session = Depends(get_db)) -> dict:
    if len(events) > MAX_EVENTS_PER_BATCH:
        raise HTTPException(413, f"批量过大：单请求上限 {MAX_EVENTS_PER_BATCH} 条")
    if not db.get(RecordingSession, session_id):
        raise HTTPException(404, detail="session not found")
    # 批量 409 降级（评审 #5）：一条旧 seq 会让整批事件永久丢失（重发同错）。
    # 逐条落库：重复键跳过（幂等重发安全），其余照常入库。
    accepted = 0
    duplicates = 0
    for e in events:
        db.add(RawEvent(session_id=session_id, seq=e.seq, page_id=e.page_id,
                        ts=e.ts, kind=e.kind, payload=e.payload))
        try:
            db.commit()
            accepted += 1
        except IntegrityError:
            db.rollback()
            duplicates += 1
    return {"accepted": accepted, "duplicates": duplicates}
