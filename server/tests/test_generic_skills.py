"""S17 Task 3/4：通用能力层（generic_skill）归纳/晋升/映射 API 测试。

FakeProvider 铁律：LLM_API_KEY 置空 + LLM_FAKE_RESPONSE 脚本化响应。
系统区分 v1：骨架 API 模板首段（/codeBack* vs /api*）。
"""
import json

import pytest


async def _make_skill(client, monkeypatch, name, url, label="保存"):
    """造 1 个 skill：input+click+network 单窗；url 首段决定"系统"API 前缀。
    两 session 输入值不同（变量需跨 session 不同才被收录为 input_variable）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": name, "description": "d"}))
    sids = []
    for value in ("v1", "v2"):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        events = [
            {"seq": 0, "ts": 0, "kind": "navigation",
             "payload": {"type": "page-load", "url": "http://t/f"}},
            {"seq": 1, "ts": 100, "kind": "action",
             "payload": {"type": "input", "name": "请输入", "value": value}},
            {"seq": 2, "ts": 200, "kind": "action",
             "payload": {"type": "click", "target": {"label": label}}},
            {"seq": 3, "ts": 260, "kind": "network",
             "payload": {"method": "POST", "url": url, "status": 200,
                         "reqBody": "{}", "resBody": '{"code":200}'}},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        sids.append(sid)
    aid = (await client.post("/api/v1/align",
                            json={"session_ids": sids})).json()["alignment_id"]
    return (await client.post(f"/api/v1/alignments/{aid}/induce")).json()


def _proposal(a_id, b_id):
    return json.dumps({
        "name": "FillAndSubmit",
        "description": "跨系统填写并提交表单",
        "slots_schema": [
            {"slot": "submit_label", "description": "提交按钮的 label",
             "examples": {str(a_id): "保存", str(b_id): "搜索"}},
            {"slot": "input_field", "description": "输入框变量名",
             "examples": {str(a_id): "请输入"}},
        ],
    })


async def test_induce_generic_fields(client, monkeypatch):
    """T3：induce 落库字段齐——name/status=candidate/slots_schema/
    source_skill_ids/evidence_refs（骨架步数+变量名）；LLM 调用落 llm_call_log（C3）。"""
    a = await _make_skill(client, monkeypatch, "SaveForm",
                          "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "ExecuteSearch",
                          "/api/web/search", label="搜索")
    monkeypatch.setenv("LLM_FAKE_RESPONSE", _proposal(a["id"], b["id"]))

    resp = await client.post("/api/v1/generic-skills/induce",
                             json={"skill_ids": [a["id"], b["id"]]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "FillAndSubmit"
    assert body["description"] == "跨系统填写并提交表单"
    assert body["status"] == "candidate"          # 回查通过也仍是 candidate（晋升独立）
    assert body["notes"] == ""
    assert body["source_skill_ids"] == [a["id"], b["id"]]
    assert [s["slot"] for s in body["slots_schema"]] == ["submit_label", "input_field"]
    refs = {r["skill_id"]: r for r in body["evidence_refs"]}
    assert set(refs) == {a["id"], b["id"]}
    assert refs[a["id"]]["skeleton_steps"] >= 1
    assert "请输入" in refs[a["id"]]["variables"]

    from app.db import SessionLocal
    from app.models import LlmCallLog
    db = SessionLocal()
    try:
        n = db.query(LlmCallLog).filter(
            LlmCallLog.purpose == "generic_skill_induction").count()
        assert n == 1                                 # C3：归纳调用落库
    finally:
        db.close()

    rows = (await client.get("/api/v1/generic-skills")).json()
    assert [r["id"] for r in rows] == [body["id"]]
    detail = (await client.get(f"/api/v1/generic-skills/{body['id']}")).json()
    assert detail["name"] == "FillAndSubmit"
    assert detail["source_skill_ids"] == [a["id"], b["id"]]


async def test_induce_requires_two_skills(client, monkeypatch):
    """T3：skill_ids <2 → 422（通用能力必须跨源归纳）。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    resp = await client.post("/api/v1/generic-skills/induce",
                             json={"skill_ids": [a["id"]]})
    assert resp.status_code == 422
    resp = await client.post("/api/v1/generic-skills/induce",
                             json={"skill_ids": []})
    assert resp.status_code == 422


