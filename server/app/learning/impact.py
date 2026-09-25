"""S13 F2：Impact Analysis（纯查询）——变更集沿 evidence_edge 反查受影响 skill。

边语义（见 learning/evidence.py）：
- session → action：type="contains"（src=session_id，dst=action label）
- action → api：type="calls"（src=action label，dst=api 模板）

遍历：
- api_templates：dst=模板 → type=calls → src=action（反查 action）；
- anchor_labels：直接匹配 action（contains 边的 dst 或 src）；
- action → skill：骨架签名（'click:保存|POST:/x'）的 action 段含该 action。

输出：{affected_skills: [{skill_id, name, confidence, paths}],
       total_skills, unchanged_count}——paths 形如
       "api:POST:/x → action:click:保存 → skill:7" / "anchor:click:保存 → skill:7"。
"""
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import EvidenceEdge, Skill


def _skeleton_actions(skill: Skill) -> set[str]:
    """骨架签名取 action 段（'click:保存|POST:/x' → 'click:保存'）。"""
    return {(step.get("signature") or "").split("|", 1)[0]
            for step in skill.skeleton or []}


def _template_to_actions(db: Session, api_templates: list[str]) -> dict[str, set[str]]:
    """api 模板 → action 集合（calls 边反查：dst=模板 → src=action）。"""
    mapping: dict[str, set[str]] = {t: set() for t in api_templates}
    # evidence_edge 的 calls 边 dst 带方法前缀（"POST:/x"），输入可能是裸模板
    # （"/x"）——双形态匹配（同 discovery.is_known 语义）。
    variants = set(api_templates)
    variant_to_input = {t: t for t in api_templates}
    for t in api_templates:
        for prefix in ("GET:", "POST:", "PUT:", "DELETE:", "PATCH:"):
            v = prefix + t
            variants.add(v)
            variant_to_input[v] = t
    if not api_templates:
        return mapping
    rows = db.query(EvidenceEdge).filter(
        EvidenceEdge.type == "calls",
        EvidenceEdge.dst.in_(variants)).all()
    for row in rows:
        # 边 dst 可能是裸模板或方法前缀形态——归并回输入模板键
        mapping.setdefault(variant_to_input.get(row.dst, row.dst), set()).add(row.src)
    return mapping


def _anchor_to_actions(db: Session, anchor_labels: list[str]) -> dict[str, set[str]]:
    """锚点 label → action 集合（contains 边 dst 或 src 直接命中即视为有效 action）。"""
    mapping: dict[str, set[str]] = {a: set() for a in anchor_labels}
    if not anchor_labels:
        return mapping
    rows = db.query(EvidenceEdge).filter(
        EvidenceEdge.type == "contains",
        or_(EvidenceEdge.src.in_(anchor_labels),
            EvidenceEdge.dst.in_(anchor_labels))).all()
    for row in rows:
        for label in anchor_labels:
            if row.src == label or row.dst == label:
                mapping[label].add(label)
    return mapping


def analyze_impact(db: Session, api_templates: list[str],
                   anchor_labels: list[str]) -> dict:
    template_to_actions = _template_to_actions(db, api_templates or [])
    anchor_to_actions = _anchor_to_actions(db, anchor_labels or [])

    affected: list[dict] = []
    # 排除 superseded：夜间定向回归只回放当前活跃版本（旧版本保留作历史，不执行）
    skills = db.query(Skill).filter(
        Skill.status != "superseded").order_by(Skill.id).all()
    for skill in skills:
        sig_actions = _skeleton_actions(skill)
        paths: list[str] = []
        for template in api_templates or []:
            for action in sorted(template_to_actions.get(template) or ()):
                if action in sig_actions:
                    paths.append(f"api:{template} → action:{action} → skill:{skill.id}")
        for label in anchor_labels or []:
            if label in sig_actions and anchor_to_actions.get(label):
                paths.append(f"anchor:{label} → skill:{skill.id}")
        if paths:
            affected.append({"skill_id": skill.id, "name": skill.name,
                             "confidence": skill.confidence, "paths": paths})

    total = len(skills)
    return {"affected_skills": affected, "total_skills": total,
            "unchanged_count": total - len(affected)}
