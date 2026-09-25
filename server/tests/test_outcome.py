import json


async def _make_learned_skill(client, monkeypatch) -> tuple[int, str]:
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveOrder", "description": "保存订单"}))
    sids = []
    for oid in (111, 222):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        events = [
            {"seq": 0, "ts": 0, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 1, "ts": 100, "kind": "network",
             "payload": {"method": "POST", "url": f"/orders/{oid}/save",
                         "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
            {"seq": 2, "ts": 200, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 3, "ts": 300, "kind": "network",
             "payload": {"method": "POST", "url": f"/orders/{oid}/save",
                         "status": 200, "reqBody": json.dumps({"note": f"n{oid}"}),
                         "resBody": '{"code":200}'}},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        await client.post(f"/api/v1/sessions/{sid}/field-changes")
        sids.append(sid)
    aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    return skill["id"], sids[0]


async def test_generate_assertions(client, monkeypatch):
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    resp = await client.post(f"/api/v1/skills/{skill_id}/assertions")
    assert resp.status_code == 200
    n = resp.json()["assertions"]
    assert n >= 3  # api_status + state_signal + field_change
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    kinds = {r["kind"] for r in rows}
    assert kinds == {"api_status", "state_signal", "field_change"}


async def test_verify_all_pass(client, monkeypatch):
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    for r in rows:
        result = (await client.post(f"/api/v1/assertions/{r['id']}/verify")).json()
        assert result["passed"] is True, r


async def test_assertions_only_from_skeleton(client, monkeypatch):
    import json as _json
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", _json.dumps({"name": "S1", "description": "d"}))
    # s1 有额外非骨架窗口，s2 没有 → 断言不得包含 s1 独有 API
    s1 = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    s2 = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    ev_common = [
        {"seq": 0, "ts": 0, "kind": "action", "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 1, "ts": 100, "kind": "network", "payload": {"method": "POST", "url": "/orders/1/save",
             "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    ev_extra = [
        {"seq": 5, "ts": 5000, "kind": "action", "payload": {"type": "click", "target": {"label": "额外"}}},
        {"seq": 6, "ts": 5100, "kind": "network", "payload": {"method": "POST", "url": "/extra/only",
             "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{s1}/events", json=ev_common + ev_extra)
    await client.post(f"/api/v1/sessions/{s2}/events", json=ev_common)
    await client.post(f"/api/v1/sessions/{s1}/process")
    await client.post(f"/api/v1/sessions/{s2}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": [s1, s2]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill['id']}/assertions")).json()
    templates = {r["api_template"] for r in rows}
    assert "/extra/only" not in templates          # 非骨架 API 不得成为断言
    assert "/orders/{id}/save" in templates
    for r in rows:
        v = (await client.post(f"/api/v1/assertions/{r['id']}/verify")).json()
        assert v["passed"] is True                  # 骨架内断言在两 session 全过


async def test_verify_detects_failure(client, monkeypatch):
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    # 直接改库造一个失败：删除第一个 session 的 field_change
    from app.db import SessionLocal
    from app.models import FieldChange
    db = SessionLocal()
    db.query(FieldChange).filter(FieldChange.session_id ==
                                 (await _first_alignment_session(client, skill_id))).delete()
    db.commit()
    db.close()
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    fc = next(r for r in rows if r["kind"] == "field_change")
    result = (await client.post(f"/api/v1/assertions/{fc['id']}/verify")).json()
    assert result["passed"] is False


async def _first_alignment_session(client, skill_id):
    from app.db import SessionLocal
    from app.models import Alignment, Skill
    db = SessionLocal()
    skill = db.get(Skill, skill_id)
    alignment = db.get(Alignment, skill.alignment_id)
    db.close()
    return alignment.session_ids[0]


async def _make_snapshot_skill(client, monkeypatch,
                               before_value="旧值", after_value="新值",
                               toasts=None) -> int:
    """带 before/after 快照事件的录制→归纳（ui_text 断言的证据源）。
    快照归属：before(ts=0) ≤ 锚点(ts=50) → 归该窗；after(ts=250) ≥ 锚点 → 归该窗。
    toasts：after 快照携带的 toast 文本（S12 N3 层1，None 则不带键）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveOrder", "description": "保存订单"}))
    sids = []
    for oid in (111, 222):
        sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
        after_payload = {"phase": "after", "ts": 250,
                         "forms": [{"label": "备注", "value": after_value}],
                         "labels": [], "tables": []}
        if toasts is not None:
            after_payload["toasts"] = toasts
        events = [
            {"seq": 0, "ts": 0, "kind": "snapshot",
             "payload": {"phase": "before", "ts": 0,
                         "forms": [{"label": "备注", "value": before_value}],
                         "labels": [], "tables": []}},
            {"seq": 1, "ts": 50, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 2, "ts": 100, "kind": "network",
             "payload": {"method": "POST", "url": f"/orders/{oid}/save",
                         "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
            {"seq": 3, "ts": 250, "kind": "snapshot", "payload": after_payload},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        sids.append(sid)
    aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    return skill["id"]


async def test_generate_ui_text_from_state_diff(client, monkeypatch):
    """Sprint 8 T3：骨架窗 state_before/after 同 label 不同 value → ui_text 断言。
    两 session 各生成一条同 label 断言 → (kind, template="", label) 去重后仅 1 条。"""
    skill_id = await _make_snapshot_skill(client, monkeypatch)
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    ui = [r for r in rows if r["kind"] == "ui_text"]
    assert len(ui) == 1, rows
    assert ui[0]["layer"] == 2
    assert ui[0]["api_template"] == ""
    assert ui[0]["payload"] == {"label": "备注", "before": "旧值", "after": "新值"}
    # session 回验：源 session 的快照差集存在 → verify 通过
    v = (await client.post(f"/api/v1/assertions/{ui[0]['id']}/verify")).json()
    assert v["passed"] is True, v


async def test_no_ui_text_without_state_diff(client, monkeypatch):
    """before/after 同值（无差集）→ 不生成 ui_text。"""
    skill_id = await _make_snapshot_skill(client, monkeypatch,
                                          before_value="同值", after_value="同值")
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    assert all(r["kind"] != "ui_text" for r in rows), rows


async def test_generate_toast_assertion(client, monkeypatch):
    """S12 N3 层1：after 快照 toasts → state_signal 断言（field=toast）。
    state_signals 直接进断言 payload，生成路径零特判；verify 也走既有
    state_signal 通道（两 session 的 after 快照都带该 toast → 通过）。"""
    skill_id = await _make_snapshot_skill(client, monkeypatch, toasts=["保存成功"])
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    toast = [r for r in rows if r["kind"] == "state_signal"
             and r["payload"].get("field") == "toast"]
    assert len(toast) == 1, rows
    assert toast[0]["layer"] == 3
    assert toast[0]["api_template"] == "/orders/{id}/save"
    assert toast[0]["payload"]["expect_value"] == "保存成功"
    v = (await client.post(f"/api/v1/assertions/{toast[0]['id']}/verify")).json()
    assert v["passed"] is True, v


async def test_no_toast_assertion_without_toasts(client, monkeypatch):
    """after 快照不带 toasts → 不生成 field=toast 断言。"""
    skill_id = await _make_snapshot_skill(client, monkeypatch)  # toasts=None
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    assert all(r["payload"].get("field") != "toast" for r in rows), rows


# ---------- S12 N4 层4：verify 通过次数累加 → layer4_verified 晋升 ----------

async def test_verify_pass_thrice_marks_layer4(client, monkeypatch):
    """同一断言 verify 通过 3 次 → evidence_count=3 且 payload.layer4_verified=true
    （历史成功样本背书；累加在 API 层，库函数 verify_against_session 无副作用）。"""
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    target = rows[0]
    for i in range(3):
        v = (await client.post(f"/api/v1/assertions/{target['id']}/verify")).json()
        assert v["passed"] is True, v
        assert v["evidence_count"] == i + 1
    rows2 = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    payload = next(r for r in rows2 if r["id"] == target["id"])["payload"]
    assert payload["layer4_verified"] is True


async def test_verify_failure_does_not_accumulate(client, monkeypatch):
    """verify 失败不累加 evidence_count，payload 不标 layer4_verified。"""
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    # 造失败：删除第一个 session 的 field_change（同 test_verify_detects_failure）
    from app.db import SessionLocal
    from app.models import FieldChange
    db = SessionLocal()
    db.query(FieldChange).filter(FieldChange.session_id ==
                                 (await _first_alignment_session(client, skill_id))).delete()
    db.commit()
    db.close()
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    fc = next(r for r in rows if r["kind"] == "field_change")
    for _ in range(3):
        v = (await client.post(f"/api/v1/assertions/{fc['id']}/verify")).json()
        assert v["passed"] is False
        assert v["evidence_count"] == 0
    rows2 = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    payload = next(r for r in rows2 if r["id"] == fc["id"])["payload"]
    assert "layer4_verified" not in payload


async def test_truncated_marker_not_asserted(client, monkeypatch):
    """FINDING A：_truncated 标记行不得生成 field_change 断言（污染 C2 锚）。"""
    import json as _json
    from app.db import SessionLocal
    from app.models import FieldChange
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
    db = SessionLocal()
    fc = FieldChange(session_id=sid, api_template="/orders/1/save", before_seq=1,
                     after_seq=3, changes=[
                         {"field": "note", "before": "a", "after": "b"},
                         {"field": "_truncated", "truncated": True,
                          "sha256": {"before": "h1", "after": "h2"}}])
    db.add(fc); db.commit(); db.close()
    sid2 = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    await client.post(f"/api/v1/sessions/{sid2}/events", json=[dict(e, seq=e["seq"]) for e in ev])
    await client.post(f"/api/v1/sessions/{sid2}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": [sid, sid2]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill['id']}/assertions")).json()
    assert all(r["payload"].get("field") != "_truncated" for r in rows), rows


async def test_rebuild_assertions_preserves_evidence_count(client, monkeypatch):
    """层4 资产语义：重建断言不清零 evidence_count/layer4_verified。"""
    skill_id, _ = await _make_learned_skill(client, monkeypatch)
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    rows = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    target = next(r for r in rows if r["kind"] == "api_status")
    for _ in range(3):
        await client.post(f"/api/v1/assertions/{target['id']}/verify")
    # 重建
    await client.post(f"/api/v1/skills/{skill_id}/assertions")
    rows2 = (await client.get(f"/api/v1/skills/{skill_id}/assertions")).json()
    t2 = next(r for r in rows2 if r["kind"] == "api_status"
              and r["payload"]["api_template"] == target["payload"]["api_template"])
    assert t2["payload"].get("layer4_verified") is True
