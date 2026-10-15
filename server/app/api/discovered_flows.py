"""AP3 discovery flow API: segment ambient sessions, human review gate."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import WRITE_GUARD
from app.db import SessionLocal
from app.models import (DiscoveredFlow, RawEvent, RecordingSession,
                         Scenario, Skill)

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _summary(row: DiscoveredFlow) -> dict:
    events = row.events or []
    return {
        "id": row.id, "session_id": row.session_id,
        "status": row.status, "discard_reason": row.discard_reason,
        "has_write": row.has_write, "skill_id": row.skill_id,
        "event_count": len(events),
        "created_at": row.created_at.isoformat(),
    }


# ---------- 归并建议（Jaccard 相似骨架——只建议不自动执行） ----------

MERGE_JACCARD_THRESHOLD = 0.5


def _flow_signatures(events: list[dict]) -> set[str]:
    """段事件 → 签名集（与技能骨架签名同构：click:label / input:name /
    METHOD:url）。"""
    sigs: set[str] = set()
    for e in events or []:
        p = e.get("payload") or {}
        if e.get("kind") == "action":
            if p.get("type") == "click":
                sigs.add(f"click:{(p.get('target') or {}).get('label', '')}")
            elif p.get("type") == "input":
                sigs.add(f"input:{p.get('name', '')}")
        elif e.get("kind") == "network":
            sigs.add(f"{p.get('method', '')}:{p.get('url', '')}")
    return {s for s in sigs if s and not s.endswith(":")}


def _skill_signatures(skeleton: list[dict]) -> set[str]:
    """骨架签名归一：窗口骨架的复合签名（click:确定|POST:/x）按 | 拆分
    ——与流事件的细粒度签名同构可比（真机实证：不拆 Jaccard=0.2 漏检）。"""
    out: set[str] = set()
    for st in skeleton or []:
        for part in str(st.get("signature") or "").split("|"):
            part = part.strip()
            if part:
                out.add(part)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _find_similar_skill(db: Session, events: list[dict],
                        system: str) -> tuple[int, str] | None:
    """同系统活跃技能中找 Jaccard 最高的（≥阈值）——归并建议。

    系统归一化：会话 target_system 可能是 adapter id（ruoyi）或系统标签
    （若依权限）——经 SYSTEM_ADAPTER 双向映射统一到标签比较。
    """
    from app.system import skill_systems, SYSTEM_ADAPTER
    flow_sigs = _flow_signatures(events)
    if not flow_sigs:
        return None
    # adapter id → 标签
    label_by_id = {v: k for k, v in SYSTEM_ADAPTER.items()}
    system_label = label_by_id.get(system, system)
    skills = db.query(Skill).filter(
        Skill.status.in_(("learned", "candidate"))).all()
    systems = skill_systems(db, [s.id for s in skills] or [0])
    best: tuple[float, int, str] | None = None
    for s in skills:
        if systems.get(s.id) != system_label:
            continue
        j = _jaccard(flow_sigs, _skill_signatures(s.skeleton or []))
        if j >= MERGE_JACCARD_THRESHOLD and (best is None or j > best[0]):
            best = (j, s.id, s.name)
    return (best[1], best[2]) if best else None


def _flow_with_suggestion(db: Session, row: DiscoveredFlow) -> dict:
    out = _summary(row)
    if row.status == "pending":
        src = db.get(RecordingSession, row.session_id)
        hit = _find_similar_skill(db, row.events or [],
                                  src.target_system if src else "")
        if hit:
            out["similar_skill_id"] = hit[0]
            out["similar_skill_name"] = hit[1]
    return out


@router.post("/sessions/{session_id}/segment", dependencies=WRITE_GUARD)
async def segment_session_endpoint(session_id: str,
                                    db: Session = Depends(get_db)) -> dict:
    """AP3：ambient 会话切分——过闸段进待发现；discard 段留痕（C3）。"""
    sess = db.get(RecordingSession, session_id)
    if not sess:
        raise HTTPException(404, "session not found")
    if sess.source != "ambient":
        raise HTTPException(422, "仅 ambient 会话可切分（显式录制本就是单任务）")
    # 幂等：已切分过的会话不重复
    if db.query(DiscoveredFlow).filter(
            DiscoveredFlow.session_id == session_id).count() > 0:
        raise HTTPException(409, "该会话已切分")

    from app.learning.segment import segment_session, GateConfig
    rows = db.execute(select(RawEvent).where(
        RawEvent.session_id == session_id)
        .order_by(RawEvent.ts, RawEvent.seq)).scalars().all()
    events = [{"seq": r.seq, "ts": r.ts, "kind": r.kind,
               "payload": r.payload or {}} for r in rows]
    segments = segment_session(events, GateConfig())

    flows = discarded = 0
    for seg in segments:
        row = DiscoveredFlow(
            session_id=session_id, events=seg["events"],
            has_write=seg.get("has_write", False),
            status="auto_discarded" if seg.get("discarded") else "pending",
            discard_reason=seg.get("discard_reason", ""))
        db.add(row)
        if seg.get("discarded"):
            discarded += 1
        else:
            flows += 1
    db.commit()
    return {"flows": flows, "discarded": discarded,
            "total_segments": len(segments)}


@router.get("/discovered-flows")
async def list_flows(status: str = Query(default=""),
                     db: Session = Depends(get_db)) -> list[dict]:
    q = db.query(DiscoveredFlow)
    if status:
        q = q.filter(DiscoveredFlow.status == status)
    return [_flow_with_suggestion(db, r) for r in q.order_by(
        DiscoveredFlow.id.desc()).limit(100).all()]


async def _confirm_flow(db: Session, flow: DiscoveredFlow) -> DiscoveredFlow:
    """确认：段事件复制成新会话 → 既有 process→align→induce 管道。"""
    # ① 新会话（ambient 源——C2 分轨延续）
    new_sid = str(uuid.uuid4())
    src = db.get(RecordingSession, flow.session_id)
    db.add(RecordingSession(id=new_sid, target_system=src.target_system if src else "",
                            note="发现流确认", source="ambient"))
    db.flush()
    for i, e in enumerate(flow.events or []):
        db.add(RawEvent(session_id=new_sid, seq=i, ts=e.get("ts", i),
                        page_id=e.get("page_id", ""), kind=e.get("kind", ""),
                        payload=e.get("payload") or {}))
    db.commit()

    # ② 既有管道：process → align → induce（LLM 命名）
    from app.ingestion.process import process_session, load_windows
    from app.ingestion.alignment import align_skeletons
    from app.ingestion.variables import param_variables, input_variables
    from app.learning.skill import induce_skill
    from app.models import Alignment

    process_session(db, new_sid)
    windows = load_windows(db, new_sid)
    aligned = align_skeletons([(new_sid, windows)])
    ev_rows = db.execute(select(RawEvent).where(
        RawEvent.session_id == new_sid).order_by(RawEvent.ts, RawEvent.seq)
    ).scalars().all()
    events_per_session = [(new_sid, [{"kind": r.kind, "payload": r.payload or {}}
                                      for r in ev_rows])]
    alignment = Alignment(
        session_ids=[new_sid], skeleton=aligned["skeleton"],
        param_variables=param_variables(aligned["skeleton"], [(new_sid, windows)]),
        input_variables=input_variables(events_per_session),
        window_params={}, buckets=aligned["buckets"])
    db.add(alignment)
    db.commit()
    db.refresh(alignment)

    skill = await induce_skill(db, alignment.id)
    flow.status = "confirmed"
    flow.skill_id = skill.id
    db.commit()
    db.refresh(flow)
    return flow


@router.post("/discovered-flows/{flow_id}/confirm", dependencies=WRITE_GUARD)
async def confirm_flow(flow_id: int, create_scenario: bool = False,
                       chain_similar: bool = False,
                       db: Session = Depends(get_db)) -> dict:
    """确认待发现流。

    - create_scenario=true：同步建单步场景（origin=learned）——AP 产出
      直接进 AR 主链可执行。
    - chain_similar=true：存在相似技能（Jaccard≥阈值）时组建链场景
      [相似技能, 新技能]（双录对照回归——归并建议的动作化）；
      无相似不凭空组链。
    """
    flow = db.get(DiscoveredFlow, flow_id)
    if not flow:
        raise HTTPException(404, "flow not found")
    if flow.status != "pending":
        raise HTTPException(409, f"流状态 {flow.status} 不可确认")
    try:
        flow = await _confirm_flow(db, flow)
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"确认失败：{str(e)[:200]}")
    out = _summary(flow)
    skill = db.get(Skill, flow.skill_id) if flow.skill_id else None
    out["skill_name"] = skill.name if skill else None
    if skill is not None:
        src = db.get(RecordingSession, flow.session_id)
        from app.system import skill_systems
        system = skill_systems(db, [skill.id]).get(skill.id, "")
        if chain_similar:
            # 组链动作化：相似技能在前+新技能在后（双录对照回归场景）
            hit = _find_similar_skill(db, flow.events or [],
                                      src.target_system if src else "")
            if hit:
                scenario = Scenario(
                    name=f"{db.get(Skill, hit[0]).name}+{skill.name}",
                    system=system or "未知系统",
                    steps=[{"skill_id": hit[0], "scenario_id": None,
                            "overrides": {}, "setup": False, "enabled": True},
                           {"skill_id": skill.id, "scenario_id": None,
                            "overrides": {}, "setup": False, "enabled": True}],
                    status="active", definition_version=1, origin="learned")
                db.add(scenario)
                db.commit()
                db.refresh(scenario)
                out["scenario_id"] = scenario.id
                out["scenario_origin"] = scenario.origin
                out["chained_with"] = hit[0]
        elif create_scenario:
            scenario = Scenario(
                name=skill.name, system=system or "未知系统",
                steps=[{"skill_id": skill.id, "scenario_id": None,
                        "overrides": {}, "setup": False, "enabled": True}],
                status="active", definition_version=1, origin="learned")
            db.add(scenario)
            db.commit()
            db.refresh(scenario)
            out["scenario_id"] = scenario.id
            out["scenario_origin"] = scenario.origin
    return out


@router.post("/discovered-flows/{flow_id}/discard", dependencies=WRITE_GUARD)
async def discard_flow(flow_id: int, db: Session = Depends(get_db)) -> dict:
    flow = db.get(DiscoveredFlow, flow_id)
    if not flow:
        raise HTTPException(404, "flow not found")
    if flow.status != "pending":
        raise HTTPException(409, f"流状态 {flow.status} 不可丢弃")
    flow.status = "discarded"
    flow.discard_reason = "user_discarded"
    db.commit()
    db.refresh(flow)
    return _summary(flow)
