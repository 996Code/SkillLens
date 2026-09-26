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


def test_cap_value_truncates_non_string_large_values():
    """FINDING B：非 str 大值（list/大数字）也必须截断，不得全文入库。"""
    from app.ingestion.fielddiff import cap_value
    big_list = ["x" * 100] * 200  # 序列化后远超 8KB
    capped = cap_value(big_list)
    assert capped != big_list
    assert len(str(capped).encode("utf-8")) <= 8192 + 100


def test_truncate_exact_8192_boundary():
    """恰好 8192 字节不截断（边界测试，审查建议项）。"""
    from app.ingestion.fielddiff import truncate_req_body
    exact = "a" * 8192
    r = truncate_req_body(exact)
    assert r["truncated"] is False and r["sha256"] is None
    r2 = truncate_req_body("a" * 8193)
    assert r2["truncated"] is True and r2["sha256"] is not None


def test_100kb_reqbody_diff_performance():
    """J5 性能基准：100KB reqBody 经 8KB 截断后 diff，1 秒内完成（S7 截断保护的规模验证）。"""
    import time
    from app.ingestion.fielddiff import diff_bodies, truncate_req_body
    big1 = '{"note": "' + "x" * 100_000 + '", "extra": 1}'
    big2 = '{"note": "' + "y" * 100_000 + '", "extra": 2}'
    t1 = truncate_req_body(big1)
    t2 = truncate_req_body(big2)
    assert t1["truncated"] and t2["truncated"]
    # 截断致 JSON 解析失败时回退全文 diff（fieldchange 实际路径）——
    # 100KB 字符串 diff 的性能基准
    import json as _json
    d1, d2 = _json.loads(big1), _json.loads(big2)
    start = time.perf_counter()
    for _ in range(100):
        changes = diff_bodies(d1, d2)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, f"100 次 100KB diff 耗时 {elapsed:.2f}s 超标"
    assert changes
