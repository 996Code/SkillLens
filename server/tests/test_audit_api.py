"""S10.5 块M 链路审计端点（M1~M4，只读）：会话列表 / 证据边 / LLM 日志 / 单会话 trace 下钻。

造数模式参考 test_baseline_api：会话走 events+process 真实管道（kept 窗 +
orphan_click 过滤窗由 process 落 filtered_window），alignment+skill 走
align+induce（FakeProvider），replay_run/filtered_window/evidence_edge/
llm_call_log 手插行做确定性断言（C3：决策可回放重过滤，手插行合法）。
"""
import json

from app.db import SessionLocal
from app.models import EvidenceEdge, FilteredWindow, LlmCallLog, ReplayRun


async def _seed_audited_session(client, source="demo", note="链路审计") -> str:
    """一个含 kept 窗（快照+写请求+状态信号）与 orphan_click 过滤窗的会话。

    窗 0：click 保存 + POST /a/1/save（code/status 双状态信号）+ before/after
    快照各 1 个 form → kept，semantic_action 带 state_before/after。
    窗 1：click 取消，锚点后无 network 无快照 → orphan_click 过滤
    （filtered_window 行由 process 落库，无 semantic_action → label 走 raw_event 回退）。
    """
    sid = (await client.post("/api/v1/sessions",
                             json={"source": source, "note": note})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://t/f"}},
        {"seq": 1, "ts": 950, "kind": "snapshot",
         "payload": {"phase": "before",
                     "forms": [{"label": "表单名", "value": "默认A"}],
                     "labels": [], "tables": []}},
        {"seq": 2, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存", "tag": "button"}}},
        {"seq": 3, "ts": 1600, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200,"status":"SUCCESS"}'}},
        {"seq": 4, "ts": 4200, "kind": "snapshot",
         "payload": {"phase": "after",
                     "forms": [{"label": "表单名", "value": "默认B"}],
                     "labels": [], "tables": []}},
        {"seq": 5, "ts": 5000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "取消", "tag": "button"}}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events",
                              json=events)).status_code == 200
    assert (await client.post(f"/api/v1/sessions/{sid}/process")).status_code == 200
    return sid


