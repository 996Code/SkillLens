import json
import re

from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.learning.evidence import sync_evidence_edges
from app.models import Alignment, OutcomeAssertion, Skill, SkillStrategy

PASCAL = re.compile(r"^[A-Z][A-Za-z0-9]*$")


def build_prompt(alignment: Alignment) -> str:
    lines = ["你在分析一个企业软件中被用户反复执行的操作流程。请为它命名。"]
    lines.append("流程骨架（每步一个签名）:")
    for step in alignment.skeleton:
        lines.append(f"  - {step['signature']}")
    if alignment.input_variables:
        names = ", ".join(v["name"] for v in alignment.input_variables)
        lines.append(f"输入变量: {names}")
    if alignment.param_variables:
        names = ", ".join(v["param"] for v in alignment.param_variables)
        lines.append(f"API 参数变量: {names}")
    lines.append('只返回 JSON，不要任何其他文字: {"name": "PascalCase 英文名", "description": "一句话中文描述"}')
    return "\n".join(lines)


def parse_llm_skill(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def verify_skill(proposal: dict, alignment: Alignment) -> tuple[bool, str]:
    name = str(proposal.get("name") or "")
    desc = str(proposal.get("description") or "")
    if not PASCAL.match(name):
        return False, "name 必须是 PascalCase（首字母大写无空格）"
    if not desc or len(desc) > 200:
        return False, "description 必须非空且 ≤200 字符"
    return True, ""


def _confidence(alignment: Alignment) -> float:
    api_steps = sum(1 for s in alignment.skeleton if "|" in s.get("signature", ""))
    total = max(len(alignment.skeleton), 1)
    has_vars = 1.0 if (alignment.param_variables or alignment.input_variables) else 0.0
    return round(api_steps / total * 0.6 + has_vars * 0.4, 2)


def induce_skill(db: Session, alignment_id: int) -> Skill:
    alignment = db.get(Alignment, alignment_id)
    result = complete(db, "skill_naming", build_prompt(alignment))
    proposal = parse_llm_skill(result.text)
    status, name, desc, notes = "candidate", "Candidate", "", ""
    if proposal is None:
        notes = "LLM 响应无法解析为 JSON"
    else:
        ok, why = verify_skill(proposal, alignment)
        if ok:
            status, name, desc = "learned", proposal["name"], proposal["description"]
        else:
            notes = why
    confidence = _confidence(alignment)
    # 先删旧 Skill 的断言再删 Skill：否则断言行 skill_id 悬空，verify 会 500（孤儿根治）
    old_skill_ids = [s.id for s in db.query(Skill).filter(Skill.alignment_id == alignment_id).all()]
    if old_skill_ids:
        db.query(OutcomeAssertion).filter(OutcomeAssertion.skill_id.in_(old_skill_ids)).delete(
            synchronize_session=False)
        db.query(SkillStrategy).filter(SkillStrategy.skill_id.in_(old_skill_ids)).delete(
            synchronize_session=False)
    db.query(Skill).filter(Skill.alignment_id == alignment_id).delete()
    skill = Skill(
        alignment_id=alignment_id, name=name, description=desc, status=status,
        skeleton=alignment.skeleton, param_variables=alignment.param_variables,
        input_variables=alignment.input_variables, confidence=confidence,
        evidence_count=len(alignment.session_ids), notes=notes,
    )
    db.add(skill)
    db.flush()
    # 多路径分桶落地：每桶一条策略（主桶亦记录），签名=桶内骨架序列
    for bucket in alignment.buckets or [{"sessions": alignment.session_ids,
                                         "skeleton": alignment.skeleton}]:
        sigs = "|".join(step.get("signature", "") for step in bucket.get("skeleton") or [])
        if not sigs:
            continue
        db.add(SkillStrategy(skill_id=skill.id, strategy_signature=sigs,
                             skeleton=bucket.get("skeleton"),
                             evidence_count=len(bucket.get("sessions") or [])))
    # 证据图边同步（全局资产，幂等累加，re-induce 不清）
    sync_evidence_edges(db, alignment)
    db.commit()
    db.refresh(skill)
    return skill
