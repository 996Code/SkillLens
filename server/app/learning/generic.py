"""S17 块 L：通用能力层（generic_skill）归纳/晋升/映射。

宪法边界：LLM 只做命名/结构化——induce 一次调用产出 name/description/
slots_schema（落 llm_call_log，purpose=generic_skill_induction）；
回查（verify_generic_proposal）/晋升（promote_generic）/映射（map_generic）
全确定性。归纳落库一律 candidate，晋升是独立确定性步骤（→ learned）。
"""
from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.learning.skill import PASCAL, parse_llm_skill
from app.models import GenericSkill, OutcomeAssertion, ReplayRun, Skill


def build_prompt(skills: list[Skill], assertion_texts: dict[int, str]) -> str:
    """各源 skill 的 name/description/骨架签名/变量名/断言摘要 → 归纳 prompt。"""
    lines = ["你在分析多个不同软件系统中被用户反复执行的操作流程，"
             "请归纳一个跨系统通用的能力模板（槽位=各系统中对应的可变部分）。"]
    for s in skills:
        lines.append(f"源 Skill #{s.id}: {s.name} - {s.description}")
        lines.append("  骨架签名:")
        for step in s.skeleton or []:
            lines.append(f"    - {step.get('signature', '')}")
        names = [v.get("name") for v in (s.input_variables or []) if v.get("name")]
        if names:
            lines.append(f"  输入变量: {', '.join(names)}")
        params = [v.get("param") for v in (s.param_variables or []) if v.get("param")]
        if params:
            lines.append(f"  API 参数变量: {', '.join(params)}")
        if assertion_texts.get(s.id):
            lines.append("  断言摘要:")
            for line in assertion_texts[s.id].splitlines():
                lines.append(f"    - {line}")
    lines.append(
        '只返回 JSON，不要任何其他文字: {"name": "PascalCase 英文名", '
        '"description": "一句话中文描述", "slots_schema": ['
        '{"slot": "槽位名", "description": "槽位含义", '
        '"examples": {"<源skill id>": "该 skill 中对应的值"}}]}')
    return "\n".join(lines)


def _assertion_texts(db: Session, skills: list[Skill]) -> dict[int, str]:
    """各源 skill 的断言摘要（kind:模板:字段），回查与 prompt 共用。"""
    out: dict[int, str] = {}
    for s in skills:
        rows = db.query(OutcomeAssertion).filter(
            OutcomeAssertion.skill_id == s.id).all()
        out[s.id] = "\n".join(
            f"{r.kind}:{r.api_template}:"
            f"{(r.payload or {}).get('field') or (r.payload or {}).get('label') or ''}"
            for r in rows)
    return out


def _skill_search_text(skill: Skill) -> str:
    """回查搜索面：骨架签名 + 输入变量名 + API 参数变量名。"""
    parts = [step.get("signature", "") for step in skill.skeleton or []]
    parts += [v.get("name") or "" for v in skill.input_variables or []]
    parts += [v.get("param") or "" for v in skill.param_variables or []]
    return "\n".join(p for p in parts if p)


def verify_generic_proposal(proposal: dict, skills: list[Skill],
                            assertion_texts: dict[int, str]) -> tuple[bool, str]:
    """确定性回查：name PascalCase；slots_schema 每个槽位的每个 examples 值
    必须能在对应源 skill 的骨架签名/变量名/断言 payload 中找到（子串匹配）。"""
    name = str(proposal.get("name") or "")
    if not PASCAL.match(name):
        return False, "name 必须是 PascalCase（首字母大写无空格）"
    if not str(proposal.get("description") or ""):
        return False, "description 必须非空"
    slots = proposal.get("slots_schema")
    if not isinstance(slots, list) or not slots:
        return False, "slots_schema 必须是非空列表"
    search = {s.id: _skill_search_text(s) + "\n" + assertion_texts.get(s.id, "")
              for s in skills}
    for slot in slots:
        if not isinstance(slot, dict) or not slot.get("slot"):
            return False, "每个槽位必须有 slot 名"
        examples = slot.get("examples") or {}
        if not examples:
            return False, f"槽位 {slot['slot']} 缺少 examples"
        for key, value in examples.items():
            try:
                sid = int(key)
            except (TypeError, ValueError):
                return False, (f"槽位 {slot['slot']} 的 examples 键 {key!r} "
                               f"不是合法 skill id")
            if sid not in search:
                return False, f"槽位 {slot['slot']} 引用了不存在的源 skill #{sid}"
            # 示例值可能是标量或列表（LLM 常把 API/断言聚成数组）——
            # 列表逐元素回查，任一元素找不到即失败
            items = value if isinstance(value, list) else [value]
            for item in items:
                if not item or str(item) not in search[sid]:
                    return False, (f"槽位 {slot['slot']} 的示例值 {item!r} 未在源 "
                                   f"skill #{sid} 的骨架/变量/断言中找到（回查失败）")
    return True, ""


