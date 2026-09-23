from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alignment, FieldChange, OutcomeAssertion, SemanticAction, Skill


def generate_assertions(db: Session, skill_id: int) -> list[OutcomeAssertion]:
    skill = db.get(Skill, skill_id)
    alignment = db.get(Alignment, skill.alignment_id)
    rows: list[tuple] = []
    # Skill 的证据范围是骨架步：只遍历 skeleton 各步 session_window_seqs
    # 指向的 semantic_action（精确到 session_id + window_seq），
    # 单侧 session 独有的非骨架窗口（v1 演示噪音）不得生成断言。
    for step in alignment.skeleton or []:
        for sid, window_seq in (step.get("session_window_seqs") or {}).items():
            action = db.execute(
                select(SemanticAction).where(
                    SemanticAction.session_id == sid,
                    SemanticAction.window_seq == window_seq,
                )
            ).scalar_one_or_none()
            if action is None:
                continue
            for call in action.api_calls or []:
                rows.append(("api_status", call["template"], 3,
                             {"api_template": call["template"], "expect_status": call.get("status")}))
            for sig in action.state_signals or []:
                rows.append(("state_signal", sig["api"], 3,
                             {"api_template": sig["api"], "field": sig["field"],
                              "expect_value": sig["value"]}))
    # FieldChange 保持按 session 全量（层 2 是存在性语义，与骨架无关）
    for sid in alignment.session_ids:
        changes = db.execute(
            select(FieldChange).where(FieldChange.session_id == sid)
        ).scalars().all()
        for fc in changes:
            for ch in fc.changes:
                rows.append(("field_change", fc.api_template, 2,
                             {"api_template": fc.api_template, "field": ch["field"],
                              "before": ch["before"], "after": ch["after"]}))

    # 按 (kind, api_template, field) 去重（跨 session 重复的同类断言合并）
    seen: dict[tuple, tuple] = {}
    for kind, tpl, layer, payload in rows:
        seen.setdefault((kind, tpl, payload.get("field", "")), (kind, tpl, layer, payload))

    db.query(OutcomeAssertion).filter(OutcomeAssertion.skill_id == skill_id).delete()
    written = []
    for kind, tpl, layer, payload in seen.values():
        row = OutcomeAssertion(skill_id=skill_id, layer=layer, kind=kind,
                               api_template=tpl, payload=payload)
        db.add(row)
        written.append(row)
    db.commit()
    return written


def verify_against_session(db: Session, assertion_id: int) -> dict:
    a = db.get(OutcomeAssertion, assertion_id)
    skill = db.get(Skill, a.skill_id)
    alignment = db.get(Alignment, skill.alignment_id)
    p = a.payload
    failed: list[str] = []
    for sid in alignment.session_ids:
        ok = _check_one(db, sid, a.kind, p)
        if not ok:
            failed.append(sid)
    return {"passed": not failed, "sessions_checked": len(alignment.session_ids),
            "failed_sessions": failed}


def _check_one(db: Session, sid: str, kind: str, p: dict) -> bool:
    if kind == "api_status":
        actions = db.execute(select(SemanticAction).where(SemanticAction.session_id == sid)).scalars().all()
        statuses = [c.get("status") for act in actions for c in (act.api_calls or [])
                    if c.get("template") == p["api_template"]]
        return bool(statuses) and all(s == p["expect_status"] for s in statuses)
    if kind == "state_signal":
        actions = db.execute(select(SemanticAction).where(SemanticAction.session_id == sid)).scalars().all()
        values = [s["value"] for act in actions for s in (act.state_signals or [])
                  if s["api"] == p["api_template"] and s["field"] == p["field"]]
        return bool(values) and all(v == p["expect_value"] for v in values)
    if kind == "field_change":
        fcs = db.execute(select(FieldChange).where(FieldChange.session_id == sid)).scalars().all()
        # before/after 是证据值：可能含输入变量（如 note=n111/n222），跨 session 天然不同，
        # 不能作为恒等条件；层 2 回放断言的语义是"该模板上该字段发生了变化"（存在性）。
        for fc in fcs:
            if fc.api_template != p["api_template"]:
                continue
            for ch in fc.changes:
                if ch["field"] == p["field"]:
                    return True
        return False
    return False
