"""S32 链路时间线 + LLM IO 全留存端点测试。

- GET /api/v1/timeline：聚合 session/alignment/skill/replay/report/review/llm/agent_run，
  按 ts 倒序，limit 生效
- GET /api/v1/audit/llm-logs/{id}：单条 LLM 调用完整 prompt/response（区别于
  列表端点的 200 字符摘要——链路可视化需要全量 IO）；404 = 不存在

造数：session 走 events+process 真实管道，alignment+skill 走 align+induce
（FakeProvider），replay/llm 手插行（C3：手插行合法）。
"""
import json

from app.db import SessionLocal
from app.models import LlmCallLog, ReplayRun


async def _seed_session(client, note: str) -> str:
    sid = (await client.post("/api/v1/sessions",
                             json={"source": "demo", "note": note})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://t/f"}},
        {"seq": 1, "ts": 950, "kind": "snapshot",
         "payload": {"phase": "before",
                     "forms": [{"label": "表单名", "value": "A"}],
                     "labels": [], "tables": []}},
        {"seq": 2, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存", "tag": "button"}}},
        {"seq": 3, "ts": 1600, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200,"status":"SUCCESS"}'}},
        {"seq": 4, "ts": 4200, "kind": "snapshot",
         "payload": {"phase": "after",
                     "forms": [{"label": "表单名", "value": "B"}],
                     "labels": [], "tables": []}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events",
                              json=events)).status_code == 200
    assert (await client.post(f"/api/v1/sessions/{sid}/process")).status_code == 200
    return sid


def _add_llm_log(purpose: str, prompt: str, response: str) -> int:
    db = SessionLocal()
    try:
        row = LlmCallLog(purpose=purpose, provider="fake", model="fake-model",
                         prompt=prompt, response=response,
                         prompt_tokens=100, completion_tokens=20, latency_ms=500)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


async def test_timeline_aggregates_and_sorts_desc(client, monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "TlSkill", "description": "时间线造数"}))
    sids = [await _seed_session(client, "时间线会话") for _ in range(2)]
    aid = (await client.post("/api/v1/align",
                             json={"session_ids": sids})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    db = SessionLocal()
    try:
        db.add(ReplayRun(skill_id=skill["id"], mode="shadow", status="shadow",
                         plan={"url": "http://t/f", "steps": []}, executed=[]))
        db.commit()
    finally:
        db.close()
    _add_llm_log("skill_naming", "P1", "R1")

    rows = (await client.get("/api/v1/timeline")).json()
    types = {r["type"] for r in rows}
    assert {"session", "alignment", "skill", "replay", "llm"} <= types
    # 倒序：ts 单调不增
    ts_list = [r["ts"] for r in rows]
    assert ts_list == sorted(ts_list, reverse=True)
    # 每项契约字段
    for r in rows:
        assert set(r) >= {"type", "id", "title", "subtitle", "ts"}


async def test_timeline_limit(client):
    for i in range(3):
        _add_llm_log(f"p{i}", "P", "R")
    rows = (await client.get("/api/v1/timeline?limit=2")).json()
    assert len(rows) == 2


async def test_llm_log_detail_returns_full_io(client):
    long_prompt = "PROMPT-" + "x" * 500
    long_response = "RESPONSE-" + "y" * 500
    lid = _add_llm_log("skill_naming", long_prompt, long_response)

    row = (await client.get(f"/api/v1/audit/llm-logs/{lid}")).json()
    assert row["prompt"] == long_prompt
    assert row["response"] == long_response
    assert row["purpose"] == "skill_naming"
    assert row["model"] == "fake-model"


async def test_llm_log_detail_404(client):
    resp = await client.get("/api/v1/audit/llm-logs/99999")
    assert resp.status_code == 404
