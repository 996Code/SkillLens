"""S25 块 W1：Playwright 脚本导出端点。

GET /skills/{id}/export/playwright → text/x-python（attachment）。
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Skill
from app.replay.exporter import export_flow_playwright, export_playwright

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/skills/{skill_id}/export/playwright")
async def export_skill(skill_id: int, db: Session = Depends(get_db)) -> PlainTextResponse:
    if not db.get(Skill, skill_id):
        raise HTTPException(404, "skill not found")
    script = export_playwright(db, skill_id)
    return PlainTextResponse(
        script, media_type="text/x-python",
        headers={"content-disposition":
                 f'attachment; filename="skill_{skill_id}_replay.py"'})


@router.get("/flows/{flow_id}/export/playwright")
async def export_flow(flow_id: int, db: Session = Depends(get_db)) -> PlainTextResponse:
    from app.models import SynthFlow
    if not db.get(SynthFlow, flow_id):
        raise HTTPException(404, "flow not found")
    script = export_flow_playwright(db, flow_id)
    return PlainTextResponse(
        script, media_type="text/x-python",
        headers={"content-disposition":
                 f'attachment; filename="flow_{flow_id}_replay.py"'})
