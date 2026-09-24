import json


async def _post(client, text, rid="req-1"):
    return await client.post("/api/v1/expected-deltas",
                             json={"requirement_id": rid, "requirement_text": text})


async def test_generate_draft_and_confirm(client, monkeypatch):
    fake = json.dumps({"feature": "RenameFormButton",
                       "changes": [{"type": "ui_action", "value": "保存按钮改名为提交"}]})
    monkeypatch.setenv("LLM_FAKE_RESPONSE", fake)
    r = await _post(client, "把保存按钮改名为提交")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft" and len(body["changes"]) == 1

    rc = await client.post(f"/api/v1/expected-deltas/{body['id']}/confirm",
                           json={"reviewed_by": "tester"})
    assert rc.json()["status"] == "confirmed"
    # 再次 confirm 返回 409
    resp = await client.post(f"/api/v1/expected-deltas/{body['id']}/confirm",
                             json={"reviewed_by": "x"})
    assert resp.status_code == 409


async def test_confirm_can_revise_changes(client, monkeypatch):
    """人工修订入口：confirm 时覆盖 changes——真实构造 Unexpected 的基础。"""
    monkeypatch.setenv("LLM_FAKE_RESPONSE", json.dumps(
        {"feature": "F", "changes": [{"type": "ui_action", "value": "A"}]}))
    body = (await _post(client, "需求")).json()
    revised = [{"type": "ui_action", "value": "A"},
               {"type": "api_add", "value": "/codeBack/formConfig/saveFormConfig"}]
    rc = await client.post(f"/api/v1/expected-deltas/{body['id']}/confirm",
                           json={"reviewed_by": "t", "changes": revised})
    assert rc.json()["status"] == "confirmed" and len(rc.json()["changes"]) == 2


async def test_generate_verify_failure_stores_draft_with_reason(client, monkeypatch):
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "垃圾输出非 JSON")
    body = (await _post(client, "需求")).json()
    assert body["status"] == "draft" and "无法解析" in body["notes"]


async def test_generate_non_dict_change_element_stays_draft(client, monkeypatch):
    """LLM 返回 changes 含非 dict 元素时不得 500，verify 失败走 draft+notes。"""
    monkeypatch.setenv("LLM_FAKE_RESPONSE", json.dumps(
        {"feature": "F", "changes": ["裸字符串"]}))
    r = await client.post("/api/v1/expected-deltas",
                           json={"requirement_id": "r1", "requirement_text": "需求"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft" and body["notes"]
