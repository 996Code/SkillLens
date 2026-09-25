import json
import re

from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.models import DiscoveredFeature, ExpectedDelta

ALLOWED_TYPES = {"ui_action", "api_add", "api_status"}
MAX_CHANGES = 20


def build_prompt(requirement_text: str) -> str:
    lines = [
        "你在把一条软件需求结构化为预期变更清单（Expected Delta）。",
        "类型限定三种：ui_action（UI 按钮/标签/文案变化，value 写成如'保存按钮改名为提交'），"
        "api_add（新增或调用的 API，value 写成模板路径如 /codeBack/formConfig/saveFormConfig），"
        "api_status（API 响应状态或顶层 code 的预期，value 写成如 /x/y -> 200）。",
        f"需求：{requirement_text}",
        '只返回 JSON，不要任何其他文字: {"feature": "PascalCase英文特征名", '
        '"changes": [{"type": "...", "value": "..."}]}',
    ]
    return "\n".join(lines)


def parse_delta(text: str) -> dict | None:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def verify_delta(changes: list) -> tuple[bool, str]:
    if not isinstance(changes, list) or not changes:
        return False, "changes 必须是非空数组"
    if len(changes) > MAX_CHANGES:
        return False, f"changes 超过 {MAX_CHANGES} 条"
    for c in changes:
        if not isinstance(c, dict):
            return False, "changes 元素必须是对象"
        if c.get("type") not in ALLOWED_TYPES:
            return False, f"未知类型 {c.get('type')}"
        if not str(c.get("value") or "").strip():
            return False, "value 不能为空"
    return True, ""


def generate_expected_delta(db: Session, requirement_text: str,
                            requirement_id: str) -> ExpectedDelta:
    result = complete(db, "expected_delta", build_prompt(requirement_text))
    proposal = parse_delta(result.text)
    changes, feature, notes = [], "", ""
    if proposal is None:
        notes = "LLM 响应无法解析为 JSON"
    else:
        feature = str(proposal.get("feature") or "")[:100]
        changes = proposal.get("changes") or []
        ok, why = verify_delta(changes)
        if not ok:
            notes = why  # changes 保留原样供人工修订
    row = ExpectedDelta(requirement_id=requirement_id, version="v1",
                        requirement_text=requirement_text,
                        feature=feature, changes=changes, status="draft", notes=notes)
    db.add(row); db.commit(); db.refresh(row)
    return row


def link_discoveries(db: Session, delta: ExpectedDelta) -> int:
    """S12 N2 先验对齐：confirmed delta 的 changes 与 discovered_feature 匹配 → linked。

    匹配规则（全确定性，不调 LLM）：
    - api_add：与 api_template 精确匹配；
    - ui_action：与纯 UI 发现行（api_template 为空）的 anchor_label 子串匹配，
      任一方向包含即命中（"保存" ⊂ "保存按钮改名为提交"，反之亦然）。
    只处理 status="new" 的行（已 linked/dismissed 的不动）。返回链接行数。
    """
    linked = 0
    for c in delta.changes or []:
        ctype = c.get("type")
        value = str(c.get("value") or "")
        if not value:
            continue
        if ctype == "api_add":
            rows = db.query(DiscoveredFeature).filter(
                DiscoveredFeature.api_template == value,
                DiscoveredFeature.status == "new",
            ).all()
        elif ctype == "ui_action":
            rows = [
                r for r in db.query(DiscoveredFeature).filter(
                    DiscoveredFeature.api_template.is_(None),
                    DiscoveredFeature.status == "new",
                ).all()
                if r.anchor_label and (r.anchor_label in value or value in r.anchor_label)
            ]
        else:
            continue
        for r in rows:
            r.status = "linked"
            r.linked_delta_id = delta.id
            linked += 1
    if linked:
        db.commit()
    return linked
