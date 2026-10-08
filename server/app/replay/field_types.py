"""S42-7 字段类型知识库引擎：字段语义 → 类型 → 合法值生成/校验。

表单 JS 校验拦截（点击提交但校验不过、无 API 请求）是回放的常见失败态。
本引擎按字段 label/名称匹配字段类型（DB 知识库优先、内置规则兜底），
生成合法值供自愈重试；成功后反哺知识库。

宪法约束：类型匹配与值生成全确定性（关键词包含 + 正则）。
S43-3 层 3：规则不命中的字段可经 LLM 归因（只做分类，输出必须落在
已知类型枚举内才落库 source=llm）——值生成/校验仍走确定性规则，
LLM 不参与判定。
"""
import random
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FieldTypeHint


def _gen_phone() -> str:
    return f"138{random.randint(10000000, 99999999)}"


def _gen_email() -> str:
    return f"sl{random.randint(1000, 9999)}@test.com"


def _gen_id_card() -> str:
    # 合法格式（校验位按 GB11643 算法生成）。评审#4a：生日段必须是真实
    # 日期——旧实现日段取 randint(10000,99999) 前两位（10-99），多数月份
    # 非法，严格校验器必拒。月 1-12、日 1-28（避开大小月/闰年边界）。
    body = (f"1101011990{random.randint(1, 12):02d}"
            f"{random.randint(1, 28):02d}{random.randint(0, 999):03d}")
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    codes = "10X98765432"
    s = sum(int(c) * w for c, w in zip(body, weights))
    return body + codes[s % 11]


def _gen_url() -> str:
    return f"https://example.com/{random.randint(100, 999)}"


def _gen_date() -> str:
    return f"1990-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"


def _gen_int() -> str:
    return str(random.randint(1, 100))


def _gen_password() -> str:
    return f"Sl@{random.randint(100000, 999999)}"


BUILTIN_RULES: list[dict] = [
    {"field_type": "phone", "label_pattern": "手机",
     "valid": lambda v: bool(re.fullmatch(r"1\d{10}", str(v))),
     "generate": _gen_phone},
    {"field_type": "phone", "label_pattern": "phone",
     "valid": lambda v: bool(re.fullmatch(r"1\d{10}", str(v))),
     "generate": _gen_phone},
    {"field_type": "phone", "label_pattern": "电话",
     "valid": lambda v: bool(re.fullmatch(r"\d{6,12}", str(v))),
     "generate": _gen_phone},
    {"field_type": "email", "label_pattern": "邮箱",
     "valid": lambda v: bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(v))),
     "generate": _gen_email},
    {"field_type": "email", "label_pattern": "email",
     "valid": lambda v: bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", str(v))),
     "generate": _gen_email},
    {"field_type": "id_card", "label_pattern": "身份证",
     "valid": lambda v: bool(re.fullmatch(r"\d{17}[\dXx]", str(v))),
     "generate": _gen_id_card},
    {"field_type": "url", "label_pattern": "网址",
     "valid": lambda v: str(v).startswith("http"),
     "generate": _gen_url},
    {"field_type": "url", "label_pattern": "url",
     "valid": lambda v: str(v).startswith("http"),
     "generate": _gen_url},
    {"field_type": "date", "label_pattern": "日期",
     "valid": lambda v: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v))),
     "generate": _gen_date},
    {"field_type": "date", "label_pattern": "生日",
     "valid": lambda v: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v))),
     "generate": _gen_date},
    {"field_type": "date", "label_pattern": "birthday",
     "valid": lambda v: bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v))),
     "generate": _gen_date},
    {"field_type": "int", "label_pattern": "排序",
     "valid": lambda v: bool(re.fullmatch(r"\d+", str(v))),
     "generate": _gen_int},
    {"field_type": "int", "label_pattern": "数量",
     "valid": lambda v: bool(re.fullmatch(r"\d+", str(v))),
     "generate": _gen_int},
    # 密码：采集侧脱敏（[REDACTED]）——回放填原值必被校验拦，
    # 视为不合法 → 自愈生成强密码
    {"field_type": "password", "label_pattern": "密码",
     "valid": lambda v: str(v) not in ("", "[REDACTED]") and len(str(v)) >= 6,
     "generate": _gen_password},
    {"field_type": "password", "label_pattern": "password",
     "valid": lambda v: str(v) not in ("", "[REDACTED]") and len(str(v)) >= 6,
     "generate": _gen_password},
]

_RULES_BY_TYPE: dict[str, dict] = {}
for _r in BUILTIN_RULES:
    _RULES_BY_TYPE.setdefault(_r["field_type"], _r)


