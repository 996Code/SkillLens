import json

from sqlalchemy import select


def test_flatten_nested():
    from app.ingestion.fielddiff import flatten
    assert flatten({"a": {"b": 1}, "c": "x"}) == {"a.b": 1, "c": "x"}


def test_diff_bodies_changes():
    from app.ingestion.fielddiff import diff_bodies
    changes = diff_bodies({"formName": "A", "keep": 1}, {"formName": "B", "keep": 1})
    assert changes == [{"field": "formName", "before": "A", "after": "B"}]


def test_diff_bodies_added_removed():
    from app.ingestion.fielddiff import diff_bodies
    changes = diff_bodies({"x": 1}, {"y": 2})
    assert {"field": "x", "before": 1, "after": None} in changes
    assert {"field": "y", "before": None, "after": 2} in changes


async def test_field_changes_endpoint(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 1, "ts": 100, "kind": "network",
         "payload": {"method": "POST", "url": "/codeBack/formConfig/saveFormConfig",
                     "status": 200, "reqBody": json.dumps({"formName": "v1"}),
                     "resBody": '{"code":200}'}},
        {"seq": 2, "ts": 200, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 3, "ts": 300, "kind": "network",
         "payload": {"method": "POST", "url": "/codeBack/formConfig/saveFormConfig",
                     "status": 200, "reqBody": json.dumps({"formName": "v2", "extra": True}),
                     "resBody": '{"code":200}'}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    resp = await client.post(f"/api/v1/sessions/{sid}/field-changes")
    assert resp.status_code == 200 and resp.json() == {"field_changes": 1}

    rows = (await client.get(f"/api/v1/sessions/{sid}/field-changes")).json()
    assert rows[0]["api_template"] == "/codeBack/formConfig/saveFormConfig"
    assert rows[0]["before_seq"] == 1 and rows[0]["after_seq"] == 3
    assert {"field": "formName", "before": "v1", "after": "v2"} in rows[0]["changes"]
    assert {"field": "extra", "before": None, "after": True} in rows[0]["changes"]

    # 幂等
    await client.post(f"/api/v1/sessions/{sid}/field-changes")
    assert len((await client.get(f"/api/v1/sessions/{sid}/field-changes")).json()) == 1


def _click(seq: int, ts: int) -> dict:
    return {"seq": seq, "ts": ts, "kind": "action",
            "payload": {"type": "click", "target": {"label": "保存"}}}


def _post(seq: int, ts: int, req_body: str) -> dict:
    return {"seq": seq, "ts": ts, "kind": "network",
            "payload": {"method": "POST", "url": "/codeBack/formConfig/saveFormConfig",
                        "status": 200, "reqBody": req_body, "resBody": '{"code":200}'}}


async def test_field_changes_large_body_truncated(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    filler1 = "x" * 9000
    filler2 = "y" * 9000
    body1 = json.dumps({"formName": "v1", "filler": filler1})
    body2 = json.dumps({"formName": "v2", "filler": filler2})
    assert len(body1.encode("utf-8")) > 8192 and len(body2.encode("utf-8")) > 8192
    events = [_click(0, 0), _post(1, 100, body1), _click(2, 200), _post(3, 300, body2)]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    assert (await client.post(f"/api/v1/sessions/{sid}/field-changes")).status_code == 200

    rows = (await client.get(f"/api/v1/sessions/{sid}/field-changes")).json()
    assert len(rows) == 1
    row = rows[0]
    assert {"field": "formName", "before": "v1", "after": "v2"} in row["changes"]
    # 截断标记在已有 changes JSON 列内（未加列）
    marker = next(c for c in row["changes"] if c.get("field") == "_truncated")
    assert marker["truncated"] is True
    hashes = marker["sha256"]
    # 两次全文 sha256：hex 64 字符且互不相同
    assert all(len(h) == 64 and int(h, 16) >= 0 for h in hashes.values())
    assert hashes["before"] != hashes["after"]
    # 截断点切断 JSON → 回退原文 diff；超限字段的值只存截断前缀，全文不入库
    filler_change = next(c for c in row["changes"] if c["field"] == "filler")
    assert filler_change["before"] != filler_change["after"]
    cap_limit = 8192 + len("…[truncated]".encode("utf-8"))
    assert len(filler_change["before"].encode("utf-8")) <= cap_limit
    assert len(filler_change["after"].encode("utf-8")) <= cap_limit


async def test_field_changes_small_body_not_truncated(client):
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [_click(0, 0), _post(1, 100, json.dumps({"formName": "v1"})),
              _click(2, 200), _post(3, 300, json.dumps({"formName": "v2"}))]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    await client.post(f"/api/v1/sessions/{sid}/field-changes")
    rows = (await client.get(f"/api/v1/sessions/{sid}/field-changes")).json()
    assert len(rows) == 1
    # 小 body：无任何 _truncated 标记（回归不变）
    assert all(c.get("field") != "_truncated" for c in rows[0]["changes"])
