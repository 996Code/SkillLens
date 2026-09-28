import json
import re

from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.learning.evidence import sync_evidence_edges
from app.models import Alignment, Skill, SkillStrategy

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


def _top_level_json_spans(text: str) -> list[str]:
    """提取顶层平衡 {...} 片段（字符串内的花括号不计；嵌套对象保持完整）。"""
    spans: list[str] = []
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append(text[start:i + 1])
                start = -1
    return spans


def parse_llm_skill(text: str) -> dict | None:
    """从 LLM 输出提取 JSON 提案（形状无关：skill 命名/dev_plan/flow/generic 共用）。

    S27 彩排发现：思维链模型会先输出散文、且可能重复 JSON 块——贪婪 `\{.*\}`
    跨块匹配非法，而 `\{[^{}]*\}` 又会拆碎嵌套对象。改为平衡括号扫描取全部
    **顶层**对象，从后往前取首个可解析的非空 dict（末块通常是最终定稿）。
    """
    for raw in reversed(_top_level_json_spans(text)):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data:
            return data
    return None


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
    # 空骨架（不同锚点流不归并的合法场景）→ 不调 LLM：无证据可命名，
    # 调用只会产生幻觉名（网易实测：空骨架被命名为无关业务名）
    if not alignment.skeleton:
        old = db.query(Skill).filter(Skill.alignment_id == alignment_id).all()
        for s in old:
            db.query(SkillStrategy).filter(SkillStrategy.skill_id == s.id).delete()
            db.query(OutcomeAssertion).filter(OutcomeAssertion.skill_id == s.id).delete()
        db.query(Skill).filter(Skill.alignment_id == alignment_id).delete()
        skill = Skill(
            alignment_id=alignment_id, name="EmptyFlow", description="",
            status="candidate", skeleton=[], param_variables=[],
            input_variables=alignment.input_variables, confidence=0.0,
            evidence_count=len(alignment.session_ids),
            notes="骨架为空（各会话锚点无公共步），无可归纳流程",
        )
        db.add(skill)
        db.commit()
        db.refresh(skill)
        return skill
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
    # S15 版本演化（v3 §29 不覆盖旧版本）：re-induce 不再删除旧 skill——旧行
    # status→"superseded" + superseded_by=新行 id（只取代当前活跃行，链式指向
    # 直接后继），新行 version=旧最大 version+1；断言/策略只写新行，旧行的
    # 断言/策略保留作历史（原"先删断言再删 skill"孤儿治理随之整体移除）。
    old_skills = db.query(Skill).filter(Skill.alignment_id == alignment_id).all()
    max_version = max((s.version or 1) for s in old_skills) if old_skills else 0
    skill = Skill(
        alignment_id=alignment_id, name=name, description=desc, status=status,
        skeleton=alignment.skeleton, param_variables=alignment.param_variables,
        input_variables=alignment.input_variables, confidence=confidence,
        evidence_count=len(alignment.session_ids), notes=notes,
        version=max_version + 1,
    )
    db.add(skill)
    db.flush()
    for old in old_skills:
        if old.status != "superseded":  # 已 superseded 的行保持原链指向不变
            old.status = "superseded"
            old.superseded_by = skill.id
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