async def test_induce_verify_failure_candidate_notes(client, monkeypatch):
    """T3：确定性回查失败（examples 值不在源 skill 骨架/变量/断言中）
    → 仍落库但 status=candidate + notes 记失败原因。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "ExecuteSearch",
                          "/api/web/search", label="搜索")
    monkeypatch.setenv("LLM_FAKE_RESPONSE", json.dumps({
        "name": "FillAndSubmit", "description": "d",
        "slots_schema": [
            {"slot": "submit_label", "description": "提交按钮",
             "examples": {str(a["id"]): "根本不存在的值"}},
        ],
    }))
    body = (await client.post("/api/v1/generic-skills/induce",
                              json={"skill_ids": [a["id"], b["id"]]})).json()
    assert body["status"] == "candidate"
    assert "回查" in body["notes"]


async def test_induce_bad_name_candidate_notes(client, monkeypatch):
    """T3：name 非 PascalCase → candidate + notes 记原因（复用 skill.py 校验）。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "ExecuteSearch",
                          "/api/web/search", label="搜索")
    monkeypatch.setenv("LLM_FAKE_RESPONSE", json.dumps({
        "name": "fill and submit", "description": "d", "slots_schema": [],
    }))
    body = (await client.post("/api/v1/generic-skills/induce",
                              json={"skill_ids": [a["id"], b["id"]]})).json()
    assert body["status"] == "candidate"
    assert "PascalCase" in body["notes"]


async def test_induce_missing_skill_404(client, monkeypatch):
    """T3：skill_ids 含不存在的 id → 404。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    resp = await client.post("/api/v1/generic-skills/induce",
                             json={"skill_ids": [a["id"], 99999]})
    assert resp.status_code == 404


async def test_induce_superseded_skill_409(client, monkeypatch):
    """T3：superseded 源 skill → 409（不可作为归纳源）。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "ExecuteSearch",
                          "/api/web/search", label="搜索")
    # re-induce a 的 alignment → 旧行 superseded
    old_id = a["id"]
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveFormV2", "description": "d"}))
    await client.post(f"/api/v1/alignments/{a['alignment_id']}/induce")
    resp = await client.post("/api/v1/generic-skills/induce",
                             json={"skill_ids": [old_id, b["id"]]})
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# Task 4：晋升纪律 + 槽位映射
# ---------------------------------------------------------------------------

def _add_replay_run(skill_id, status):
    """直插 replay_run（带断言结果）——promote 校验的数据源。"""
    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    try:
        db.add(ReplayRun(skill_id=skill_id, mode="execute", status=status,
                         plan={"steps": []}, executed=[],
                         assertion_results=[{"passed": status == "pass"}]))
        db.commit()
    finally:
        db.close()


async def _induce_generic(client, monkeypatch, a, b):
    monkeypatch.setenv("LLM_FAKE_RESPONSE", _proposal(a["id"], b["id"]))
    return (await client.post("/api/v1/generic-skills/induce",
                              json={"skill_ids": [a["id"], b["id"]]})).json()


async def test_promote_two_systems_both_pass_learned(client, monkeypatch):
    """T4：双系统（/codeBack vs /api）+ 各源回放 PASS → learned。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "ExecuteSearch",
                          "/api/web/search", label="搜索")
    generic = await _induce_generic(client, monkeypatch, a, b)
    _add_replay_run(a["id"], "pass")
    _add_replay_run(b["id"], "pass")

    resp = await client.post(f"/api/v1/generic-skills/{generic['id']}/promote")
    assert resp.status_code == 200
    assert resp.json()["status"] == "learned"
    detail = (await client.get(f"/api/v1/generic-skills/{generic['id']}")).json()
    assert detail["status"] == "learned"          # 落库持久化


async def test_promote_single_system_409(client, monkeypatch):
    """T4：全部源 skill 同一 API 前缀（单系统）→ 409 带原因。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "SaveForm2", "/codeBack/other/save")
    # 单系统场景两 skill label 同为"保存"——提案示例须匹配实际骨架（过回查），
    # 才能到达 promote 的单系统检查（S17 纪律：回查失败先拦）
    monkeypatch.setenv("LLM_FAKE_RESPONSE", json.dumps({
        "name": "FillAndSubmit", "description": "d",
        "slots_schema": [
            {"slot": "submit_label", "description": "提交按钮",
             "examples": {str(a["id"]): "保存", str(b["id"]): "保存"}},
        ]}))
    generic = (await client.post("/api/v1/generic-skills/induce",
                                 json={"skill_ids": [a["id"], b["id"]]})).json()
    _add_replay_run(a["id"], "pass")
    _add_replay_run(b["id"], "pass")

    resp = await client.post(f"/api/v1/generic-skills/{generic['id']}/promote")
    assert resp.status_code == 409
    assert "系统" in resp.json()["detail"]


