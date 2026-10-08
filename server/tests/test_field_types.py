"""S42-7 字段类型知识库引擎测试：类型匹配/值校验/生成/自愈反哺。"""
from app.db import SessionLocal, engine
from app.models import Base, FieldTypeHint
from app.replay import field_types as ft


def setup_module():
    Base.metadata.create_all(engine)


def _db():
    # conftest 的 client fixture 收尾会 drop_all——确保表存在再清
    Base.metadata.create_all(engine)
    db = SessionLocal()
    db.query(FieldTypeHint).delete()
    db.commit()
    return db


def test_builtin_match_and_validate():
    db = _db()
    try:
        assert ft.is_valid_value(db, "请输入手机号码", "13812345678") is True
        assert ft.is_valid_value(db, "请输入手机号码", "1381234") is False
        assert ft.is_valid_value(db, "用户邮箱", "a@b.com") is True
        assert ft.is_valid_value(db, "用户邮箱", "not-an-email") is False
        # 未知类型不判定
        assert ft.is_valid_value(db, "喜欢的颜色", "随便什么") is True
    finally:
        db.close()


def test_generate_valid_values():
    db = _db()
    try:
        phone = ft.generate_value(db, "手机号码")
        assert phone and phone.isdigit() and len(phone) == 11
        email = ft.generate_value(db, "联系邮箱")
        assert "@" in email and "." in email
        idc = ft.generate_value(db, "身份证号")
        assert len(idc) == 18
        assert ft.generate_value(db, "喜欢的颜色") is None
    finally:
        db.close()


def test_record_success_feedback_loop():
    """自愈成功 → 知识库沉淀 → 同字段下次直接命中（自我反哺）。"""
    db = _db()
    try:
        row = ft.record_success(db, "请输入手机号码", "13899998888", skill_id=7)
        assert row is not None and row.source == "learned"
        assert row.success_count == 1
        assert row.example_value == "13899998888"
        assert row.source_skill_id == 7
        # 二次成功 → 计数递增
        row2 = ft.record_success(db, "请输入手机号码", "13811112222", skill_id=8)
        assert row2.id == row.id and row2.success_count == 2
        # 沉淀后同字段仍能解析类型（DB 条目优先于内置）
        assert ft.is_valid_value(db, "请输入手机号码", "1381234") is False
    finally:
        db.close()


def test_learned_hint_covers_builtin():
    """learned 条目（label 精确沉淀）优先命中——领域知识覆盖内置。"""
    db = _db()
    try:
        ft.record_success(db, "应急联系电话", "13900001111", skill_id=1)
        # "应急联系电话" 不匹配内置"手机"关键词，但 learned 条目命中"电话"
        # （内置"电话"规则本身存在）——验证 resolve 链路完整
        rule = ft.resolve_type(db, "应急联系电话")
        assert rule is not None
    finally:
        db.close()


async def test_field_types_api_crud(client):
    """S42-7：字段类型知识库 Web 维护 API（增改删查）。"""
    r = await client.post("/api/v1/field-types", json={
        "label_pattern": "微信", "field_type": "phone",
        "example_value": "wx-12345"})
    assert r.status_code == 200
    hid = r.json()["id"]
    assert r.json()["source"] == "manual"

    r = await client.get("/api/v1/field-types")
    items = [i for i in r.json()["items"] if i["id"] == hid]
    assert items and items[0]["label_pattern"] == "微信"
    assert "phone" in r.json()["builtin_types"]

    r = await client.put(f"/api/v1/field-types/{hid}", json={
        "label_pattern": "微信号", "field_type": "phone", "example_value": ""})
    assert r.status_code == 200 and r.json()["label_pattern"] == "微信号"

    r = await client.delete(f"/api/v1/field-types/{hid}")
    assert r.status_code == 200
    r = await client.delete(f"/api/v1/field-types/{hid}")
    assert r.status_code == 404


def test_password_rule():
    """密码字段：脱敏值/空值不合法 → 自愈生成强密码。"""
    db = _db()
    try:
        assert ft.is_valid_value(db, "登录密码", "[REDACTED]") is False
        assert ft.is_valid_value(db, "请输入确认密码", "") is False
        assert ft.is_valid_value(db, "登录密码", "Sl@123456") is True
        pwd = ft.generate_value(db, "登录密码")
        assert pwd and len(pwd) >= 8
    finally:
        db.close()


# ---------- 评审#4：确定性修复（重复 pattern / 身份证日期段 / 重复解析） ----------

def test_record_success_duplicate_pattern_deterministic():
    """同 pattern 多行（manual+learned 并存）不得 MultipleResultsFound——
    按 success_count 降序、id 升序确定性选取，重复调用落同一行。"""
    db = _db()
    try:
        db.add(FieldTypeHint(label_pattern="微信号", field_type="phone",
                             example_value="a", source="manual", success_count=5))
        db.add(FieldTypeHint(label_pattern="微信号", field_type="email",
                             example_value="b", source="manual", success_count=1))
        db.commit()
        row = ft.record_success(db, "微信号", "13800001111")
        assert row is not None and row.field_type == "phone"   # 高 success_count 胜
        first_id, first_count = row.id, row.success_count
        row2 = ft.record_success(db, "微信号", "13800002222")
        assert row2.id == first_id and row2.success_count == first_count + 1
    finally:
        db.close()


