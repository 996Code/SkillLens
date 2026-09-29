"""Task 1（S9 块C）：GET /api/v1/skills/{id}/card 聚合端点——骨架+变量+断言+最近 run 概要。"""
import json

from app.db import SessionLocal
from app.models import ReplayRun


async def _seed_skill(client, monkeypatch, llm_name="SaveForm"):
    """参考 test_baseline_api._seed_skill：两 session 输入值不同 → 有 input_variables。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": llm_name, "description": "d"}))
    sids = []
    for value in ("旧甲", "旧乙"):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        events = [
            {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load", "url": "http://t/f"}},
            {"seq": 1, "ts": 100, "kind": "action",
             "payload": {"type": "input", "name": "请输入", "value": value}},
            {"seq": 2, "ts": 200, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 3, "ts": 260, "kind": "network",
             "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                         "reqBody": "{}", "resBody": '{"code":200}'}},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        sids.append(sid)
    aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    return skill["id"]


def _add_replay_run(skill_id: int, assertion_results, mode="execute", status="execute") -> int:
    """直接落 replay_run 行（API 层测试不依赖回放浏览器链路）。"""
    db = SessionLocal()
    try:
        run = ReplayRun(skill_id=skill_id, mode=mode, status=status,
                        plan={"url": "http://t/f", "steps": []}, executed=[],
                        assertion_results=assertion_results)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


async def test_card_full_fields(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, None, mode="shadow", status="pass")   # 更早的 shadow run
    run_id = _add_replay_run(skill_id, [{"passed": True}, {"passed": False}])

    resp = await client.get(f"/api/v1/skills/{skill_id}/card")
    assert resp.status_code == 200
    card = resp.json()
    # S15：card 加 superseded_by（superseded 行前端提示用；活跃行为 None）
    assert set(card) == {"id", "name", "description", "status", "confidence",
                         "evidence_count", "alignment_id", "skeleton", "input_variables",
                         "param_variables", "assertions", "strategies", "last_run", "window_params",
                         "notes", "superseded_by"}
    assert card["superseded_by"] is None
    assert card["id"] == skill_id
    assert card["name"] == "SaveForm"
    assert card["status"] == "learned"
    assert card["confidence"] == 1.0            # api 步 0.6 + 有输入变量 0.4
    assert card["evidence_count"] == 2
    assert card["alignment_id"] > 0
    assert isinstance(card["skeleton"], list) and card["skeleton"]
    assert isinstance(card["input_variables"], list) and card["input_variables"]
    assert card["input_variables"][0]["name"] == "请输入"
    assert set(card["input_variables"][0]["values"].values()) == {"旧甲", "旧乙"}
    # skeleton 结构透传（align 端点同源），param_variables 同为列表
    align = (await client.get(f"/api/v1/alignments/{card['alignment_id']}")).json()
    assert card["skeleton"] == align["skeleton"]
    assert card["param_variables"] == align["param_variables"]
    # 断言行：id/kind/layer/payload
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    assert len(card["assertions"]) == len(rows)
    for a, r in zip(card["assertions"], rows):
        assert set(a) == {"id", "kind", "layer", "payload"}
        assert a["id"] == r["id"] and a["kind"] == r["kind"] and a["layer"] == r["layer"]
        assert a["payload"] == r["payload"]
    # last_run：取 id 倒序第一条（shadow 也算）
    assert card["last_run"] == {"id": run_id, "status": "execute", "mode": "execute",
                                "flaky": False, "ts": card["last_run"]["ts"]}
    # window_params 从 alignment 读
    assert card["window_params"] == {"idle_ms": 2000, "max_window_ms": 8000,
                                     "consistent": True}


async def test_card_without_run_last_run_null(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch, llm_name="NoRun")
    card = (await client.get(f"/api/v1/skills/{skill_id}/card")).json()
    assert card["last_run"] is None
    assert card["assertions"]   # 断言仍聚合


async def test_card_404(client):
    assert (await client.get("/api/v1/skills/99999/card")).status_code == 404


# ---------- S12 N4 层5：断言观测一致性端点 ----------

def _api_status_result(status, passed=True):
    """与 assert_eval.evaluate_assertions 输出同构的 api_status 结果行。
    模板用 templatize 后的 /a/{id}/save（种子 URL /a/1/save 的模板形态）。"""
    return {"kind": "api_status",
            "payload": {"api_template": "/a/{id}/save", "expect_status": 200},
            "observed_status": status, "passed": passed}


async def test_consistency_same_observed_across_runs(client, monkeypatch):
    """同 skill 两 run 观测相同 → consistent=true；ui_text 等无观测断言跳过。"""
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, [_api_status_result(200)])
    _add_replay_run(skill_id, [_api_status_result(200)])
    resp = await client.get(f"/api/v1/skills/{skill_id}/consistency")
    assert resp.status_code == 200
    body = resp.json()
    assert body["skill_id"] == skill_id
    assert body["runs"] == 2
    assert body["consistent"] is True
    assert body["inconsistent_count"] == 0
    # 只输出有观测的断言（api_status）；state_signal/field_change 无观测行 → 跳过
    assert [r["kind"] for r in body["assertions"]] == ["api_status"]
    row = body["assertions"][0]
    assert row["observed_values"] == [200, 200]
    assert row["consistent"] is True


async def test_consistency_different_observed_across_runs(client, monkeypatch):
    """两 run 观测不同（200 vs 500）→ consistent=false，inconsistent_count 计数。"""
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, [_api_status_result(200)])
    _add_replay_run(skill_id, [_api_status_result(500, passed=False)])
    body = (await client.get(f"/api/v1/skills/{skill_id}/consistency")).json()
    assert body["consistent"] is False
    assert body["inconsistent_count"] == 1
    row = body["assertions"][0]
    assert row["observed_values"] == [200, 500]
    assert row["consistent"] is False


async def test_consistency_no_runs_vacuously_consistent(client, monkeypatch):
    """无 replay_run（或全空 assertion_results）→ 无观测断言，整体一致。"""
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, None)  # shadow run：assertion_results 为空不计入
    body = (await client.get(f"/api/v1/skills/{skill_id}/consistency")).json()
    assert body["runs"] == 0
    assert body["assertions"] == []
    assert body["consistent"] is True


async def test_consistency_404(client):
    assert (await client.get("/api/v1/skills/99999/consistency")).status_code == 404


async def test_consistency_matches_realistic_result_rows(client):
    """回归：assert_eval 结果行不含 kind（真形态）——匹配键不依赖 kind。"""
    import json as _json
    from app.db import SessionLocal
    from app.models import OutcomeAssertion, ReplayRun, Skill
    db = SessionLocal()
    try:
        skill = Skill(alignment_id=999, name="S", description="d", status="learned",
                      skeleton=[], param_variables=[], input_variables=[],
                      confidence=1.0, evidence_count=1)
        db.add(skill); db.flush()
        a = OutcomeAssertion(skill_id=skill.id, layer=3, kind="api_status",
                             api_template="/x/save",
                             payload={"api_template": "/x/save", "expect_status": 200})
        db.add(a); db.flush()
        # 真形态结果行：无 kind 键（与 assert_eval 输出一致）
        rows = [{"payload": {"api_template": "/x/save", "expect_status": 200},
                 "observed_status": 200, "passed": True}]
        for st in (200, 200):
            db.add(ReplayRun(skill_id=skill.id, mode="execute", status="pass",
                             plan={}, executed=[], assertion_results=rows))
        db.commit()
        sid = skill.id
    finally:
        db.close()
    r = await client.get(f"/api/v1/skills/{sid}/consistency")
    body = r.json()
    assert body["assertions"], body
    assert body["assertions"][0]["observed_values"] == [200, 200]
    assert body["consistent"] is True


async def test_skill_flow_graph(client, monkeypatch):
    """S39 操作流程图：GET /skills/{id}/flow 返回骨架步骤+断言节点图
    （流程图基座——Skill 详情以图呈现，不再是表格）。"""
    import json as _json
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       _json.dumps({"name": "FlowSkill", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://t/f"}},
        {"seq": 1, "ts": 100, "kind": "action",
         "payload": {"type": "input", "name": "字段A", "value": "旧"}},
        {"seq": 2, "ts": 200, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 3, "ts": 260, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align",
                            json={"session_ids": [sid, sid]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")

    flow = (await client.get(f"/api/v1/skills/{skill['id']}/flow")).json()
    types = [n["type"] for n in flow["nodes"]]
    assert types[0] == "page"
    assert "action" in types
    assert "assert" in types
    # 骨架步骤节点带签名信息（label 含操作语义）
    action = next(n for n in flow["nodes"] if n["type"] == "action")
    assert action["label"]
    # 边连通（链式）
    ids = {n["id"] for n in flow["nodes"]}
    for e in flow["edges"]:
        assert e["from"] in ids and e["to"] in ids
