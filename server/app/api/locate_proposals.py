"""S24 块 U T3/T4：定位修复提案 API。

- GET  /skills/{id}/locate-proposals → 提案列表（含源 run 归因——U3 链路）；
- POST /locate-proposals/{id}/reject → 人工否决（reviewer/admin）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.auth import require_role
from app.db import SessionLocal
from app.models import LocateProposal, ReplayRun, Skill, User

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _item(db: Session, row: LocateProposal) -> dict:
    attribution = None
    if row.source_run_id:
        run = db.get(ReplayRun, row.source_run_id)
        attribution = run.attribution if run else None
    if not attribution:
        # S43-4：源 run 内联自愈 pass 时无失败归因——给确定性描述
        # （提案状态语义），避免提案列表归因字段空洞
        attribution = (f"提案 {row.status}（verify_count={row.verify_count}）："
                       f"标签 {row.step_label!r} → {row.proposed_label!r}")
    return {
        "id": row.id,
        "skill_id": row.skill_id,
        "step_label": row.step_label,
        "proposed_label": row.proposed_label,
        "strategy": row.strategy,
        "status": row.status,
        "verify_count": row.verify_count,
        "source_run_id": row.source_run_id,
        "applied_skill_id": row.applied_skill_id,
        "attribution": attribution,
        "created_at": row.created_at.isoformat(),
    }


@router.get("/skills/{skill_id}/locate-proposals")
async def list_proposals(skill_id: int, db: Session = Depends(get_db)) -> list:
    if not db.get(Skill, skill_id):
        raise HTTPException(404, "skill not found")
    rows = db.query(LocateProposal).filter(
        LocateProposal.skill_id == skill_id
    ).order_by(LocateProposal.id.desc()).all()
    return [_item(db, r) for r in rows]


@router.post("/locate-proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_role("reviewer", "admin"))):
    row = db.get(LocateProposal, proposal_id)
    if row is None:
        raise HTTPException(404, "proposal not found")
    if row.status == "rejected":
        raise HTTPException(409, "已否决")
    row.status = "rejected"
    db.commit()
    return {"ok": True, "id": row.id, "status": row.status}


@router.post("/locate-proposals/{proposal_id}/promote")
async def promote_proposal(proposal_id: int, db: Session = Depends(get_db),
                           user: User = Depends(require_role("reviewer", "admin"))):
    """S26：人工提前晋升（跳过 N 次计数）——回写骨架生成 skill 新版本。"""
    from app.replay.repair import _apply_proposal_version
    row = db.get(LocateProposal, proposal_id)
    if row is None:
        raise HTTPException(404, "proposal not found")
    if row.status not in ("verified", "promoted"):
        raise HTTPException(409, f"状态 {row.status} 不可晋升（需 verified）")
    if row.status == "verified":
        row.status = "promoted"
        _apply_proposal_version(db, row)
        db.commit()
    return {"ok": True, "id": row.id, "status": row.status,
            "applied_skill_id": row.applied_skill_id}


@router.get("/skills/{skill_id}/diff")
async def promotion_diff(skill_id: int, db: Session = Depends(get_db)) -> list:
    """AJ4 晋升 diff 视图（mabl 元素历史版本表对应物）：旧标签→新标签
    +归因理由（source_run）+verify 计数——supersede 链的呈现层。"""
    from app.models import Skill
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(404, "skill not found")
    # 当前骨架 label（旧值）
    current = {}
    for st in skill.skeleton or []:
        lbl = st.get("label")
        if lbl:
            current[st.get("signature", "")] = lbl
    rows = db.query(LocateProposal).filter(
        LocateProposal.skill_id == skill_id,
        LocateProposal.status.in_(("proposed", "verified", "promoted"))).all()
    return [{"step_label": r.step_label,
             "current_label": current.get(f"click:{r.step_label}", ""),
             "proposed_label": r.proposed_label,
             "status": r.status, "strategy": r.strategy,
             "verify_count": r.verify_count or 0,
             "source_run_id": r.source_run_id} for r in rows]


@router.get("/skills/{skill_id}/confidence")
async def confidence_panel(skill_id: int, db: Session = Depends(get_db)) -> list:
    """AJ4 置信面板（mabl Find Summary 语义）：verify 计数明细+阈值判定
    ——低置信（<LOCATE_AUTO_PROMOTE_N）只告警不晋升。"""
    from app.config import LOCATE_AUTO_PROMOTE_N
    rows = db.query(LocateProposal).filter(
        LocateProposal.skill_id == skill_id,
        LocateProposal.status.in_(("proposed", "verified", "promoted"))).all()
    return [{"step_label": r.step_label,
             "proposed_label": r.proposed_label,
             "verify_count": r.verify_count or 0,
             "threshold": LOCATE_AUTO_PROMOTE_N,
             "low_confidence": (r.verify_count or 0) < LOCATE_AUTO_PROMOTE_N,
             "status": r.status} for r in rows]
