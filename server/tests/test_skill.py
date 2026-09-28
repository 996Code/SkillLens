import json
import os

import pytest


@pytest.fixture
def fake_llm(monkeypatch):
    os.environ.pop("LLM_API_KEY", None)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveFormConfig", "description": "保存表单配置"}))


async def _make_alignment(client) -> int:
    sids = []
    for order_id in (111, 222):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        events = [
            {"seq": 0, "ts": 2000, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 1, "ts": 2600, "kind": "network",
             "payload": {"method": "POST", "url": f"/orders/{order_id}/save",
                         "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        sids.append(sid)
    resp = await client.post("/api/v1/align", json={"session_ids": sids})
    return resp.json()["alignment_id"]


async def test_induce_learned(client, fake_llm):
    aid = await _make_alignment(client)
    resp = await client.post(f"/api/v1/alignments/{aid}/induce")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "SaveFormConfig"
    assert body["status"] == "learned"
    assert body["evidence_count"] == 2
    assert 0 < body["confidence"] <= 1
    assert len(body["skeleton"]) == 1


async def test_induce_candidate_on_bad_json(client, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "not-json")
    aid = await _make_alignment(client)
    body = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    assert body["status"] == "candidate"
    assert body["name"] == "Candidate"
    assert "解析" in body["notes"] or "JSON" in body["notes"]


async def test_induce_candidate_on_bad_name(client, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "save form", "description": "x"}))
    aid = await _make_alignment(client)
    body = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    assert body["status"] == "candidate"
    assert "PascalCase" in body["notes"]


async def test_reinduce_list_shows_only_active_version(client, fake_llm):
    # S15 语义变更（v3 §29 不覆盖旧版本）：re-induce 不再是"删旧建新"的幂等替换——
    # 旧行 superseded 保留在 DB；列表默认排除 superseded，故 /skills 每 alignment
    # 仍只见一条（最新版）。
    aid = await _make_alignment(client)
    await client.post(f"/api/v1/alignments/{aid}/induce")
    await client.post(f"/api/v1/alignments/{aid}/induce")
    skills = (await client.get("/api/v1/skills")).json()
    assert len([s for s in skills if s["alignment_id"] == aid]) == 1


async def test_reinduce_supersedes_keeps_old_assertions(client, fake_llm):
    # S15 语义变更（v3 §29）：re-induce 不再删除旧 Skill 及其断言——旧行
    # status→superseded + superseded_by=新行 id，断言保留作历史；verify 旧行
    # 断言 → 409 提示验证新版本。（原孤儿治理测试断言旧行被删/旧断言 404，
    # 随"先删断言再删 skill"逻辑整体移除而按新语义改写。）
    aid = await _make_alignment(client)
    v1 = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{v1['id']}/assertions")
    rows = (await client.get(f"/api/v1/skills/{v1['id']}/assertions")).json()
    assert rows
    old_ids = [r["id"] for r in rows]

    v2 = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()

    from app.db import SessionLocal
    from app.models import OutcomeAssertion, Skill
    db = SessionLocal()
    try:
        for oid in old_ids:
            assert db.get(OutcomeAssertion, oid) is not None  # 旧断言行保留作历史
        old = db.get(Skill, v1["id"])
        assert old.status == "superseded"
        assert old.superseded_by == v2["id"]
        new = db.get(Skill, v2["id"])
        assert new.status == "learned"
        assert new.version == 2
        assert (old.version or 1) == 1
    finally:
        db.close()

    for oid in old_ids:
        resp = await client.post(f"/api/v1/assertions/{oid}/verify")
        assert resp.status_code == 409                    # 已取代 → 409，而非 404/500
        assert "已被取代" in resp.json()["detail"]
        assert "v2" in resp.json()["detail"]


async def test_reinduce_twice_version_chain(client, fake_llm):
    # S15：re-induce 两次 → 三行 v1(superseded)→v2(superseded)→v3(learned)；
    # superseded_by 链式指向直接后继；各版断言均仍在 DB（历史保留）。
    aid = await _make_alignment(client)
    v1 = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{v1['id']}/assertions")
    v2 = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{v2['id']}/assertions")
    v3 = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()

    from app.db import SessionLocal
    from app.models import OutcomeAssertion, Skill
    db = SessionLocal()
    try:
        rows = db.query(Skill).filter(Skill.alignment_id == aid).order_by(Skill.id).all()
        assert [r.id for r in rows] == [v1["id"], v2["id"], v3["id"]]
        assert [r.version for r in rows] == [1, 2, 3]
        assert [r.status for r in rows] == ["superseded", "superseded", "learned"]
        assert rows[0].superseded_by == v2["id"]   # 链式：指向直接后继
        assert rows[1].superseded_by == v3["id"]
        assert rows[2].superseded_by is None
        # 旧行断言仍在 DB（历史保留，superseded 行一切保留）
        assert db.query(OutcomeAssertion).filter(
            OutcomeAssertion.skill_id == v1["id"]).count() > 0
        assert db.query(OutcomeAssertion).filter(
            OutcomeAssertion.skill_id == v2["id"]).count() > 0
    finally:
        db.close()


async def test_lists_and_trace_exclude_superseded(client, fake_llm):
    # S15：/skills、/baseline/skills（含 compare 聚合）、audit trace 的 skills 段
    # 默认排除 superseded；card 端点对 superseded 行返回 200 + superseded_by
    # （前端提示用，不 404）。
    aid = await _make_alignment(client)
    v1 = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    v2 = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()

    skills = (await client.get("/api/v1/skills")).json()
    assert [s["id"] for s in skills if s["alignment_id"] == aid] == [v2["id"]]

    baseline = (await client.get("/api/v1/baseline/skills")).json()
    assert [i["skill_id"] for i in baseline
            if i["skill_id"] in (v1["id"], v2["id"])] == [v2["id"]]

    compare = (await client.get("/api/v1/baseline/compare")).json()
    assert compare["demo"]["count"] == 1   # superseded 不参与基线聚合

    from app.db import SessionLocal
    from app.models import Alignment
    db = SessionLocal()
    try:
        sid = (db.get(Alignment, aid).session_ids or [])[0]
    finally:
        db.close()
    trace = (await client.get(f"/api/v1/audit/sessions/{sid}/trace")).json()
    assert [s["id"] for s in trace["skills"]] == [v2["id"]]

    card = (await client.get(f"/api/v1/skills/{v1['id']}/card")).json()
    assert card["status"] == "superseded"
    assert card["superseded_by"] == v2["id"]


async def test_verify_assertion_missing_skill_404(client):
    # 兜底：断言存在但 skill 已消失（历史孤儿数据）→ 404 而非 AttributeError 500
    from app.db import SessionLocal
    from app.models import OutcomeAssertion
    db = SessionLocal()
    orphan = OutcomeAssertion(skill_id=999999, layer=3, kind="api_status",
                              api_template="/x/y", payload={})
    db.add(orphan)
    db.commit()
    orphan_id = orphan.id
    db.close()

    resp = await client.post(f"/api/v1/assertions/{orphan_id}/verify")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "skill not found"


async def test_induce_writes_strategies_and_evidence(client, monkeypatch):
    """T3+T4：induce 落 SkillStrategy（分桶数）与 evidence_edge（contains/calls 幂等累加）。"""
    import json as _json
    from app.db import SessionLocal
    from app.models import EvidenceEdge, SkillStrategy
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", _json.dumps({"name": "S", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    ev = []
    for i, note in enumerate(("a", "b")):
        ev += [
            {"seq": i*2, "ts": i*200, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": i*2+1, "ts": i*200+100, "kind": "network",
             "payload": {"method": "POST", "url": "/orders/1/save", "status": 200,
                         "reqBody": _json.dumps({"note": note}), "resBody": '{"code":200}'}},
        ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=ev)
    await client.post(f"/api/v1/sessions/{sid}/process")
    sid2 = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    await client.post(f"/api/v1/sessions/{sid2}/events", json=ev)
    await client.post(f"/api/v1/sessions/{sid2}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": [sid, sid2]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()

    db = SessionLocal()
    try:
        strategies = db.query(SkillStrategy).filter(SkillStrategy.skill_id == skill["id"]).all()
        assert len(strategies) == 1  # 同签名 → 1 桶
        assert strategies[0].evidence_count == 2
        assert "click:保存" in strategies[0].strategy_signature

        edges = db.query(EvidenceEdge).filter(EvidenceEdge.dst == "click:保存").all()
        assert edges and all(e.type == "contains" for e in edges)
        calls = db.query(EvidenceEdge).filter(EvidenceEdge.src == "click:保存").all()
        assert calls and all(e.type == "calls" for e in calls)
        # 二次 induce：策略行重建、边幂等累加（计数≥2，不重复建行）
        await client.post(f"/api/v1/alignments/{aid}/induce")
        n_edges_before = db.query(EvidenceEdge).count()
        strategies2 = db.query(SkillStrategy).filter(
            SkillStrategy.skill_id == skill["id"]).all()
        assert len(strategies2) == 1
        await client.post(f"/api/v1/alignments/{aid}/induce")
        n_edges_after = db.query(EvidenceEdge).count()
        assert n_edges_after == n_edges_before  # 行数不增（幂等）
        call_edge = db.query(EvidenceEdge).filter(
            EvidenceEdge.src == "click:保存", EvidenceEdge.type == "calls").first()
        assert call_edge.evidence_count >= 2  # 每 induce 累加（signature 可编码多个 api 调用）
    finally:
        db.close()


async def test_list_skills_source_field(client, monkeypatch):
    """S10 Task5：GET /skills 列表项带 source（首个 session 来源，缺省 demo）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveFormConfig", "description": "保存"}))

    async def _make(source):
        sids = []
        for order_id in (111, 222):
            body = {"source": source} if source else {}
            sid = (await client.post("/api/v1/sessions", json=body)).json()["session_id"]
            events = [
                {"seq": 0, "ts": 2000, "kind": "action",
                 "payload": {"type": "click", "target": {"label": "保存"}}},
                {"seq": 1, "ts": 2600, "kind": "network",
                 "payload": {"method": "POST", "url": f"/orders/{order_id}/save",
                             "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
            ]
            await client.post(f"/api/v1/sessions/{sid}/events", json=events)
            await client.post(f"/api/v1/sessions/{sid}/process")
            sids.append(sid)
        aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
        return (await client.post(f"/api/v1/alignments/{aid}/induce")).json()["id"]

    demo_skill = await _make(None)
    real_skill = await _make("real_traffic")

    skills = (await client.get("/api/v1/skills")).json()
    by_id = {s["id"]: s for s in skills}
    assert by_id[demo_skill]["source"] == "demo"
    assert by_id[real_skill]["source"] == "real_traffic"


async def test_induce_empty_skeleton_skips_llm(client, monkeypatch):
    """空骨架对齐（不同锚点流不归并）→ 不调 LLM（防幻觉命名），candidate+notes。"""
    import json as _json
    calls = []
    import app.llm.gateway as gw
    orig = gw.complete
    def counting(db, purpose, prompt):
        calls.append(purpose)
        return orig(db, purpose, prompt)
    monkeypatch.setattr(gw, "complete", counting)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", _json.dumps({"name": "Hallucinated", "description": "x"}))
    # 造两个不同锚点的单窗会话 → 空骨架
    sids = []
    for label in ("国内", "国际"):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        await client.post(f"/api/v1/sessions/{sid}/events", json=[
            {"seq": 0, "ts": 0, "kind": "action",
             "payload": {"type": "click", "target": {"label": label}}},
            {"seq": 1, "ts": 100, "kind": "network",
             "payload": {"method": "GET", "url": f"/news/{label}", "status": 200,
                         "resBody": '{"code":0}'}}])
        await client.post(f"/api/v1/sessions/{sid}/process")
        sids.append(sid)
    aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    assert skill["status"] == "candidate"
    assert "骨架为空" in skill["notes"]
    assert calls == []  # LLM 零调用


def test_parse_llm_skill_extracts_last_json_block():
    """S27 彩排发现：glm-5.3-oc 输出思维链+重复 JSON 块——贪婪正则跨块失败。
    解析器须从后往前取可解析的 JSON 对象。"""
    from app.learning.skill import parse_llm_skill
    text = ('Let me analyze...\n{"name": "A", "description": "第一块"}\n\n'
            'The output should be JSON only:\n'
            '{"name": "SaveFormAndTableConfig", "description": "用户点击保存按钮。"}\n')
    d = parse_llm_skill(text)
    assert d is not None
    assert d["name"] == "SaveFormAndTableConfig"


def test_parse_llm_skill_single_block_still_works():
    from app.learning.skill import parse_llm_skill
    assert parse_llm_skill('{"name": "A", "description": "d"}') == {
        "name": "A", "description": "d"}


def test_parse_llm_skill_no_json_returns_none():
    from app.learning.skill import parse_llm_skill
    assert parse_llm_skill("纯文本无 JSON") is None