def induce_generic(db: Session, skills: list[Skill]) -> GenericSkill:
    """从 ≥2 个源 skill 归纳通用模板。回查失败→candidate+notes；
    通过→仍 candidate（晋升 promote 是独立步骤）。全字段落库（C3）。"""
    assertion_texts = _assertion_texts(db, skills)
    result = complete(db, "generic_skill_induction",
                      build_prompt(skills, assertion_texts))
    proposal = parse_llm_skill(result.text)
    name, desc, slots, notes = "Candidate", "", [], ""
    if proposal is None:
        notes = "LLM 响应无法解析为 JSON"
    else:
        name = str(proposal.get("name") or "") or "Candidate"
        desc = str(proposal.get("description") or "")
        raw_slots = proposal.get("slots_schema")
        slots = raw_slots if isinstance(raw_slots, list) else []
        ok, why = verify_generic_proposal(proposal, skills, assertion_texts)
        if not ok:
            notes = why
    evidence_refs = []
    for s in skills:
        variables = [v.get("name") for v in (s.input_variables or []) if v.get("name")]
        variables += [v.get("param") for v in (s.param_variables or []) if v.get("param")]
        evidence_refs.append({"skill_id": s.id,
                               "skeleton_steps": len(s.skeleton or []),
                               "variables": variables})
    row = GenericSkill(name=name, description=desc, slots_schema=slots,
                       status="candidate",
                       source_skill_ids=[s.id for s in skills],
                       evidence_refs=evidence_refs, notes=notes)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# Task 4：晋升纪律 + 槽位映射（全确定性）
# ---------------------------------------------------------------------------

def api_prefixes(skill: Skill) -> set[str]:
    """系统区分 v1：骨架签名中 API 模板的首段（/codeBack* 与 /api* 等
    不同首段视为不同系统；target_system 字段化列入后续）。"""
    prefixes: set[str] = set()
    for step in skill.skeleton or []:
        for chunk in step.get("signature", "").split("|")[1:]:
            for part in chunk.split(","):
                tpl = part.split(":", 1)[1].strip() if ":" in part else part.strip()
                if tpl.startswith("/"):
                    first = tpl.strip("/").split("/")[0]
                    if first:
                        prefixes.add(first)
    return prefixes


def promote_generic(db: Session, generic: GenericSkill) -> tuple[bool, str]:
    """晋升纪律（确定性）：⓪归纳回查必须已通过（notes 含回查失败→不可晋升——
    LLM 幻觉被确定性回查抓住的 candidate 不许升 learned）；
    ①源 skill 覆盖 ≥2 个系统（API 前缀区分）；
    ②各源 skill 最近一次带断言结果的 replay_run status=pass。"""
    if "回查失败" in (generic.notes or ""):
        return False, "归纳回查未通过（LLM 产物含未证实引用），不可晋升——请重新归纳"
    skills = [s for s in (db.get(Skill, sid)
                          for sid in generic.source_skill_ids or []) if s]
    prefixes: set[str] = set()
    for s in skills:
        prefixes |= api_prefixes(s)
    if len(prefixes) < 2:
        return False, (f"源 skill 仅覆盖单一系统（API 前缀: {sorted(prefixes) or ['无']}），"
                       "晋升需绑定 ≥2 个不同系统")
    for s in skills:
        runs = db.query(ReplayRun).filter(ReplayRun.skill_id == s.id) \
            .order_by(ReplayRun.id.desc()).all()
        run = next((r for r in runs if r.assertion_results), None)
        if run is None:
            return False, f"源 skill #{s.id} 无带断言结果的回放记录（需回放 PASS 才可晋升）"
        if run.status != "pass":
            return False, (f"源 skill #{s.id} 最近一次回放 status={run.status}"
                           "（需 PASS 才可晋升）")
    return True, ""


def map_generic(generic: GenericSkill, target: Skill) -> dict:
    """槽位映射探测（确定性，200 不 409——映射是探测不是断言）。

    v1 简化：目标 skill 有 ≥1 输入变量且骨架含 click 步 = 可映射基础流；
    每个槽位先按 examples 值在目标骨架/变量中做子串匹配，匹配不到回退
    依次占用空闲输入变量；填不满 → complete=false + 缺口列表。
    """
    sig_text = "\n".join(step.get("signature", "") for step in target.skeleton or [])
    var_names = [v.get("name") for v in (target.input_variables or []) if v.get("name")]
    search_text = sig_text + "\n" + "\n".join(var_names)
    gaps: list[str] = []
    if not var_names:
        gaps.append("目标 skill 无输入变量（可映射基础流要求 ≥1 输入变量）")
    if "click:" not in sig_text:
        gaps.append("目标 skill 骨架无 click 步（可映射基础流要求含点击提交）")
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for slot in generic.slots_schema or []:
        name = str(slot.get("slot") or "")
        matched = ""
        for value in (slot.get("examples") or {}).values():
            if value and str(value) in search_text:
                matched = str(value)
                break
        if not matched:
            free = [n for n in var_names if n not in used]
            if free:
                matched = free[0]
                used.add(free[0])
        if matched:
            mapping[name] = matched
        else:
            gaps.append(f"槽位 {name} 无法在目标 skill 的骨架/变量中找到对应值")
    return {"mapping": mapping, "complete": not gaps, "gaps": gaps}
