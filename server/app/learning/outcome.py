from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alignment, FieldChange, OutcomeAssertion, SemanticAction, Skill


def _ui_text_rows(action: SemanticAction) -> list[tuple]:
    """从单个骨架窗的 state_before/state_after 提取 forms 差集。
    同 label 且 value 不同 → ("ui_text", "", 2, {label, before, after})。
    任一侧缺失（旧数据 NULL）无差集可言，返回空。"""
    before = action.state_before or {}
    after = action.state_after or {}
    b_map = {f.get("label"): f.get("value") for f in (before.get("forms") or [])}
    a_map = {f.get("label"): f.get("value") for f in (after.get("forms") or [])}
    out: list[tuple] = []
    for label in sorted(set(b_map) & set(a_map)):
        if b_map[label] != a_map[label]:
            out.append(("ui_text", "", 2,
                        {"label": label, "before": b_map[label], "after": a_map[label]}))
    return out


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
            # Sprint 8 T3：骨架窗 UI 状态差集 → ui_text 断言（层 2，reqBody 盲区证据）。
            # 只取骨架窗口的 state_before/after（与 api_status 同证据范围，
            # Sprint 3 fix1 语义：非骨架窗口的快照不得生成断言）。
            rows.extend(_ui_text_rows(action))
    # FieldChange 保持按 session 全量（层 2 是存在性语义，与骨架无关）
    for sid in alignment.session_ids:
        changes = db.execute(
            select(FieldChange).where(FieldChange.session_id == sid)
        ).scalars().all()
        for fc in changes:
            for ch in fc.changes:
                # _truncated 是截断标记行而非业务字段变化，不得生成断言
                # （否则污染 C2 基线锚的 assertion_count/pass_rate）
                if ch.get("field") == "_truncated":
                    continue
                rows.append(("field_change", fc.api_template, 2,
                             {"api_template": fc.api_template, "field": ch["field"],
                              "before": ch["before"], "after": ch["after"]}))

    # 按 (kind, api_template, field) 去重（跨 session 重复的同类断言合并）。
    # ui_text 无 template/field：template 为空串、field 位置用 label——
    # 不同 label 不碰撞、同 label 跨 session 仍合并（去重键仍生效）。
    seen: dict[tuple, tuple] = {}
    for kind, tpl, layer, payload in rows:
        field_key = payload.get("field") or payload.get("label") or ""
        seen.setdefault((kind, tpl, field_key), (kind, tpl, layer, payload))

    # 层4 历史成功样本是资产：重建断言前按签名快照计数，重建后回填
    # （与 evidence_edge/discovered_feature 的"不随重建清零"语义一致）。
    old_rows = db.query(OutcomeAssertion).filter(
        OutcomeAssertion.skill_id == skill_id).all()
    prior_counts: dict[tuple, int] = {}
    for r in old_rows:
        sig = (r.kind, r.api_template,
               (r.payload or {}).get("field") or (r.payload or {}).get("label") or "")
        prior_counts[sig] = r.evidence_count or 0

    db.query(OutcomeAssertion).filter(OutcomeAssertion.skill_id == skill_id).delete()
    written = []
    for kind, tpl, layer, payload in seen.values():
        field_key = payload.get("field") or payload.get("label") or ""
        sig = (kind, tpl, field_key)
        row = OutcomeAssertion(skill_id=skill_id, layer=layer, kind=kind,
                               api_template=tpl, payload=payload,
                               evidence_count=prior_counts.get(sig, 0))
        if row.evidence_count >= 3:
            row.payload = {**payload, "layer4_verified": True}
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
    if kind == "ui_text":
        # 层 2 存在性语义：session 任一语义动作窗的快照差集里该 label 发生了变化即过
        # （与 field_change 同口径：before/after 是证据值，跨 session 天然可不同）
        actions = db.execute(select(SemanticAction).where(SemanticAction.session_id == sid)).scalars().all()
        for act in actions:
            b_map = {f.get("label"): f.get("value")
                     for f in ((act.state_before or {}).get("forms") or [])}
            a_map = {f.get("label"): f.get("value")
                     for f in ((act.state_after or {}).get("forms") or [])}
            if p["label"] in b_map and p["label"] in a_map \
                    and b_map[p["label"]] != a_map[p["label"]]:
                return True
        return False
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