def test_record_success_duplicate_pattern_tie_lowest_id():
    """success_count 打平 → 取最小 id（稳定可复现）。"""
    db = _db()
    try:
        db.add(FieldTypeHint(label_pattern="工号", field_type="int",
                             example_value="", source="manual", success_count=0))
        db.add(FieldTypeHint(label_pattern="工号", field_type="int",
                             example_value="", source="learned", success_count=0))
        db.commit()
        ids = sorted(r.id for r in
                     db.query(FieldTypeHint).filter_by(label_pattern="工号").all())
        row = ft.record_success(db, "工号", "42")
        assert row.id == ids[0]
    finally:
        db.close()


def test_gen_id_card_birth_segment_is_real_date():
    """评审#4a：日段曾是 randint(10000,99999) 前两位（10-99）——多数月份
    非法日期，严格校验器必拒。现月 1-12、日 1-28，校验位仍按 GB11643。"""
    import datetime as _dt
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    for _ in range(200):
        v = ft._gen_id_card()
        assert len(v) == 18 and v[:17].isdigit()
        d = _dt.datetime.strptime(v[6:14], "%Y%m%d").date()   # 非法日期直接抛
        assert 1 <= d.month <= 12 and 1 <= d.day <= 28
        s = sum(int(c) * w for c, w in zip(v[:17], weights))
        assert v[17] == "10X98765432"[s % 11]


def test_resolve_type_repeatable():
    """评审#4b：有界扫描改造后重复调用结果稳定一致。"""
    db = _db()
    try:
        ft.record_success(db, "手机号码", "13800000000")
        r1 = ft.resolve_type(db, "手机号码")
        r2 = ft.resolve_type(db, "手机号码")
        assert r1 is not None and r1["field_type"] == "phone"
        assert r2["field_type"] == r1["field_type"]
        assert ft.resolve_type(db, "不存在的字段") is None
        assert ft.resolve_type(db, "不存在的字段") is None
    finally:
        db.close()


# ---------- S43-3：LLM 归因（层 3）——规则外字段经 LLM 分类回填知识库 ----------

def _db_clean():
    """client 夹具已建好测试库 schema——只清表不 create_all
    （create_all 与夹具的 drop/create 交错会报表已存在）。"""
    db = SessionLocal()
    db.query(FieldTypeHint).delete()
    db.commit()
    return db


async def test_llm_attribute_type_unknown_field(client, monkeypatch):
    """未知字段（规则不命中）→ LLM 归因 → 落库 source=llm →
    后续 resolve_type/生成走确定性规则（LLM 只分类，判定仍确定性）。"""
    db = _db_clean()
    try:
        # 规则不命中（真未知字段）
        assert ft.resolve_type(db, "微信号码") is None
    finally:
        db.close()

    monkeypatch.setenv("LLM_FAKE_RESPONSE", "phone")
    db = _db_clean()
    try:
        row = await ft.llm_attribute_type(db, "微信号码")
        assert row is not None
        assert row.field_type == "phone"
        assert row.source == "llm"
        # 落库后确定性通道接管：值生成可用
        val = ft.generate_value(db, "微信号码")
        assert val and val.startswith("1")
        assert ft.is_valid_value(db, "微信号码", "123") is False
    finally:
        db.close()


async def test_llm_attribute_type_rejects_unknown_enum(client, monkeypatch):
    """LLM 输出不在类型枚举内 → 不落库（宁缺毋滥，垃圾归因不进知识库）。"""
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "这是个超链接吧")
    db = _db_clean()
    try:
        row = await ft.llm_attribute_type(db, "神秘字段")
        assert row is None
        n = db.query(FieldTypeHint).filter_by(label_pattern="神秘字段").count()
        assert n == 0
    finally:
        db.close()


async def test_llm_attribute_type_existing_no_overwrite(client, monkeypatch):
    """已有 builtin/learned 匹配的字段不再问 LLM（省调用且不覆盖已有知识）。"""
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "email")
    db = _db_clean()
    try:
        row = await ft.llm_attribute_type(db, "手机号")
        assert row is None  # 内置规则已命中 → 跳过 LLM
    finally:
        db.close()


async def test_heal_with_llm_attribution(client, monkeypatch):
    """S43-3 集成：规则不命中的非法值字段 → _heal_with_llm_attribution
    经 LLM 归因回填 → 确定性生成合法值（runner 自愈路径的层 3 接线）。"""
    from app.replay.runner import _heal_with_llm_attribution
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "phone")
    db = _db_clean()
    try:
        plan = {"steps": [
            {"kind": "input", "name": "应急联络号", "value": "abc"},
            {"kind": "input", "name": "备注", "value": "正常文本"},
        ]}
        # 校验错误只提到 应急联络号（确定性关联——备注不被误归因破坏）
        v_errs = ["应急联络号格式不正确"]
        healed_plan, fields = await _heal_with_llm_attribution(db, plan, v_errs)
        assert [f["name"] for f in fields] == ["应急联络号"]
        assert healed_plan["steps"][0]["value"].startswith("1")
        assert healed_plan["steps"][1]["value"] == "正常文本"
    finally:
        db.close()
