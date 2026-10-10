import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import ReplayRun, Skill
from app.replay.runner import run_replay, run_replay_batch
from app.api.auth import WRITE_GUARD

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ReplayRequest(BaseModel):
    overrides: dict[str, str] = {}
    confirm_side_effect: bool = False


@router.post("/skills/{skill_id}/replay", dependencies=WRITE_GUARD)
async def replay(skill_id: int, body: ReplayRequest, db: Session = Depends(get_db)) -> dict:
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    if skill.status == "superseded":
        raise HTTPException(409, f"该 Skill 版本已被取代（v{skill.superseded_by}），请使用新版本")
    run = await run_replay(db, skill_id, body.overrides, body.confirm_side_effect)
    return {"id": run.id, "skill_id": run.skill_id, "mode": run.mode, "status": run.status,
            "plan": run.plan, "executed": run.executed,
            "assertion_results": run.assertion_results,
            "attribution": run.attribution, "artifact_path": run.artifact_path,
            "duration_ms": run.duration_ms, "flaky": run.flaky,
            "created_at": run.created_at.isoformat() if run.created_at else None}


class ReplayBatchRequest(BaseModel):
    skill_ids: list[int] = Field(min_length=1)  # 空列表 → 422
    overrides_map: dict[int, dict] = {}         # 按 skill_id 给 overrides，缺省空
    confirm_side_effect: bool = False           # C1：批级门控参数


@router.post("/skills/replay-batch", dependencies=WRITE_GUARD)
async def replay_batch(body: ReplayBatchRequest,
                       db: Session = Depends(get_db)) -> dict:
    """S13 F3 批回放：browser 实例复用（一次 launch 多 context 串行），
    confirm_side_effect 批级——false 时各 skill 独立走 shadow 门控。"""
    runs = await run_replay_batch(db, body.skill_ids, body.overrides_map,
                                  body.confirm_side_effect)
    results = [{"skill_id": r.skill_id, "run_id": r.id,
                "status": r.status, "mode": r.mode} for r in runs]
    return {"results": results, "total": len(results),
            "pass_count": sum(1 for r in results if r["status"] == "pass"),
            "fail_count": sum(1 for r in results if r["status"] == "fail"),
            "error_count": sum(1 for r in results if r["status"] == "error")}


@router.get("/replay-runs/{run_id}")
async def get_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    run = db.get(ReplayRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="replay run not found")
    executed = run.executed
    # AM3：插件 run 的 executed 恒空（executor 只发 observed——步结果在
    # plan.executor_state.received）。合成 executed 形态供详情页步骤表+
    # 三态标签呈现（服务端 run 不受影响——原值直通）。
    if (run.executor == "extension" and not executed
            and isinstance(run.plan, dict)):
        instructions = run.plan.get("executor_instructions")
        ins_by_seq = {i.get("seq"): i for i in instructions}             if isinstance(instructions, list) else {}
        state = run.plan.get("executor_state")
        received = state.get("received") if isinstance(state, dict) else None
        executed = []
        # 体检🟢：received 脏数据（非 dict 条目）逐条防御——跳过不炸
        for rec in received if isinstance(received, list) else []:
            if not isinstance(rec, dict):
                continue
            ins = ins_by_seq.get(rec.get("seq")) or {}
            ev = rec.get("evidence")
            executed.append({
                "kind": ins.get("op") if isinstance(ins, dict) else None,
                "label": (ins.get("label") or ins.get("name"))
                         if isinstance(ins, dict) else None,
                "ok": rec.get("result") == "ok",
                "error": (ev.get("error") if isinstance(ev, dict) else None)
                         or (None if rec.get("result") == "ok"
                             else rec.get("result"))})
    return {"id": run.id, "skill_id": run.skill_id, "mode": run.mode, "status": run.status,
            "plan": run.plan, "executed": executed,
            "assertion_results": run.assertion_results,
            "attribution": run.attribution, "artifact_path": run.artifact_path,
            "duration_ms": run.duration_ms, "flaky": run.flaky,
            "created_at": run.created_at.isoformat() if run.created_at else None}


@router.get("/replay-runs/{run_id}/flow")
async def get_run_flow(run_id: int, db: Session = Depends(get_db)) -> dict:
    """S38 统一流程图：Run → 节点+边+执行注记（流程图基座）。
    节点类型：page/action/state/assert（业务语义层）。"""
    from app.replay.flow_graph import build_run_flow
    run = db.get(ReplayRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="replay run not found")
    return build_run_flow(run)


_STEP_FILE_RE = re.compile(r"^(start|step-\d+)\.png$")


@router.get("/replay-runs/{run_id}/step-screenshot")
async def get_step_screenshot(run_id: int, file: str = Query(...),
                              db: Session = Depends(get_db)) -> FileResponse:
    """S33：步骤截图出图。白名单 = plan.step_screenshots.files ∩ 文件名规则
    （双校验防路径穿越）；文件缺失（artifacts 清理）404。"""
    run = db.get(ReplayRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="replay run not found")
    meta = (run.plan or {}).get("step_screenshots") or {}
    if (not _STEP_FILE_RE.match(file) or file not in meta.get("files", [])):
        raise HTTPException(status_code=404, detail="screenshot not found")
    path = Path(meta["dir"]) / file
    if not path.is_file():
        raise HTTPException(status_code=404, detail="screenshot file missing")
    return FileResponse(str(path), media_type="image/png")
