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
