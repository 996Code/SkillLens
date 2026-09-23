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
