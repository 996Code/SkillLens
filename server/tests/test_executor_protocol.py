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

    # 换参注入：fill 步 value 被替成 overrides 新值（JeecG 269 铁证回归——
    # 旧值已存在致唯一性校验拒绝，回放写场景必须可换参）
    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    try:
        run = db.get(ReplayRun, body["run_id"])
        fills = [i for i in (run.plan or {}).get("executor_instructions", [])
                 if i.get("op") == "fill"]
        assert fills, "无 fill 指令"
        assert any(i.get("value") == "新值" for i in fills), \
            "overrides 未注入 fill value"
    finally:
        db.close()


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

    # AG3 别名回归：step 写入须真落库——新 session 重读（旧 bug：变异
    # plan 内嵌 dict 使 SQLAlchemy 新旧值相等，UPDATE 不发，内存看似推进）
    from app.db import SessionLocal
    from app.models import ReplayRun as RR
    db = SessionLocal()
    try:
        fresh = db.get(RR, run_id)
        st = (fresh.plan or {}).get("executor_state") or {}
        assert st.get("cursor") == 1 and len(st.get("received", [])) == 1
    finally:
        db.close()


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


async def test_executor_intervention_exhausted_fails(client, monkeypatch):
    """协议 §4 超限语义：介入用满（=2）后再 miss → detach+intervention_
    exhausted+run fail。手工造 label 首步 run（真实 plan 首步是 goto 无
    label，测不到介入链——ASGI 复现实证）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    run = ReplayRun(
        skill_id=1, mode="execute", status="running",
        plan={"steps": [], "url": "http://t/",
              "executor_instructions": [
                  {"seq": 1, "op": "click", "label": "保存", "labels": [],
                   "timeout_ms": 5},
                  {"seq": 2, "op": "detach", "timeout_ms": 5}],
              "executor_state": {"cursor": 0, "received": [],
                                 "interventions": 0, "overrides": {}}},
        executor="extension")
    db.add(run)
    db.commit()
    run_id = run.id
    db.close()
    exhausted = False
    for i in range(3):
        resp = await client.post(f"/api/v1/executor/runs/{run_id}/step",
                                 json={"seq": 1, "result": "miss",
                                       "evidence": {"page_texts": ["保存"]}})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        if body.get("intervention_exhausted"):
            exhausted = True
            ins = body.get("instruction") or {}
            assert ins.get("op") == "detach" or ins.get("seq") is None
            break
    assert exhausted, "3 次 miss 后未触发超限"
    db = SessionLocal()
    try:
        from sqlalchemy import text as _t
        st = db.execute(_t("SELECT status FROM replay_run WHERE id=:i"),
                        {"i": run_id}).scalar()
        assert st == "fail"
    finally:
        db.close()


async def test_focus_step_skip_persists_cursor(client, monkeypatch):
    """聚焦步豁免必须持久化推进（JeecG 941 铁证）：豁免响应返回 fill 指令，
    但 cursor/received 不落库——下一条 fill 上报被幂等判 duplicate、领回聚焦
    步，形成豁免死循环（fill ok→duplicate→click miss→豁免→…）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    run = ReplayRun(
        skill_id=1, mode="execute", status="running",
        plan={"steps": [], "url": "http://t/",
              "executor_instructions": [
                  {"seq": 1, "op": "click", "label": "*表名", "labels": [],
                   "timeout_ms": 5},
                  {"seq": 2, "op": "fill", "name": "*表名", "value": "v1",
                   "timeout_ms": 5},
                  {"seq": 3, "op": "detach", "timeout_ms": 5}],
              "executor_state": {"cursor": 0, "received": [],
                                 "interventions": 0, "overrides": {}}},
        executor="extension")
    db.add(run)
    db.commit()
    run_id = run.id
    db.close()

    # 聚焦步 miss → 豁免：响应给 fill（seq 2），标记 focus_step_skipped
    resp = await client.post(f"/api/v1/executor/runs/{run_id}/step",
                             json={"seq": 1, "result": "miss", "evidence": {}})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("focus_step_skipped") is True
    assert body["instruction"]["seq"] == 2 and body["instruction"]["op"] == "fill"

    # 豁免后状态必须已落库：cursor=1（聚焦步消费）、received 含 miss 证据
    db = SessionLocal()
    try:
        fresh = db.get(ReplayRun, run_id)
        st = (fresh.plan or {}).get("executor_state") or {}
        assert st.get("cursor") == 1, "豁免未持久化 cursor——会触发 duplicate 死循环"
        assert len(st.get("received", [])) == 1
    finally:
        db.close()

    # fill 上报 ok → 不应被幂等挡回（duplicate=False），推进到 detach
    resp2 = await client.post(f"/api/v1/executor/runs/{run_id}/step",
                              json={"seq": 2, "result": "ok", "evidence": {}})
    assert resp2.status_code == 200, resp2.text
    assert resp2.json().get("duplicate") is False
    assert resp2.json()["instruction"]["op"] == "detach"


async def test_executor_finish_evaluates_assertions(client, monkeypatch):
    """AG4：done finish 吃证据跑 evaluate_assertions——判定语义=执行+断言，
    断言结果落 run.assertion_results；status 由断言重判（pass/fail）。"""
    skill_id = await _seed_skill(client, monkeypatch)
    r = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                          json={"overrides": {}, "confirm_side_effect": True})
    run_id = r.json()["run_id"]
    # 模拟执行完成：网络证据=断言期望的 save POST 200
    resp = await client.post(f"/api/v1/executor/runs/{run_id}/finish",
                             json={"status": "done",
                                   "summary": {
                                       "executed": [
                                           {"kind": "input", "name": "请输入",
                                            "ok": True},
                                           {"kind": "click", "label": "保存",
                                            "ok": True}],
                                       "observed": [
                                           {"url": "http://t/a/9/save",
                                            "status": 200, "method": "POST",
                                            "body": '{"code":200}'}],
                                       "duration_ms": 3000, "steps": 3}})
    assert resp.status_code == 200
    body = resp.json()
    assert body["executor"] == "extension"
    # 断言被评估：结果非空且全部通过 → status pass
    assert body["assertion_results"], "断言结果未落"
    assert all(a.get("passed") for a in body["assertion_results"])
    assert body["status"] == "pass"
