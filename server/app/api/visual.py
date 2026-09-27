"""S22 块 T T3：视觉基线 API。

- GET  /skills/{id}/visual-baseline → 基线信息 + 最近一次 visual 断言结果（无则 null）；
- POST /skills/{id}/visual-baseline/reset → 删行删文件（reviewer/admin；下次 PASS 重建）；
- GET  /skills/{id}/visual-baseline/image?which=baseline|latest → FileResponse。
  which 白名单映射固定路径，无用户路径输入（防穿越）。
"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.db import SessionLocal
from app.models import ReplayRun, Skill, VisualBaseline, User
from app.replay.runner import ARTIFACT_DIR
from app.replay.visual import visual_dir

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _baseline_out(row: VisualBaseline | None) -> dict | None:
    if row is None:
        return None
    return {"skill_id": row.skill_id, "file_path": row.file_path,
            "image_hash": row.image_hash, "width": row.width,
            "height": row.height, "source_run_id": row.source_run_id,
            "created_at": row.created_at.isoformat()}


def _last_visual_result(db: Session, skill_id: int) -> dict | None:
    """最近一次含 visual_baseline 断言的回放结果（前端并排图与差异摘要数据源）。"""
    runs = db.execute(
        select(ReplayRun).where(ReplayRun.skill_id == skill_id)
        .order_by(ReplayRun.id.desc())).scalars().all()
    for run in runs:
        for row in reversed(run.assertion_results or []):
            if (row.get("payload") or {}).get("kind") == "visual_baseline":
                return {"run_id": run.id, "run_status": run.status,
                        "passed": row["passed"], "payload": row["payload"],
                        "ts": run.created_at.isoformat()}
    return None


@router.get("/skills/{skill_id}/visual-baseline")
async def get_visual_baseline(skill_id: int, db: Session = Depends(get_db)) -> dict:
    if not db.get(Skill, skill_id):
        raise HTTPException(status_code=404, detail="skill not found")
    row = db.query(VisualBaseline).filter_by(skill_id=skill_id).first()
    return {"baseline": _baseline_out(row),
            "last_result": _last_visual_result(db, skill_id)}


@router.post("/skills/{skill_id}/visual-baseline/reset")
async def reset_visual_baseline(skill_id: int, db: Session = Depends(get_db),
                                user: User = Depends(require_role("reviewer", "admin"))):
    row = db.query(VisualBaseline).filter_by(skill_id=skill_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="baseline not found")
    try:
        Path(row.file_path).unlink(missing_ok=True)
    except OSError:
        pass  # 文件缺失不阻断表行删除
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/skills/{skill_id}/visual-baseline/image")
async def get_visual_image(skill_id: int, which: str = "baseline",
                           db: Session = Depends(get_db)) -> FileResponse:
    if which not in ("baseline", "latest"):
        raise HTTPException(status_code=422, detail="which must be baseline|latest")
    path = visual_dir(ARTIFACT_DIR, skill_id) / f"{which}.png"
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"{which} image not found")
    return FileResponse(path, media_type="image/png")
