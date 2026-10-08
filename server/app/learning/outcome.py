import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alignment, FieldChange, OutcomeAssertion, SemanticAction, Skill

logger = logging.getLogger("skilllens")


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
        # 空 label 无法定位字段（框架无语义元素），生成断言必误判——跳过
        if not label:
            continue
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
                # S43-4：查询型调用不生成断言——ERPNext reportview/search 等
                # RPC 虽走 POST 但语义是列表轮询/读取，与流程无因果（URL
                # 直达回放时不出现），observed None 判 fail 是假阴性；业务
                # 结果由真写方法+状态信号判定
                # 评审#7：畸形条目（非 dict/缺 template）跳过并记录（C3
                # 可见不吞），不得 KeyError
                if not isinstance(call, dict):
                    logger.warning("generate_assertions: skip malformed api_call %r", call)
                    continue
                t = call.get("template") or ""
                if not t:
                    logger.warning("generate_assertions: api_call missing template: %r", call)
                    continue
                if any(k in t for k in ("reportview", "search_link", "search_widget",
                                        "get_count", "list_view", "get_list")):
                    continue
                if (call.get("method") or "GET").upper() == "GET":
                    continue
                rows.append(("api_status", t, 3,
                             {"api_template": t, "expect_status": call.get("status")}))
            for sig in action.state_signals or []:
                if (not isinstance(sig, dict) or not sig.get("api")
                        or sig.get("field") is None or "value" not in sig):
                    logger.warning("generate_assertions: skip malformed state_signal %r", sig)
                    continue
                payload = {"api_template": sig["api"], "field": sig["field"],
                           "expect_value": sig["value"]}
                # S42：GET /{id} 行读取是行上下文（回放命中行≠录制行，
                # 行属性期望值漂移是定位语义的必然，非回归）→ 记录不判定
                if (sig.get("method") or "GET").upper() == "GET" and "{id}" in sig["api"]:
                    payload["context"] = True
                rows.append(("state_signal", sig["api"], 3, payload))
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
            for ch in fc.changes or []:
                # 评审#7：changes 可能含人工修订的畸形条目（expected.py
                # 原样保留）——非 dict/缺 field 或 before/after 证据键的
                # 无法构成断言，跳过并记录（C3 可见不吞），不得 KeyError
                if not isinstance(ch, dict) or not ch.get("field") \
                        or "before" not in ch or "after" not in ch:
                    logger.warning("generate_assertions: skip malformed change %r", ch)
                    continue
                # _truncated 是截断标记行而非业务字段变化，不得生成断言
                # （否则污染 C2 基线锚的 assertion_count/pass_rate）
                if ch["field"] == "_truncated":
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
    # 评审#7：payload 缺键（人工修订/旧数据）→ verify 判 False（可见失败），
    # 不得 KeyError 把回验打成 500
    p = p if isinstance(p, dict) else {}
    if kind == "api_status":
        tpl = p.get("api_template")
        if tpl is None:
            return False
        actions = db.execute(select(SemanticAction).where(SemanticAction.session_id == sid)).scalars().all()
        statuses = [c.get("status") for act in actions for c in (act.api_calls or [])
                    if isinstance(c, dict) and c.get("template") == tpl]
        return bool(statuses) and all(s == p.get("expect_status") for s in statuses)
    if kind == "state_signal":
        tpl = p.get("api_template")
        field = p.get("field")
        if tpl is None or field is None:
            return False
        actions = db.execute(select(SemanticAction).where(SemanticAction.session_id == sid)).scalars().all()
        values = [s.get("value") for act in actions for s in (act.state_signals or [])
                  if isinstance(s, dict) and s.get("api") == tpl and s.get("field") == field]
        return bool(values) and all(v == p.get("expect_value") for v in values)
    if kind == "ui_text":
        label = p.get("label")
        if label is None:
            return False
        # 层 2 存在性语义：session 任一语义动作窗的快照差集里该 label 发生了变化即过
        # （与 field_change 同口径：before/after 是证据值，跨 session 天然可不同）
        actions = db.execute(select(SemanticAction).where(SemanticAction.session_id == sid)).scalars().all()
        for act in actions:
            b_map = {f.get("label"): f.get("value")
                     for f in ((act.state_before or {}).get("forms") or [])
                     if isinstance(f, dict)}
            a_map = {f.get("label"): f.get("value")
                     for f in ((act.state_after or {}).get("forms") or [])
                     if isinstance(f, dict)}
            if label in b_map and label in a_map and b_map[label] != a_map[label]:
                return True
        return False
    if kind == "field_change":
        tpl = p.get("api_template")
        field = p.get("field")
        if tpl is None or field is None:
            return False
        fcs = db.execute(select(FieldChange).where(FieldChange.session_id == sid)).scalars().all()
        # before/after 是证据值：可能含输入变量（如 note=n111/n222），跨 session 天然不同，
        # 不能作为恒等条件；层 2 回放断言的语义是"该模板上该字段发生了变化"（存在性）。
        for fc in fcs:
            if fc.api_template != tpl:
                continue
            for ch in fc.changes or []:
                if isinstance(ch, dict) and ch.get("field") == field:
                    return True
        return False
    return False
