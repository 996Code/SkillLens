"""S23 块 V T3：性能漂移进四分类报告（TDD 先红）。

- 历史 ≥3 次慢基线 + 当前显著变慢 → drift 含 perf 项（确定性）；
- 历史不足 3 次 → 无 perf 项；
- 响应含 perf 上下文（baseline/current/history）；
- API 延迟漂移同规则进 drift。
"""
import json


async def _seed_confirmed_delta(client, monkeypatch) -> tuple[int, int]:
    """建 skill + confirmed expected delta，返回 (skill_id, delta_id)。"""
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                        json.dumps({"name": "SaveForm", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load", "url": "http://mock.local/"}},
        {"seq": 1, "ts": 100, "kind": "action", "payload": {"type": "input", "name": "请输入", "value": "旧"}},
        {"seq": 2, "ts": 200, "kind": "action", "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 3, "ts": 260, "kind": "network", "payload": {"method": "POST", "url": "/a/1/save", "status": 200, "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": [sid, sid]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    delta = (await client.post("/api/v1/expected-deltas", json={
        "requirement_id": "perf-req", "requirement_text": "测试",
    })).json()
    # FakeProvider 提案为空 → 确认时提交修订 changes（ConfirmRequest.changes）
    delta = (await client.post(f"/api/v1/expected-deltas/{delta['id']}/confirm",
                              json={"reviewed_by": "perf-test",
                                    "changes": [{"type": "api_add",
                                                 "value": "/a/1/save"}]})).json()
    return skill["id"], delta["id"]


def _add_runs(skill_id: int, durations: list[int],
              latencies: list[dict] | None = None) -> int:
    """直插历史 execute run（带 duration_ms/plan.api_latencies），返回最后一个 run id。"""
    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    last = 0
    try:
        for i, d in enumerate(durations):
            run = ReplayRun(skill_id=skill_id, mode="execute", status="pass",
                           plan={"url": "http://mock.local/", "steps": [],
                                 "api_latencies": (latencies[i] if latencies else {})},
                           executed=[], assertion_results=[],
                           duration_ms=d)
            db.add(run)
            db.commit()
            db.refresh(run)
            last = run.id
    finally:
        db.close()
    return last


def _add_observed(delta_id: int, skill_id: int, run_id: int, duration_ms: int) -> int:
    from app.db import SessionLocal
    from app.models import ObservedDelta
    db = SessionLocal()
    try:
        row = ObservedDelta(expected_delta_id=delta_id, skill_id=skill_id,
                            replay_run_id=run_id, items=[],
                            duration_ms=duration_ms)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


async def test_perf_drift_into_report(client, monkeypatch):
    skill_id, delta_id = await _seed_confirmed_delta(client, monkeypatch)
    # 历史 3 次快回放（中位 1000ms），当前 5000ms = 5x > 1.5x → perf drift
    _add_runs(skill_id, [900, 1000, 1100])
    slow_run = _add_runs(skill_id, [5000])
    obs_id = _add_observed(delta_id, skill_id, slow_run, 5000)

    resp = await client.post(f"/api/v1/expected-deltas/{delta_id}/report",
                             json={"observed_delta_id": obs_id})
    assert resp.status_code == 201
    body = resp.json()
    perf_items = [d for d in body["drift"] if d["type"] == "perf"]
    assert len(perf_items) == 1
    assert "1000ms" in perf_items[0]["value"] and "5000ms" in perf_items[0]["value"]
    # perf 上下文
    assert body["perf"]["baseline"]["median"] == 1000
    assert body["perf"]["current_ms"] == 5000
    assert body["perf"]["history_ms"] == [900, 1000, 1100]


async def test_perf_no_drift_insufficient_history(client, monkeypatch):
    skill_id, delta_id = await _seed_confirmed_delta(client, monkeypatch)
    _add_runs(skill_id, [900, 1000])          # 仅 2 次历史
    slow_run = _add_runs(skill_id, [99999])
    obs_id = _add_observed(delta_id, skill_id, slow_run, 99999)

    resp = await client.post(f"/api/v1/expected-deltas/{delta_id}/report",
                             json={"observed_delta_id": obs_id})
    body = resp.json()
    assert [d for d in body["drift"] if d["type"] == "perf"] == []


async def test_api_latency_drift_into_report(client, monkeypatch):
    skill_id, delta_id = await _seed_confirmed_delta(client, monkeypatch)
    hist_lat = [{"/a/{id}/save": 100}, {"/a/{id}/save": 120}, {"/a/{id}/save": 110}]
    _add_runs(skill_id, [1000, 1000, 1000], latencies=hist_lat)
    slow_run = _add_runs(skill_id, [1000],
                         latencies=[{"/a/{id}/save": 600}])
    obs_id = _add_observed(delta_id, skill_id, slow_run, 1000)

    resp = await client.post(f"/api/v1/expected-deltas/{delta_id}/report",
                             json={"observed_delta_id": obs_id})
    body = resp.json()
    perf_items = [d for d in body["drift"] if d["type"] == "perf"]
    # 总耗时正常（1000 ≈ 中位 1000）无耗时漂移；API 延迟 110 → 600 = 5.5x 漂移
    assert len(perf_items) == 1
    assert "/a/{id}/save" in perf_items[0]["value"]


async def test_report_perf_endpoint(client, monkeypatch):
    """GET /reports/{id}/perf：报告页刷新后仍可取性能上下文（只读派生）。"""
    skill_id, delta_id = await _seed_confirmed_delta(client, monkeypatch)
    _add_runs(skill_id, [900, 1000, 1100])
    slow_run = _add_runs(skill_id, [5000])
    obs_id = _add_observed(delta_id, skill_id, slow_run, 5000)
    report = (await client.post(f"/api/v1/expected-deltas/{delta_id}/report",
                                json={"observed_delta_id": obs_id})).json()

    resp = await client.get(f"/api/v1/reports/{report['id']}/perf")
    assert resp.status_code == 200
    perf = resp.json()
    assert perf["baseline"]["median"] == 1000
    assert perf["current_ms"] == 5000
    assert perf["history_ms"] == [900, 1000, 1100]

    # 404：不存在的报告
    resp = await client.get("/api/v1/reports/99999/perf")
    assert resp.status_code == 404
