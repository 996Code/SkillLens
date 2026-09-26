"""S18 T1/T2：夜间开发计划（dev_plan）生成 + confirm 门控 API 测试。

FakeProvider 铁律：LLM_API_KEY 置空 + LLM_FAKE_RESPONSE 脚本化响应。
已知表单集合：直插含 formCode=xxx 骨架签名的 skill（known_form_codes
从所有 skill 骨架签名正则提取）。
"""
import json

import pytest


def _add_form_skill(form_code: str) -> None:
    """直插 1 个 skill：骨架签名 URL 含 formCode=xxx（known_form_codes 数据源）。"""
    from app.db import SessionLocal
    from app.models import Skill
    db = SessionLocal()
    try:
        db.add(Skill(
            alignment_id=1, name="FormFlow", description="表单流", status="learned",
            skeleton=[{"signature": "click:表单设计器|GET:/codeBack/formConfig/"
                                   f"getFormConfigByCode?formCode={form_code}"}],
            param_variables=[], input_variables=[], confidence=0.5, evidence_count=1))
        db.commit()
    finally:
        db.close()


_GOOD_CHANGES = [{"op": "add_field", "field_type": "文本输入框",
                  "label": "紧急联系电话", "key": "jinjilianxidianhua"}]


async def _generate(client, monkeypatch, changes=None, raw=None,
                    target_form="qingjiashenqing",
                    requirement="请假申请表单增加紧急联系电话字段"):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    if raw is None:
        raw = json.dumps({"changes": changes if changes is not None else _GOOD_CHANGES})
    monkeypatch.setenv("LLM_FAKE_RESPONSE", raw)
    return await client.post("/api/v1/dev-plans",
                             json={"requirement_text": requirement,
                                   "target_form": target_form})


async def test_generate_dev_plan_fields(client, monkeypatch):
    """T1：生成落库字段齐——changes/status=draft/notes 空；LLM 调用落
    llm_call_log purpose=dev_plan（C3）；列表倒序 + 详情。"""
    _add_form_skill("qingjiashenqing")
    r = await _generate(client, monkeypatch)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert body["notes"] == ""
    assert body["target_form"] == "qingjiashenqing"
    assert body["changes"] == _GOOD_CHANGES

    from app.db import SessionLocal
    from app.models import DevPlan, LlmCallLog
    db = SessionLocal()
    try:
        n = db.query(LlmCallLog).filter(LlmCallLog.purpose == "dev_plan").count()
        assert n == 1                                 # C3：结构化调用落库
        row = db.get(DevPlan, body["id"])
        assert row.requirement_text.startswith("请假申请")
        assert row.execution_log is None              # 执行器 T3 才写
        assert row.reviewed_by == ""
        assert row.created_at is not None
    finally:
        db.close()

    rows = (await client.get("/api/v1/dev-plans")).json()
    assert [x["id"] for x in rows] == [body["id"]]
    detail = (await client.get(f"/api/v1/dev-plans/{body['id']}")).json()
    assert detail["changes"] == _GOOD_CHANGES
    assert detail["status"] == "draft"


async def test_generate_bad_op_stays_draft_with_notes(client, monkeypatch):
    """T1：LLM 给坏 op（非 add_field）→ 仍落库 draft + notes 记原因。"""
    _add_form_skill("qingjiashenqing")
    r = await _generate(client, monkeypatch,
                        changes=[{"op": "delete_field", "field_type": "文本输入框",
                                  "label": "x", "key": "x"}])
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert "add_field" in body["notes"]


async def test_generate_bad_key_stays_draft_with_notes(client, monkeypatch):
    """T1：key 非法（中文/含空格/大写）→ draft + notes 记 key 规则。"""
    _add_form_skill("qingjiashenqing")
    r = await _generate(client, monkeypatch,
                        changes=[{"op": "add_field", "field_type": "文本输入框",
                                  "label": "紧急联系电话", "key": "紧急电话"}])
    body = r.json()
    assert body["status"] == "draft"
    assert "key" in body["notes"]


async def test_generate_bad_field_type_stays_draft_with_notes(client, monkeypatch):
    """T1：field_type 不在白名单 → draft + notes。"""
    _add_form_skill("qingjiashenqing")
    r = await _generate(client, monkeypatch,
                        changes=[{"op": "add_field", "field_type": "文件上传",
                                  "label": "附件", "key": "fujian"}])
    body = r.json()
    assert body["status"] == "draft"
    assert "field_type" in body["notes"] or "白名单" in body["notes"]


async def test_generate_unknown_target_form_notes(client, monkeypatch):
    """T1：target_form 不在任何 skill 骨架中（未知表单）→ draft + notes 记。"""
    _add_form_skill("qingjiashenqing")
    r = await _generate(client, monkeypatch, target_form="bu_cun_zai_de_biao_dan")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert "target_form" in body["notes"] or "未知表单" in body["notes"]


