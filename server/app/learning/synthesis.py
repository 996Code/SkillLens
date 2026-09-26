"""S19 T1：流程生成（synth_flow）——证据收集 + LLM 目标分解 + 确定性回查。

宪法边界：LLM 只做目标分解（把 goal 编排为步骤序列，purpose=flow_synthesis，
落 llm_call_log）；证据收集（collect_evidence）与回查（verify_steps）全
确定性——每步 target 必须能在已知证据集合中找到，LLM 幻觉流程不进执行。
生成一律落 proposed（回查失败也落库供人工看，notes 记原因）。
"""
from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.learning.skill import parse_llm_skill
from app.models import Alignment, RawEvent, Skill, SynthFlow

# 步骤 kind 白名单（与回放通道的 goto/input/click 对齐）
STEP_KINDS = {"goto", "input", "click"}


def _signature_parts(signature: str) -> tuple[str, str]:
    """'click:保存|GET:/api/x' → ('click:保存', 'GET:/api/x')；无 | 时 API 段为空。"""
    action, _, api_part = signature.partition("|")
    return action, api_part


def _api_templates(skeleton: list) -> set[str]:
    """骨架签名 | 后段的 API 模板路径集合（'GET:/api/x' → '/api/x'）。"""
    templates: set[str] = set()
    for step in skeleton or []:
        _, api_part = _signature_parts(step.get("signature", ""))
        for seg in api_part.split(","):
            seg = seg.strip()
            if ":" in seg:
                tpl = seg.split(":", 1)[1].strip()
                if tpl.startswith("/"):
                    templates.add(tpl)
    return templates


def _click_anchors(skeleton: list) -> set[str]:
    """骨架签名 action 段的 click 锚点 label 集合（'click:保存' → '保存'）。"""
    anchors: set[str] = set()
    for step in skeleton or []:
        action, _ = _signature_parts(step.get("signature", ""))
        if action.startswith("click:"):
            label = action[len("click:"):].strip()
            if label:
                anchors.add(label)
    return anchors


def _session_pages(db: Session, alignment_id) -> set[str]:
    """skill 的 alignment 首会话 navigation 事件 URL 集合（回放计划 URL 同源）。"""
    alignment = db.get(Alignment, alignment_id)
    if alignment is None or not alignment.session_ids:
        return set()
    ref_sid = alignment.session_ids[0]
    pages: set[str] = set()
    for (payload,) in db.query(RawEvent.payload).filter(
            RawEvent.session_id == ref_sid,
            RawEvent.kind == "navigation").all():
        url = (payload or {}).get("url", "")
        if url:
            pages.add(url)
    return pages


def collect_evidence(db: Session, system_hint: str) -> dict:
    """收集该系统的已知证据（全部非 superseded skill）：
    anchors（click 锚点 label）/ variables（输入变量名）/ pages（alignment
    首会话 navigation URL）/ api_templates（骨架签名 API 模板路径）/
    skill_ids（贡献证据的 skill）。

    system_hint 过滤：skill 的 api_templates 前缀匹配 system_hint（如
    "/api"、"/codeBack"）才收——anchors/variables/pages 跟随匹配的 skill
    （跨系统证据不得混入同一流程）。system_hint 为空时不过滤（全量）。
    """
    evidence = {"anchors": set(), "variables": set(), "pages": set(),
                "api_templates": set(), "skill_ids": set()}
    skills = db.query(Skill).filter(Skill.status != "superseded").all()
    for s in skills:
        templates = _api_templates(s.skeleton)
        if system_hint and not any(t.startswith(system_hint) for t in templates):
            continue
        evidence["anchors"] |= _click_anchors(s.skeleton)
        evidence["variables"] |= {v.get("name") for v in s.input_variables or []
                                  if v.get("name")}
        evidence["api_templates"] |= templates
        evidence["skill_ids"].add(s.id)
        evidence["pages"] |= _session_pages(db, s.alignment_id)
    return evidence