async def test_promote_missing_pass_run_409(client, monkeypatch):
    """T4：源 skill 无带断言结果的回放记录 → 409 带原因。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "ExecuteSearch",
                          "/api/web/search", label="搜索")
    generic = await _induce_generic(client, monkeypatch, a, b)
    _add_replay_run(a["id"], "pass")              # b 无回放记录

    resp = await client.post(f"/api/v1/generic-skills/{generic['id']}/promote")
    assert resp.status_code == 409
    assert "回放" in resp.json()["detail"]


async def test_promote_fail_run_409(client, monkeypatch):
    """T4：源 skill 最近回放 fail → 409 带原因。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "ExecuteSearch",
                          "/api/web/search", label="搜索")
    generic = await _induce_generic(client, monkeypatch, a, b)
    _add_replay_run(a["id"], "pass")
    _add_replay_run(b["id"], "fail")

    resp = await client.post(f"/api/v1/generic-skills/{generic['id']}/promote")
    assert resp.status_code == 409
    assert "fail" in resp.json()["detail"]


async def test_promote_generic_404(client):
    resp = await client.post("/api/v1/generic-skills/9999/promote")
    assert resp.status_code == 404


async def test_map_complete(client, monkeypatch):
    """T4：目标 skill 骨架/变量填满全部槽位 → complete=true + mapping。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "ExecuteSearch",
                          "/api/web/search", label="搜索")
    generic = await _induce_generic(client, monkeypatch, a, b)
    target = await _make_skill(client, monkeypatch, "SaveFormOther",
                                "/codeBack/other/save")

    resp = await client.post(f"/api/v1/generic-skills/{generic['id']}/map",
                             json={"target_skill_id": target["id"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["complete"] is True
    assert body["gaps"] == []
    assert body["mapping"]["submit_label"] == "保存"   # 目标骨架 click:保存 命中
    assert body["mapping"]["input_field"] == "请输入"  # 目标输入变量命中


async def test_map_incomplete_reports_gaps(client, monkeypatch):
    """T4：目标 skill 无输入变量 → 基础流缺口 + 槽位缺口，complete=false（200 不 409）。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "ExecuteSearch",
                          "/api/web/search", label="搜索")
    generic = await _induce_generic(client, monkeypatch, a, b)
    # 目标：无 input 事件 → 无输入变量
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "NoInputFlow", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 1, "ts": 260, "kind": "network",
         "payload": {"method": "POST", "url": "/codeBack/x/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align",
                             json={"session_ids": [sid, sid]})).json()["alignment_id"]
    target = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()

    resp = await client.post(f"/api/v1/generic-skills/{generic['id']}/map",
                             json={"target_skill_id": target["id"]})
    assert resp.status_code == 200                  # 映射是探测不是断言
    body = resp.json()
    assert body["complete"] is False
    assert any("输入变量" in g for g in body["gaps"])
    assert any("input_field" in g for g in body["gaps"])


async def test_map_target_404(client, monkeypatch):
    """T4：generic 或目标 skill 不存在 → 404。"""
    a = await _make_skill(client, monkeypatch, "SaveForm", "/codeBack/formConfig/save")
    b = await _make_skill(client, monkeypatch, "ExecuteSearch",
                          "/api/web/search", label="搜索")
    generic = await _induce_generic(client, monkeypatch, a, b)
    resp = await client.post(f"/api/v1/generic-skills/{generic['id']}/map",
                             json={"target_skill_id": 99999})
    assert resp.status_code == 404
    resp = await client.post("/api/v1/generic-skills/9999/map",
                             json={"target_skill_id": a["id"]})
    assert resp.status_code == 404