async def test_generate_unparseable_response_notes(client, monkeypatch):
    """T1：LLM 响应非 JSON → draft + notes 记无法解析（复用解析模式）。"""
    _add_form_skill("qingjiashenqing")
    r = await _generate(client, monkeypatch, raw="垃圾输出非 JSON")
    body = r.json()
    assert body["status"] == "draft"
    assert "无法解析" in body["notes"]


async def test_generate_empty_changes_notes(client, monkeypatch):
    """T1：changes 空列表 → 回查失败 draft + notes。"""
    _add_form_skill("qingjiashenqing")
    r = await _generate(client, monkeypatch, changes=[])
    body = r.json()
    assert body["status"] == "draft"
    assert "changes" in body["notes"]


async def test_get_dev_plan_404(client):
    resp = await client.get("/api/v1/dev-plans/99999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Task 2：confirm 门控（C1 延伸：draft 计划不可执行）
# ---------------------------------------------------------------------------

async def _make_plan(client, monkeypatch):
    _add_form_skill("qingjiashenqing")
    r = await _generate(client, monkeypatch)
    assert r.status_code == 201
    return r.json()


async def test_confirm_flow_and_repeat_409(client, monkeypatch):
    """T2：confirm → confirmed + reviewed_by 落库；重复 confirm 409。"""
    plan = await _make_plan(client, monkeypatch)
    rc = await client.post(f"/api/v1/dev-plans/{plan['id']}/confirm",
                           json={"reviewed_by": "tester"})
    assert rc.status_code == 200
    assert rc.json()["status"] == "confirmed"
    assert rc.json()["reviewed_by"] == "tester"
    detail = (await client.get(f"/api/v1/dev-plans/{plan['id']}")).json()
    assert detail["status"] == "confirmed"          # 落库持久化
    assert detail["reviewed_by"] == "tester"

    again = await client.post(f"/api/v1/dev-plans/{plan['id']}/confirm",
                              json={"reviewed_by": "x"})
    assert again.status_code == 409


async def test_confirm_missing_404(client):
    resp = await client.post("/api/v1/dev-plans/99999/confirm",
                             json={"reviewed_by": "t"})
    assert resp.status_code == 404


async def test_execute_draft_409(client, monkeypatch):
    """T2：draft 计划执行 → 409（C1 延伸门控：计划未确认，不可执行）。"""
    plan = await _make_plan(client, monkeypatch)
    resp = await client.post(f"/api/v1/dev-plans/{plan['id']}/execute")
    assert resp.status_code == 409
    assert "未确认" in resp.json()["detail"]


async def test_execute_confirmed_runs_executor(client, monkeypatch):
    """T3：confirmed 计划执行 → 真实执行器（测试环境无浏览器目标→error 收敛，
    C3：execution_log 落库）。"""
    plan = await _make_plan(client, monkeypatch)
    await client.post(f"/api/v1/dev-plans/{plan['id']}/confirm",
                      json={"reviewed_by": "tester"})
    resp = await client.post(f"/api/v1/dev-plans/{plan['id']}/execute")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in ("executed", "error")
    assert isinstance(body["execution_log"], list)


async def test_execute_missing_404(client):
    resp = await client.post("/api/v1/dev-plans/99999/execute")
    assert resp.status_code == 404


async def test_known_form_codes_extracts_from_skeletons(client):
    """T1：known_form_codes 从所有 skill 骨架签名提取 formCode=xxx 集合。"""
    from app.db import SessionLocal
    from app.learning.devplan import known_form_codes
    db = SessionLocal()
    try:
        assert known_form_codes(db) == set()          # 空库 → 空集合
    finally:
        db.close()
    _add_form_skill("qingjiashenqing")
    _add_form_skill("baoxiaoshenqing")
    db = SessionLocal()
    try:
        assert known_form_codes(db) == {"qingjiashenqing", "baoxiaoshenqing"}
    finally:
        db.close()


def test_compile_steps_validation():
    """T3 纯函数：变更清单 → 步骤序列；非法 op/空清单拒绝。"""
    from app.agents.dev_executor import compile_steps
    steps = compile_steps([{"op": "add_field", "field_type": "文本输入框",
                             "label": "紧急联系电话", "key": "jinjidianhua"}])
    assert steps == [{"action": "add_field", "field_type": "文本输入框",
                      "label": "紧急联系电话", "key": "jinjidianhua"}]
    import pytest
    with pytest.raises(ValueError):
        compile_steps([{"op": "delete_field", "field_type": "x"}])
    with pytest.raises(ValueError):
        compile_steps([])
