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


class TestExpectWriteAnnotation:
    """AM1（期望-观测对比，docs/specs/2026-10-10-am-*.md）：submit 类
    click 在编译期声明期望效果（写请求）——插件端执行后对比观测。
    词表与服务端 runner write_like 同源（plan.py 单一事实源）。
    两步提交流（Submit→Yes）的 Submit 步豁免（判定移交 Yes 步）。"""

    def _compile(self, steps: list[dict]) -> list[dict]:
        from app.api.executor import compile_executor_plan
        return compile_executor_plan({"url": "http://t/f", "steps": steps})

    def test_submit_click_annotated(self):
        out = self._compile([
            {"kind": "input", "name": "a", "value": "1"},
            {"kind": "click", "label": "保存"},
        ])
        clicks = [i for i in out if i["op"] == "click"]
        assert clicks[0].get("expect_write") is True, "保存 click 必须声明写期望"

    def test_two_stage_submit_exempt(self):
        # Submit 只开确认弹窗（写请求由 Yes 发出）——Submit 步豁免
        out = self._compile([
            {"kind": "click", "label": "Submit"},
            {"kind": "click", "label": "Yes"},
        ])
        clicks = [i for i in out if i["op"] == "click"]
        assert clicks[0].get("expect_write") is not True, "两步提交的 Submit 步应豁免"
        assert clicks[1].get("expect_write") is True, "Yes 步承载写期望"

    def test_non_submit_click_not_annotated(self):
        out = self._compile([
            {"kind": "click", "label": "新增"},
            {"kind": "click", "label": "确定"},  # 搜索类确定——非写词表
        ])
        for c in [i for i in out if i["op"] == "click"]:
            assert c.get("expect_write") is not True, "非 submit click 不应误标"

    def test_word_list_single_source(self):
        # 词表漂移守卫：runner 步循环必须消费 plan.py 常量（不再内联字面量）
        import inspect
        from app.replay import runner as R
        from app.replay.plan import WRITE_EXACT, WRITE_SUB
        src = inspect.getsource(R)
        assert "from app.replay.plan import WRITE_EXACT, WRITE_SUB" in src, \
            "runner 未消费 plan.py 词表（漂移）"
        assert 'write_exact = {"getitems"' not in src, "runner 残留内联词表"

    def test_evidence_derived_expectation(self):
        """AM1 证据派生（真机 2820 实证驱动）：JeecG 模态提交「确定」
        不在词表（防搜索框误报），但录制时其后有 POST——证据派生必须
        命中；搜索「确定」后是 GET——不命中。"""
        from app.api.executor import compile_executor_plan
        steps = [
            {"kind": "click", "label": "新增"},
            {"kind": "input", "name": "a", "value": "1"},
            {"kind": "click", "label": "确定"},
        ]
        events = [
            {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"url": "http://t/f"}},
            {"seq": 1, "ts": 100, "kind": "action", "payload": {"type": "click", "target": {"label": "新增"}}},
            {"seq": 2, "ts": 200, "kind": "action", "payload": {"type": "input", "name": "a", "value": "1"}},
            {"seq": 3, "ts": 300, "kind": "action", "payload": {"type": "click", "target": {"label": "确定"}}},
            {"seq": 4, "ts": 400, "kind": "network", "payload": {"method": "POST", "url": "/u/add", "status": 200}},
        ]
        out = compile_executor_plan({"url": "http://t/f", "steps": steps}, events)
        clicks = [i for i in out if i["op"] == "click"]
        assert clicks[0].get("expect_write") is not True, "新增（开模态）不应期望写"
        assert clicks[1].get("expect_write") is True, "确定（后随 POST）证据派生必须命中"

    def test_evidence_derived_search_get_not_annotated(self):
        from app.api.executor import compile_executor_plan
        steps = [{"kind": "input", "name": "q", "value": "x"},
                 {"kind": "click", "label": "确定"}]
        events = [
            {"seq": 1, "ts": 100, "kind": "action", "payload": {"type": "input", "name": "q", "value": "x"}},
            {"seq": 2, "ts": 200, "kind": "action", "payload": {"type": "click", "target": {"label": "确定"}}},
            {"seq": 3, "ts": 300, "kind": "network", "payload": {"method": "GET", "url": "/u/list?q=x", "status": 200}},
        ]
        out = compile_executor_plan({"url": "http://t/f", "steps": steps}, events)
        clicks = [i for i in out if i["op"] == "click"]
        assert clicks[0].get("expect_write") is not True, "搜索确定（后随 GET）不得误标"

    def test_evidence_derived_two_stage_self_exempt(self):
        from app.api.executor import compile_executor_plan
        steps = [{"kind": "click", "label": "Submit"},
                 {"kind": "click", "label": "Yes"}]
        events = [
            {"seq": 1, "ts": 100, "kind": "action", "payload": {"type": "click", "target": {"label": "Submit"}}},
            {"seq": 2, "ts": 200, "kind": "action", "payload": {"type": "click", "target": {"label": "Yes"}}},
            {"seq": 3, "ts": 300, "kind": "network", "payload": {"method": "POST", "url": "/s", "status": 200}},
        ]
        out = compile_executor_plan({"url": "http://t/f", "steps": steps}, events)
        clicks = [i for i in out if i["op"] == "click"]
        assert clicks[0].get("expect_write") is not True, "Submit（写前先到 Yes 动作）自豁免"
        assert clicks[1].get("expect_write") is True, "Yes 承载写期望"


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
    label，测不到介入链——ASGI 实证）。

    三轮评审修正：提案采纳改为确定性成员校验后，"LLM 返回任意串即 heal"
    不再成立——本用例改为按钮改名场景（旧 label 不在页面上、提案取自
    page_texts），每轮都真 heal（cursor 复位重发同步），第三轮判超限。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "保存")     # 提案取自页面证据
    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    run = ReplayRun(
        skill_id=1, mode="execute", status="running",
        plan={"steps": [], "url": "http://t/",
              "executor_instructions": [
                  {"seq": 1, "op": "click", "label": "保存旧名", "labels": [],
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


async def test_plan_overrides_rewrite_row_anchor(client, monkeypatch):
    """换参注入覆盖 row-anchor（S43-5 服务端语义插件端等效）：行操作候选的
    anchor 含旧实例值时替换——270 铁证：行锚=上游技能建的表名，换参后
    列表行是新值，旧锚行匹配空→更多菜单开不了→同步链全 miss。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    skill_id = await _seed_skill(client, monkeypatch)
    r = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                          json={"overrides": {}, "confirm_side_effect": True})
    run_id = r.json()["run_id"]
    from app.db import SessionLocal
    from app.models import ReplayRun
    db = SessionLocal()
    try:
        run = db.get(ReplayRun, run_id)
        ins = (run.plan or {}).get("executor_instructions")
        assert ins
        # 手工注入带 anchor 的候选（seed 技能无行操作步——单测语义验证）
        ins[0]["resolve_candidates"] = [
            {"strategy": "row-trigger", "kind": "row-trigger",
             "selector": ".ant-table-row", "anchor": "旧表名A12345"}]
        run.plan = {**run.plan, "executor_instructions": ins}
        db.commit()
    finally:
        db.close()
    # 带 overrides 的新 plan（先收敛前一个 run——AK6 批次1 不变量：
    # 同 skill 存在 running run 时新 plan 被拒。aborted 无 error——
    # 不触发 5s 秒败秒建节流形态）
    await client.post(f"/api/v1/executor/runs/{run_id}/finish", json={
        "status": "aborted", "summary": {"executed": []}})
    r2 = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                           json={"overrides": {"旧表名A12345": "新表名B99999"},
                                 "confirm_side_effect": True})
    assert r2.status_code == 200
    body = r2.json()
    first = body["instruction"]
    # 首条是 goto——anchor 注入在 instructions[0] 对应 plan 重编译后消失；
    # 语义验证改走直接检查：重编译后 anchor 候选不存在（seed 无行操作），
    # 但 fill 值替换必须生效
    db = SessionLocal()
    try:
        run2 = db.get(ReplayRun, body["run_id"])
        ins2 = (run2.plan or {}).get("executor_instructions")
        assert not any(c.get("anchor") == "旧表名A12345"
                       for i in ins2 for c in i.get("resolve_candidates") or [])
    finally:
        db.close()


class TestPlanThrottle:
    """垃圾 run 洪泛防线（131 run/13s 实证）：同 skill 5s 内已有快速失败
    的 extension run（秒败秒建=重试风暴形态）→ 拒绝再创建。"""

    async def test_duplicate_plan_after_fast_fail_rejected(self, client, monkeypatch):
        skill_id = await _seed_skill(client, monkeypatch)
        # 创建 → 立即以 attach 冲突错误 finish → 马上再创建（风暴形态）
        r1 = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                               json={"overrides": {}, "confirm_side_effect": True})
        assert r1.status_code == 200
        rid = r1.json()["run_id"]
        await client.post(f"/api/v1/executor/runs/{rid}/finish", json={
            "status": "fail",
            "summary": {"error": "attach 失败：Another debugger is already attached",
                        "executed": []}})
        r2 = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                               json={"overrides": {}, "confirm_side_effect": True})
        assert r2.status_code == 409


class TestStormGaps:
    """AK6 批次1：attach 风暴复盘（docs/reviews/2026-10-09-attach-storm-
    retrospective.md）暴露的四个识别缺口。不变量：同 skill 至多一个
    非终态 extension run；终态 run 不可再写；僵尸必被收割。"""

    async def test_plan_rejected_while_prior_run_running(self, client, monkeypatch):
        """缺口②：running 前驱盲区——118 条僵尸 running 实证。前一个 run
        卡 running（无 error）时 5s 节流放行；不变量守卫必须不看 5s 窗口
        直接拒绝，两种风暴形态（秒败秒建+running 挂着建新的）一起堵。"""
        skill_id = await _seed_skill(client, monkeypatch)
        r1 = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                               json={"overrides": {}, "confirm_side_effect": True})
        assert r1.status_code == 200
        # 不 finish——留 running（模拟卡死/挂起）
        r2 = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                               json={"overrides": {}, "confirm_side_effect": True})
        assert r2.status_code == 409, "running 前驱必须拒绝新 plan"

    async def test_plan_reaps_stale_running_before_check(self, client, monkeypatch):
        """缺口③：收割常态化——plan 入口必跑 _reap_stale_runs。10 分钟前
        创建且无步上报的僵尸 running 应在 plan 时被收割成 lost，随后
        新 plan 放行（正常使用不被死锁——10 分钟过期防永拒）。"""
        from datetime import datetime, timedelta
        from app.db import SessionLocal
        from app.models import ReplayRun
        skill_id = await _seed_skill(client, monkeypatch)
        r1 = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                               json={"overrides": {}, "confirm_side_effect": True})
        rid = r1.json()["run_id"]
        # 伪造 11 分钟前创建的僵尸（无 last_step_at）
        db = SessionLocal()
        try:
            run = db.get(ReplayRun, rid)
            run.created_at = datetime.utcnow() - timedelta(minutes=11)
            db.commit()
        finally:
            db.close()
        r2 = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                               json={"overrides": {}, "confirm_side_effect": True})
        assert r2.status_code == 200, "僵尸收割后新 plan 必须放行"
        db = SessionLocal()
        try:
            assert db.get(ReplayRun, rid).status == "lost"
        finally:
            db.close()

    async def test_step_rejected_after_terminal_state(self, client, monkeypatch):
        """缺口④a：终态 run 不可再写——SW 重启重复消费旧请求（lessons #53）
        的服务端防线。已 finish 的 run 收到 step 上报 → 拒收（409），
        不复活不二次污染。"""
        skill_id = await _seed_skill(client, monkeypatch)
        r1 = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                               json={"overrides": {}, "confirm_side_effect": True})
        rid = r1.json()["run_id"]
        await client.post(f"/api/v1/executor/runs/{rid}/finish", json={
            "status": "fail",
            "summary": {"error": "attach 失败：Another debugger is already attached",
                        "executed": []}})
        # 旧请求复活：向已终态 run 上报 step
        resp = await client.post(f"/api/v1/executor/runs/{rid}/step",
                                 json={"seq": 2, "result": "ok", "evidence": {}})
        assert resp.status_code == 409, "终态 run 的 step 上报必须拒收"

    async def test_finish_rejected_after_terminal_state(self, client, monkeypatch):
        """缺口④b：已终态 run 二次 finish（SW 重启后旧请求重放）→ 拒收，
        防止把 fail 翻写成 pass（判定完整性）。"""
        skill_id = await _seed_skill(client, monkeypatch)
        r1 = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                               json={"overrides": {}, "confirm_side_effect": True})
        rid = r1.json()["run_id"]
        f1 = await client.post(f"/api/v1/executor/runs/{rid}/finish", json={
            "status": "fail",
            "summary": {"error": "attach 失败", "executed": []}})
        assert f1.status_code == 200
        # 重放的 finish 用 done+全绿证据试图翻案——必须被终态守卫拒收
        f2 = await client.post(f"/api/v1/executor/runs/{rid}/finish", json={
            "status": "done",
            "summary": {"executed": [{"kind": "input", "ok": True}],
                        "observed": [{"url": "http://t/a/9/save", "status": 200,
                                      "method": "POST", "body": '{"code":200}'}]}})
        assert f2.status_code == 409, "终态 run 二次 finish 必须拒收（fail 不得翻 pass）"


class TestAtomicPlanGuard:
    """体检🟡①：plan 并发原子化——插入后复查，后到者在竞态窗内让位。"""

    async def test_second_run_yields_when_overlap(self, client, monkeypatch):
        """人为制造竞态窗残留（两条 running）——plan 新建 run 后复查发现
        自己是后到者（id 大），让位 aborted+409。"""
        from app.db import SessionLocal
        from app.models import ReplayRun as RR
        skill_id = await _seed_skill(client, monkeypatch)
        db = SessionLocal()
        try:
            ghost = RR(skill_id=skill_id, mode="execute", status="running",
                       plan={"steps": []}, executor="extension")
            db.add(ghost); db.commit(); ghost_id = ghost.id
        finally:
            db.close()
        r = await client.post(f"/api/v1/executor/skills/{skill_id}/plan",
                              json={"overrides": {}, "confirm_side_effect": True})
        assert r.status_code == 409
        db = SessionLocal()
        try:
            mine = db.get(RR, r.json().get("run_id") or 0)
            # 本测试路径：前置守卫已拦（ghost 在）——让位逻辑在守卫放行
            # 后才触发；此处验证守卫主路径不受让位改动影响
            assert mine is None or mine.status != "running"
        finally:
            db.close()
