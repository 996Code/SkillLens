"""AH1 链（chain）CRUD：链=纯数据，服务端只存不解释（规则在插件侧解释——
降耦合原则：不为任何系统写执行代码）。

- POST /chains          创建（name/system/steps）—— WRITE_GUARD
- GET /chains           列表（?system= 过滤；空间小窗按当前 tab 系统取）
- GET /chains/{id}      详情（steps 附技能概要：id/name/requires_confirmation，
                        小窗与 executor 链模式渲染用）
- DELETE /chains/{id}   删除 —— WRITE_GUARD
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Alignment, Chain, RawEvent, Skill
from app.api.auth import WRITE_GUARD

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class ChainStepIn(BaseModel):
    skill_id: int
    overrides: dict[str, str] = Field(default_factory=dict)


class ChainIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    system: str = Field(min_length=1, max_length=40)
    steps: list[ChainStepIn] = Field(min_length=1)


def _validate_steps(db: Session, steps: list[ChainStepIn]) -> None:
    """skill_id 必须存在——技能删除后链不可静默悬空（创建时即拒绝）。"""
    for st in steps:
        if not db.get(Skill, st.skill_id):
            raise HTTPException(422, f"skill 不存在：{st.skill_id}")


def _fill_fields(db: Session, skill_id: int) -> list[dict]:
    """AI2 防呆：fill 字段候选——链 overrides 的合法 key 集（lesson #49：
    key 语义=录制的 input 事件 name，变量名可能一字之差静默失效）。
    直接查参考会话 input 事件（name+首值）——与 compile_skeleton_plan
    的 fill 投影同源，不跑完整编译。"""
    s = db.get(Skill, skill_id)
    fills: list[dict] = []
    if not s or not s.alignment_id:
        return fills
    try:
        al = db.get(Alignment, s.alignment_id)
        ref_sid = (al.session_ids or [None])[0] if al else None
        if not ref_sid:
            return fills
        rows = db.execute(
            select(RawEvent).where(
                RawEvent.session_id == ref_sid,
                RawEvent.kind == "action").order_by(RawEvent.ts, RawEvent.seq)
        ).scalars().all()
        seen: set[str] = set()
        for r in rows:
            p = r.payload or {}
            if p.get("type") == "input":
                nm = str(p.get("name") or "")
                if nm and nm not in seen:
                    seen.add(nm)
                    fills.append({"name": nm, "value": str(p.get("value", ""))[:60]})
    except Exception:
        pass
    return fills


def _skill_brief(db: Session, skill_id: int) -> dict:
    from app.replay.plan import requires_confirmation
    s = db.get(Skill, skill_id)
    return {"id": s.id, "name": s.name,
            "requires_confirmation": requires_confirmation(s.skeleton or []),
            "fill_fields": _fill_fields(db, skill_id)}


@router.post("/chains", status_code=201, dependencies=WRITE_GUARD)
async def create_chain(body: ChainIn, db: Session = Depends(get_db)) -> dict:
    _validate_steps(db, body.steps)
    row = Chain(name=body.name, system=body.system,
                steps=[st.model_dump() for st in body.steps])
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "system": row.system,
            "steps": row.steps}


@router.get("/chains")
async def list_chains(system: str = "", db: Session = Depends(get_db)) -> list[dict]:
    q = db.query(Chain)
    if system:
        q = q.filter(Chain.system == system)
    return [{"id": r.id, "name": r.name, "system": r.system,
             "steps": r.steps, "created_at": str(r.created_at)}
            for r in q.order_by(Chain.id.desc()).all()]


@router.get("/chains/{chain_id}")
async def get_chain(chain_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Chain, chain_id)
    if not row:
        raise HTTPException(404, "chain not found")
    steps = []
    for st in row.steps or []:
        brief = _skill_brief(db, st.get("skill_id", 0)) \
            if db.get(Skill, st.get("skill_id", 0)) else None
        steps.append({"skill_id": st.get("skill_id"),
                      "overrides": st.get("overrides") or {},
                      "skill": brief})
    return {"id": row.id, "name": row.name, "system": row.system,
            "steps": steps, "created_at": str(row.created_at)}


@router.delete("/chains/{chain_id}", dependencies=WRITE_GUARD)
async def delete_chain(chain_id: int, db: Session = Depends(get_db)) -> dict:
    row = db.get(Chain, chain_id)
    if not row:
        raise HTTPException(404, "chain not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/chains/fills/{skill_id}")
async def skill_fill_fields(skill_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """AI2 防呆：单技能 fill 候选（面板组链时按需取——列表端点不逐技能
    查 events，288 技能全量 fills 是重查询）。"""
    if not db.get(Skill, skill_id):
        raise HTTPException(404, "skill not found")
    return _fill_fields(db, skill_id)


@router.post("/chains/{chain_id}/run", dependencies=WRITE_GUARD)
async def run_chain(chain_id: int, wait: int = 0,
                    confirm_side_effect: bool = True,
                    db: Session = Depends(get_db)) -> dict:
    """AI3 CI 出口：同步执行链（服务端 Playwright 路径）。

    - wait=1：同步等执行完成（CI 场景——curl/流水线直接拿结果）
    - HTTP 200=整体 pass；409=有步骤 fail/error（CI 退出码语义：
      `curl -f` 或 status_code 判定即得非零）
    - confirm_side_effect 默认 true（CI 授权由调用方持有——与 executor
      auto=1 同语义；显式 false 走 C1 shadow 门控）
    - 失败摘要走 webhook（WEBHOOK_URL 配置时）——复用既有通道
    """
    if not db.get(Chain, chain_id):
        raise HTTPException(404, "chain not found")
    if not wait:
        # 异步形态：后台任务执行（结果经 GET /chains/{id}/runs 查——
        # P2 补执行历史表；当前先只支持同步，CI 是主场景）
        raise HTTPException(422, "当前仅支持 wait=1（同步执行）")
    from app.replay.chain_runner import run_chain_server
    result = await run_chain_server(db, chain_id, confirm_side_effect)
    # webhook 失败摘要（fire-and-forget；无 WEBHOOK_URL 静默跳过）
    if result.get("status") != "pass":
        try:
            from app.integrations.webhook import notify
            import json as _json
            await notify("SkillLens 链执行失败",
                         f"链 #{chain_id}：{result.get('pass_count', 0)}/"
                         f"{result.get('total', 0)} 步通过\n"
                         + _json.dumps(result.get("steps", []), ensure_ascii=False)[:500])
        except Exception:
            pass  # webhook 失败不影响 CI 判定
    if result.get("status") != "pass":
        raise HTTPException(409, result)
    return result