def build_prompt(goal: str, evidence: dict) -> str:
    """目标 + 证据集合 → 分解 prompt。每步 target 必须从证据集合中选：
    goto 用 pages 的 URL；input 用 variables；click 用 anchors。"""
    lines = [
        "你在分析一个企业软件中系统已学会的操作流程证据，"
        "请把用户目标分解为可执行的步骤序列（生成从未被演示过的新流程）。",
        f"用户目标: {goal}",
        "已知页面 URL（goto 步的 target 必须从中选择）:",
    ]
    lines += [f"  - {u}" for u in sorted(evidence["pages"])] or ["  （无）"]
    lines.append("已知输入变量名（input 步的 target 必须从中选择）:")
    lines += [f"  - {v}" for v in sorted(evidence["variables"])] or ["  （无）"]
    lines.append("已知可点击锚点 label（click 步的 target 必须从中选择）:")
    lines += [f"  - {a}" for a in sorted(evidence["anchors"])] or ["  （无）"]
    lines += [
        "步骤 kind 只允许 goto|input|click；input 步必须给 value（要填的值）。",
        '只返回 JSON，不要任何其他文字: {"steps": ['
        '{"kind": "goto", "target": "页面URL"}, '
        '{"kind": "input", "target": "变量名", "value": "填写值"}, '
        '{"kind": "click", "target": "锚点label"}]}',
    ]
    return "\n".join(lines)


def verify_steps(steps, evidence: dict) -> tuple[bool, str]:
    """确定性回查：steps 非空列表；每步 kind 白名单；goto.target 是某已知
    页面 URL 的子串；input.target 精确 ∈ variables；click.target 与某已知
    锚点互为子串。失败记 why（落 notes 供人工看）。"""
    if not isinstance(steps, list) or not steps:
        return False, "steps 必须是非空列表"
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return False, f"steps[{i}] 必须是对象"
        kind = step.get("kind")
        if kind not in STEP_KINDS:
            return False, (f"steps[{i}].kind 只允许 goto|input|click"
                           f"（得到 {kind!r}）")
        target = str(step.get("target") or "")
        if not target:
            return False, f"steps[{i}].target 必须非空"
        if kind == "goto":
            if not any(target in url for url in evidence["pages"]):
                return False, (f"steps[{i}] goto 目标 {target!r} 不在已知页面"
                               f" URL 中（回查失败）")
        elif kind == "input":
            if target not in evidence["variables"]:
                return False, (f"steps[{i}] input 目标 {target!r} 不在已知"
                               f"输入变量中（回查失败）")
        else:  # click
            if not any(target in a or a in target for a in evidence["anchors"]):
                return False, (f"steps[{i}] click 锚点 {target!r} 不在已知"
                               f"锚点中（回查失败）")
    return True, ""


def synth_flow(db: Session, goal: str, system_hint: str) -> SynthFlow:
    """LLM 目标分解 + 确定性回查 → 落库 proposed。回查失败 → notes 记原因
    仍落库（人工看 notes 修订——与 dev_plan 同模式）。evidence_refs 落
    证据快照（C3：提案可追溯）。"""
    evidence = collect_evidence(db, system_hint)
    result = complete(db, "flow_synthesis", build_prompt(goal, evidence))
    proposal = parse_llm_skill(result.text)
    steps: list = []
    notes = ""
    if proposal is None:
        notes = "LLM 响应无法解析为 JSON"
    else:
        raw = proposal.get("steps")
        steps = raw if isinstance(raw, list) else []
        ok, why = verify_steps(steps, evidence)
        if not ok:
            notes = why
    evidence_refs = {key: sorted(evidence[key]) for key in evidence}
    row = SynthFlow(goal=goal, system_hint=system_hint, steps=steps,
                    status="proposed", notes=notes,
                    evidence_refs=evidence_refs)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