async def _seed_trace_chain(client, monkeypatch, llm_name="TraceSkill"):
    """两会话 → align → induce（FakeProvider）→ 返回 (sids, alignment_id, skill)。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": llm_name, "description": "链路审计造数"}))
    sids = [await _seed_audited_session(client) for _ in range(2)]
    aid = (await client.post("/api/v1/align",
                             json={"session_ids": sids})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    return sids, aid, skill


def _add_replay_run(skill_id: int, mode: str) -> int:
    """直接落 replay_run 行（API 层测试不依赖回放浏览器链路）。"""
    db = SessionLocal()
    try:
        run = ReplayRun(skill_id=skill_id, mode=mode, status=mode,
                        plan={"url": "http://t/f", "steps": []}, executed=[])
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


def _add_edge(src: str, dst: str, edge_type: str, count: int) -> None:
    db = SessionLocal()
    try:
        db.add(EvidenceEdge(src=src, dst=dst, type=edge_type, evidence_count=count))
        db.commit()
    finally:
        db.close()


# ---------- M1a：GET /audit/sessions 会话列表 ----------

async def test_audit_sessions_list_fields_and_counts(client):
    sid = await _seed_audited_session(client, source="real_traffic", note="链路审计")
    items = (await client.get("/api/v1/audit/sessions")).json()
    assert len(items) == 1
    item = items[0]
    assert set(item) == {"session_id", "source", "note", "created_at",
                         "event_count", "filtered_count", "semantic_action_count"}
    assert item["session_id"] == sid
    assert item["source"] == "real_traffic"
    assert item["note"] == "链路审计"
    assert item["created_at"]                    # iso 时间串非空
    assert item["event_count"] == 6
    assert item["filtered_count"] == 1
    assert item["semantic_action_count"] == 1


async def test_audit_sessions_order_limit_zero_counts(client):
    """created_at 倒序（最新在前）+ limit + 未处理会话三计数为 0。"""
    sids = [(await client.post("/api/v1/sessions", json={})).json()["session_id"]
            for _ in range(3)]
    items = (await client.get("/api/v1/audit/sessions")).json()
    assert [i["session_id"] for i in items] == list(reversed(sids))
    assert all(i["event_count"] == 0 and i["filtered_count"] == 0
               and i["semantic_action_count"] == 0 for i in items)
    limited = (await client.get("/api/v1/audit/sessions?limit=2")).json()
    assert [i["session_id"] for i in limited] == list(reversed(sids))[:2]


# ---------- M2：GET /audit/evidence-edges 证据边列表 ----------

async def test_audit_evidence_edges_fields_order_filters(client):
    _add_edge("s1", "click:保存", "contains", 3)
    _add_edge("click:保存", "POST:/x/save", "calls", 1)
    _add_edge("click:查询", "GET:/y/list", "calls", 2)

    items = (await client.get("/api/v1/audit/evidence-edges")).json()
    assert len(items) == 3
    assert [i["evidence_count"] for i in items] == [3, 2, 1]   # evidence_count 倒序
    first = items[0]
    assert set(first) == {"src", "dst", "type", "evidence_count",
                          "first_seen", "last_seen"}
    assert first["src"] == "s1"
    assert first["dst"] == "click:保存"
    assert first["type"] == "contains"
    assert first["first_seen"] and first["last_seen"]

    calls = (await client.get("/api/v1/audit/evidence-edges?type=calls")).json()
    assert {i["src"] for i in calls} == {"click:保存", "click:查询"}   # type 精确过滤

    liked = (await client.get(
        "/api/v1/audit/evidence-edges?src_like=click:保")).json()
    assert [(i["src"], i["dst"]) for i in liked] == [("click:保存", "POST:/x/save")]

    limited = (await client.get("/api/v1/audit/evidence-edges?limit=1")).json()
    assert len(limited) == 1 and limited[0]["evidence_count"] == 3


# ---------- M3：GET /audit/llm-logs LLM 调用日志 ----------

async def test_audit_llm_logs_fields_truncation_order(client):
    db = SessionLocal()
    try:
        db.add(LlmCallLog(purpose="skill_naming", provider="fake", model="fake-model",
                          prompt="P" * 250, response="R" * 250,
                          prompt_tokens=11, completion_tokens=7, latency_ms=42))
        db.add(LlmCallLog(purpose="assert_gen", provider="fake", model="fake-model",
                          prompt="短", response="ok",
                          prompt_tokens=None, completion_tokens=None, latency_ms=5))
        db.commit()
    finally:
        db.close()

    items = (await client.get("/api/v1/audit/llm-logs")).json()
    assert len(items) == 2
    assert items[0]["purpose"] == "assert_gen"          # id 倒序：后插在前
    assert set(items[0]) == {"id", "purpose", "provider", "model", "prompt_tokens",
                             "completion_tokens", "latency_ms", "created_at",
                             "prompt_head", "response_head"}
    assert items[0]["prompt_head"] == "短"
    assert items[0]["response_head"] == "ok"
    assert items[0]["prompt_tokens"] is None            # 失败/无 usage 调用为 NULL

    tail = items[1]
    assert tail["prompt_head"] == "P" * 200             # 界面摘要 200 字符截断
    assert tail["response_head"] == "R" * 200
    assert tail["prompt_tokens"] == 11 and tail["completion_tokens"] == 7
    assert tail["latency_ms"] == 42

    limited = (await client.get("/api/v1/audit/llm-logs?limit=1")).json()
    assert len(limited) == 1 and limited[0]["purpose"] == "assert_gen"


# ---------- M1b/M4：GET /audit/sessions/{sid}/trace 单会话链路下钻 ----------

async def test_audit_trace_full_chain(client, monkeypatch):
    sids, aid, skill = await _seed_trace_chain(client, monkeypatch)
    run_ids = [_add_replay_run(skill["id"], "execute"),
               _add_replay_run(skill["id"], "shadow")]

    resp = await client.get(f"/api/v1/audit/sessions/{sids[0]}/trace")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"session", "windows", "semantic_actions",
                         "alignments", "skills", "replay_runs"}

    # session：与列表项同构
    s = body["session"]
    assert set(s) == {"session_id", "source", "note", "created_at",
                      "event_count", "filtered_count", "semantic_action_count"}
    assert s["session_id"] == sids[0]
    assert s["event_count"] == 6
    assert s["filtered_count"] == 1
    assert s["semantic_action_count"] == 1

    # windows：全窗 + filtered 联查（M4：每窗显式 kept/reason）
    wins = body["windows"]
    assert [w["window_seq"] for w in wins] == [0, 1]
    assert set(wins[0]) == {"window_seq", "anchor_type", "anchor_label", "kept",
                            "filter_reason", "api_count", "state_signal_count",
                            "has_state_snapshot"}
    w0, w1 = wins
    assert w0["kept"] is True and w0["filter_reason"] == ""
    assert w0["anchor_type"] == "click" and w0["anchor_label"] == "保存"
    assert w0["api_count"] == 1
    assert w0["state_signal_count"] == 2               # code + status 双信号
    assert w0["has_state_snapshot"] is True
    assert w1["kept"] is False and w1["filter_reason"] == "orphan_click"
    assert w1["anchor_label"] == "取消"                 # 无语义动作 → raw_event label 回退
    assert w1["anchor_type"] == "click"
    assert w1["api_count"] == 0 and w1["state_signal_count"] == 0
    assert w1["has_state_snapshot"] is False

    # semantic_actions：forms 为计数
    acts = body["semantic_actions"]
    assert len(acts) == 1
    assert set(acts[0]) == {"window_seq", "anchor_label", "api_templates",
                            "state_before_forms", "state_after_forms"}
    assert acts[0]["window_seq"] == 0
    assert acts[0]["anchor_label"] == "保存"
    assert acts[0]["api_templates"] == ["/a/{id}/save"]   # URL 模板化后的路径
    assert acts[0]["state_before_forms"] == 1
    assert acts[0]["state_after_forms"] == 1

    # alignments：session_ids 包含该 sid（JSON 列 Python 侧过滤）
    aligns = body["alignments"]
    assert len(aligns) == 1
    assert set(aligns[0]) == {"id", "skeleton_steps", "bucket_count"}
    assert aligns[0]["id"] == aid
    assert aligns[0]["skeleton_steps"] >= 1
    assert aligns[0]["bucket_count"] == 1               # 两会话同路径 → 单桶

    # skills：上述 alignment 的 skill
    skills = body["skills"]
    assert len(skills) == 1
    assert set(skills[0]) == {"id", "name", "status", "confidence"}
    assert skills[0]["id"] == skill["id"]
    assert skills[0]["name"] == "TraceSkill"
    assert skills[0]["status"] == "learned"
    assert skills[0]["confidence"] == skill["confidence"]

    # replay_runs：上述 skill 的全部 run，id 倒序
    runs = body["replay_runs"]
    assert [r["id"] for r in runs] == list(reversed(run_ids))
    assert set(runs[0]) == {"id", "status", "mode", "created_at"}
    assert runs[0]["mode"] == "shadow" and runs[1]["mode"] == "execute"

    # 404：会话不存在
    assert (await client.get(
        "/api/v1/audit/sessions/no-such-sid/trace")).status_code == 404


async def test_audit_trace_manual_filtered_row_keeps_semantic_label(client):
    """手插 filtered_window 行（C3 可回放重过滤）：kept 翻转、reason 来自手插行，
    但窗口已有 semantic_action 时 anchor_label 仍优先语义动作（不回退 raw_event）。"""
    sid = await _seed_audited_session(client)
    db = SessionLocal()
    try:
        db.add(FilteredWindow(session_id=sid, window_seq=0, reason="read_only"))
        db.commit()
    finally:
        db.close()

    wins = (await client.get(f"/api/v1/audit/sessions/{sid}/trace")).json()["windows"]
    w0 = wins[0]
    assert w0["kept"] is False and w0["filter_reason"] == "read_only"
    assert w0["anchor_label"] == "保存"                 # 优先 semantic_action.target.label
    assert w0["api_count"] == 1                         # 语义动作数据不因决策行消失


async def test_audit_trace_without_snapshots_and_empty_downstream(client):
    """无 snapshot 事件：forms 计数为 None；未 align 的会话下游三段为空列表。"""
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": "http://t/f"}},
        {"seq": 1, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 2, "ts": 1600, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")

    body = (await client.get(f"/api/v1/audit/sessions/{sid}/trace")).json()
    w0 = body["windows"][0]
    assert w0["kept"] is True and w0["has_state_snapshot"] is False
    act = body["semantic_actions"][0]
    assert act["state_before_forms"] is None
    assert act["state_after_forms"] is None
    assert body["alignments"] == []
    assert body["skills"] == []
    assert body["replay_runs"] == []