def _match_rule(label: str) -> dict | None:
    low = str(label or "").lower()
    for r in BUILTIN_RULES:
        if r["label_pattern"].lower() in low:
            return r
    return None


def resolve_type(db: Session, label: str) -> dict | None:
    """字段 → 类型规则。DB 知识库（含 learned/manual，按 success_count
    优先）先于内置关键词规则——自愈沉淀的领域知识可覆盖内置。
    评审#4b：排序+有界扫描下推 SQL（success_count 降序、id 升序，
    limit 500）——库行规模=字段词表量级，上界防病态增长；自愈期
    逐字段调用不再全表重扫，且同数据同答案（确定性）。"""
    rows = db.execute(
        select(FieldTypeHint).where(FieldTypeHint.label_pattern.isnot(None))
        .order_by(FieldTypeHint.success_count.desc(), FieldTypeHint.id)
        .limit(500)
    ).scalars().all()
    low = str(label or "").lower()
    for row in rows:
        if row.label_pattern and row.label_pattern.lower() in low:
            base = _RULES_BY_TYPE.get(row.field_type)
            if base is not None:
                return base
    return _match_rule(label)


def is_valid_value(db: Session, label: str, value: str) -> bool:
    rule = resolve_type(db, label)
    if rule is None:
        return True  # 未知类型不判定（宁缺毋滥）
    return bool(rule["valid"](value))


def generate_value(db: Session, label: str) -> str | None:
    rule = resolve_type(db, label)
    if rule is None:
        return None
    return str(rule["generate"]())


def record_success(db: Session, label: str, value: str,
                   skill_id: int | None = None) -> FieldTypeHint | None:
    """自愈成功反哺：label → 类型 + 实例值沉淀/计数。

    label 取字段名（input 步的 name/label）；沉淀的是"这个字段这样填
    能过"的知识，下次同字段（或同 pattern 字段）直接命中。
    """
    rule = resolve_type(db, label)
    if rule is None:
        return None
    # 精确 label 已有 learned 条目 → 计数 + 更新实例值。
    # 评审#4：同 pattern 多行（manual/learned/llm 并存）时
    # scalar_one_or_none 会抛 MultipleResultsFound，被 run_replay 兜底
    # 捕获后把成功回放打成 error——取 success_count 最高、id 最小
    # （计数最高=最被验证的行继续累积；打平取最小 id，确定性可复现）
    row = db.execute(
        select(FieldTypeHint).where(FieldTypeHint.label_pattern == label)
        .order_by(FieldTypeHint.success_count.desc(), FieldTypeHint.id)
        .limit(1)
    ).scalars().first()
    if row is None:
        row = FieldTypeHint(label_pattern=label, field_type=rule["field_type"],
                            example_value=str(value)[:200], source="learned",
                            source_skill_id=skill_id, success_count=0)
        db.add(row)
    row.field_type = rule["field_type"]
    row.example_value = str(value)[:200]
    row.success_count = (row.success_count or 0) + 1
    db.commit()
    db.refresh(row)
    return row


# 类型枚举与内置规则的映射（LLM 归因只允许落这些类型——
# 落库后值生成/校验仍走确定性规则，垃圾输出不进知识库）
_LLM_ENUM = sorted(_RULES_BY_TYPE.keys())


async def llm_attribute_type(db: Session, label: str) -> FieldTypeHint | None:
    """S43-3 层 3：规则外字段的 LLM 归因。

    前置：resolve_type 不命中（builtin/learned 已覆盖的不再问，省调用
    且不覆盖已有知识）。LLM 输出须严格等于类型枚举之一，否则不落库
    （宁缺毋滥）。落库 source=llm、success_count=0（待自愈成功反哺
    计数后晋升可信度）。
    """
    if not label or resolve_type(db, label) is not None:
        return None
    from app.llm.gateway import acomplete
    prompt = (
        f"判断表单字段的类型。字段名：{label}\n"
        f"候选类型（只能从中选一个）：{', '.join(_LLM_ENUM)}\n"
        "如果都不合适输出 none。只输出类型名本身，不要任何解释。"
    )
    try:
        result = await acomplete(db, "field_type_attr", prompt)
    except Exception:
        return None
    text = (result.text or "").strip().strip('"').splitlines()[0].strip().lower()
    if text not in _LLM_ENUM:
        return None
    row = FieldTypeHint(label_pattern=str(label)[:200], field_type=text,
                        example_value="", source="llm", success_count=0)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
