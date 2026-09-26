"""S18 T1：夜间开发计划（dev_plan）生成。

宪法边界：LLM 只做结构化——把需求文本结构化为字段变更清单
（purpose=dev_plan，落 llm_call_log）；回查（verify_dev_plan）与
已知表单提取（known_form_codes）全确定性。生成一律落 draft
（C1 延伸：计划不执行，confirm 是独立人工门控，T2）。
"""
import re

from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.learning.skill import parse_llm_skill
from app.models import DevPlan, RawEvent, Skill

# 设计器基础字段类型白名单（v1）——LLM 提议的 field_type 必须在此集合内
FIELD_TYPES = {"文本输入框", "数值", "日期时间", "单选", "多选"}

# key 规则：小写拼音/英文，无空格
KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# 骨架签名 URL 中的 formCode=xxx（v1 已知表单来源：skill 骨架签名匹配）
FORM_CODE_RE = re.compile(r"formCode=([^&|,]+)")


def build_prompt(requirement_text: str, target_form: str) -> str:
    """需求文本 + 目标表单 → 结构化 prompt（变更清单，op 只允许 add_field）。"""
    lines = [
        "你在分析一个企业软件的表单设计需求，请把它结构化为字段变更清单。",
        f"目标表单 formCode: {target_form}",
        f"需求: {requirement_text}",
        f"字段类型白名单（field_type 只允许以下值）: {'、'.join(sorted(FIELD_TYPES))}",
        "变更 op 只允许 add_field（v1 只支持加字段）。",
        "key 规则：小写拼音或英文、无空格（如 jinjilianxidianhua）；"
        "label 用中文业务名。",
        '只返回 JSON，不要任何其他文字: {"changes": ['
        '{"op": "add_field", "field_type": "文本输入框", '
        '"label": "中文字段名", "key": "pinyin_key"}]}',
    ]
    return "\n".join(lines)


def known_form_codes(db: Session) -> set[str]:
    """已知表单集合（v1 双源）：
    ①skill 骨架签名中的 formCode=xxx——真实骨架的 API 模板经 split_url
    已剥离 query，此源常为空，保留作防御；
    ②raw_event 导航事件的页面 URL（payload.url 含 formCode=xxx）——
    系统观察过的页面即已知表单（更符合"见过即知"语义）。"""
    codes: set[str] = set()
    for (skeleton,) in db.query(Skill.skeleton).all():
        for step in skeleton or []:
            if not isinstance(step, dict):
                continue
            m = FORM_CODE_RE.search(step.get("signature", ""))
            if m:
                codes.add(m.group(1))
    for (payload,) in db.query(RawEvent.payload).filter(
            RawEvent.kind == "navigation").all():
        m = FORM_CODE_RE.search(str((payload or {}).get("url", "")))
        if m:
            codes.add(m.group(1))
    return codes


def verify_dev_plan(proposal: dict, target_form: str,
                    known_forms: set[str]) -> tuple[bool, str]:
    """确定性回查：target_form 必须在已知表单集合；changes 非空列表；
    每项 op=add_field、field_type 在白名单、label 非空、key 合法。"""
    if target_form not in known_forms:
        return False, (f"target_form {target_form} 未在任何 skill 骨架中出现"
                       "（未知表单，回查失败）")
    changes = proposal.get("changes")
    if not isinstance(changes, list) or not changes:
        return False, "changes 必须是非空列表"
    for i, ch in enumerate(changes):
        if not isinstance(ch, dict):
            return False, f"changes[{i}] 必须是对象"
        if ch.get("op") != "add_field":
            return False, (f"changes[{i}].op 只允许 add_field"
                           f"（得到 {ch.get('op')!r}）")
        if ch.get("field_type") not in FIELD_TYPES:
            return False, (f"changes[{i}].field_type {ch.get('field_type')!r} "
                           f"不在字段类型白名单 {sorted(FIELD_TYPES)}")
        if not str(ch.get("label") or "").strip():
            return False, f"changes[{i}].label 必须非空（中文业务名）"
        if not KEY_RE.match(str(ch.get("key") or "")):
            return False, (f"changes[{i}].key 必须匹配 ^[a-z][a-z0-9_]*$"
                           "（小写拼音/英文无空格）")
    return True, ""


def generate_dev_plan(db: Session, requirement_text: str,
                      target_form: str) -> DevPlan:
    """LLM 结构化 + 确定性回查 → 落库 draft。回查失败→draft+notes
    （人工看 notes 修订——与 expected_delta 同模式）。"""
    result = complete(db, "dev_plan", build_prompt(requirement_text, target_form))
    proposal = parse_llm_skill(result.text)
    changes: list = []
    notes = ""
    if proposal is None:
        notes = "LLM 响应无法解析为 JSON"
    else:
        raw = proposal.get("changes")
        changes = raw if isinstance(raw, list) else []
        ok, why = verify_dev_plan(proposal, target_form, known_form_codes(db))
        if not ok:
            notes = why
    row = DevPlan(requirement_text=requirement_text, target_form=target_form,
                  changes=changes, status="draft", notes=notes)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
