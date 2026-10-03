"""AG1 扩展执行器协议——server 侧端点组（TDD 规格：docs/arch/extension-executor-protocol.md）。

四端点语义（v0.1）：
- GET  /executor/skills：技能列表含 requires_confirmation（C1 确认卡元数据）；
- POST /executor/skills/{id}/plan：编译计划（confirm_side_effect 必传 true 才能
  execute——与现有 replay 端点同语义），返回 run_id+首条指令（goto）；
- POST /executor/runs/{run_id}/step：上报证据→返回下一条指令；seq 重复幂等
  （丢弃重放，返回缓存指令）；指令序列=计划步的确定性投影；
- POST /executor/runs/{run_id}/finish：终态落库（done/fail/aborted/lost），
  run 标记 executor=extension，证据归档（C3）。
"""
import json

import app.replay.runner as runner_mod


async def _seed_skill(client, monkeypatch, llm_name="SaveForm"):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": llm_name, "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load", "url": "http://t/f"}},
        {"seq": 1, "ts": 100, "kind": "action",
         "payload": {"type": "input", "name": "请输入", "value": "旧"}},
        {"seq": 2, "ts": 200, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 3, "ts": 260, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": [sid, sid]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    return skill["id"]


async def test_executor_skills_lists_c1_metadata(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    resp = await client.get("/api/v1/executor/skills")
    assert resp.status_code == 200
    items = resp.json()
    hit = next(s for s in items if s["id"] == skill_id)
    assert hit["name"]
    # C1 确认卡元数据：requires_confirmation 布尔（POST 保存步→true）
    assert hit["requires_confirmation"] is True


async def test_executor_plan_compiles_and_returns_first_instruction(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    # 未确认（confirm=false）不编译 execute 计划——C1 双保险
    resp = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                             json={"overrides": {}, "confirm_side_effect": False})
    assert resp.status_code == 409
    # 确认后返回 run_id + 首条指令 goto
    resp = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                             json={"overrides": {"请输入": "新值"},
                                   "confirm_side_effect": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["run_id"] > 0
    first = body["instruction"]
    assert first["op"] == "goto" and first["url"].startswith("http")
    assert first["seq"] == 1 and first["timeout_ms"] > 0


async def test_executor_step_loop_and_idempotency(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    r = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                          json={"overrides": {}, "confirm_side_effect": True})
    run_id = r.json()["run_id"]

    # 步 1 证据（goto ok）→ 指令 2 应为 snapshot 或步骤指令
    ev = {"seq": 1, "result": "ok", "evidence": {"page_title": "t"}}
    r2 = await client.post(f"/api/v1/executor/runs/{run_id}/step", json=ev)
    assert r2.status_code == 200
    ins = r2.json()["instruction"]
    assert ins["seq"] == 2 and ins["op"] in ("snapshot", "resolve", "fill", "click")

    # 同 seq 重放（断连恢复场景）→ 幂等：返回同一条指令，不推进
    r3 = await client.post(f"/api/v1/executor/runs/{run_id}/step", json=ev)
    assert r3.status_code == 200
    assert r3.json()["instruction"]["seq"] == 2
    assert r3.json()["instruction"] == ins


async def test_executor_instructions_carry_resolve_candidates(client, monkeypatch):
    """AG2 接线：click/fill 指令内联 resolver 候选序列（策略名与
    locate.py 同源）——插件端按序实测，无需自行理解定位语义。"""
    skill_id = await _seed_skill(client, monkeypatch)
    r = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                          json={"overrides": {}, "confirm_side_effect": True})
    run_id = r.json()["run_id"]
    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    try:
        run = db.get(ReplayRun, run_id)
        instrs = (run.plan or {}).get("executor_instructions") or []
        clicks = [i for i in instrs if i["op"] == "click"]
        assert clicks, "无 click 指令"
        c = clicks[0]
        assert c.get("resolve_candidates"), "click 指令缺 resolver 候选"
        strategies = [x["strategy"] for x in c["resolve_candidates"]]
        assert "title-attr" in strategies and "role-button" in strategies
    finally:
        db.close()


async def test_executor_finish_lands_run_with_executor_mark(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    r = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                          json={"overrides": {}, "confirm_side_effect": True})
    run_id = r.json()["run_id"]
    # 用户中途停止：aborted 终态，已收证据保留
    resp = await client.post(f"/api/v1/executor/runs/{run_id}/finish",
                             json={"status": "aborted",
                                   "summary": {"executed": [], "observed": []}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "aborted" and body["executor"] == "extension"
