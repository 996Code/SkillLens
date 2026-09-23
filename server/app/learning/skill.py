import json
import re

from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.models import Alignment, Skill

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
    db.query(Skill).filter(Skill.alignment_id == alignment_id).delete()
    skill = Skill(
        alignment_id=alignment_id, name=name, description=desc, status=status,
        skeleton=alignment.skeleton, param_variables=alignment.param_variables,
        input_variables=alignment.input_variables, confidence=confidence,
        evidence_count=len(alignment.session_ids), notes=notes,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill
