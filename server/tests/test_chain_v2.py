"""链编排 v2：前置链（setup）+ 子链引用 + 适配器自动登录。

- ChainStep 支持 skill_id | scenario_id（子链递归展开，深度≤3）
- setup=true 的步骤 fail 只记 warning 不判链失败（登录已有效时登录链
  自然 fail——Playwright storageState 复用的声明式等价：已登录则跳过）
- 服务端执行前自动跑目标系统适配器登录例程（幂等——已登录直过）：
  根治 CI 多系统登录态（storage_state 单文件单域的局限）
"""
import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Alignment, Scenario, Skill


async def _mk(db, name):
    al = Alignment(session_ids=[], skeleton=[], buckets=[],
                   input_variables=[], param_variables=[], window_params={})
    db.add(al)
    db.flush()
    s = Skill(alignment_id=al.id, name=name, description="", status="learned",
              skeleton=[], param_variables=[], input_variables=[],
              confidence=0.9, evidence_count=1)
    db.add(s)
    db.commit()
    return s.id


class TestChainRef:
    async def test_chain_step_can_reference_chain(self, client: AsyncClient):
        """步骤引用链（scenario_id）——子链作为步骤（登录链被业务链引用）。"""
        db = SessionLocal()
        try:
            sid = await _mk(db, "编排技能")
            # 子链（模拟登录链）
            r1 = await client.post("/api/v1/scenarios", json={
                "name": "登录链", "system": "JeecG 表单",
                "steps": [{"skill_id": sid, "overrides": {}, "setup": True}]})
            sub_id = r1.json()["id"]
            # 主链引用子链
            r2 = await client.post("/api/v1/scenarios", json={
                "name": "业务链（引用登录链）", "system": "JeecG 表单",
                "steps": [{"scenario_id": sub_id}, {"skill_id": sid}]})
            assert r2.status_code == 201
            main_id = r2.json()["id"]
            one = await client.get(f"/api/v1/scenarios/{main_id}")
            steps = one.json()["steps"]
            assert steps[0]["scenario_id"] == sub_id
            assert steps[1]["skill_id"] == sid
            # setup 标记持久化
            sub = await client.get(f"/api/v1/scenarios/{sub_id}")
            assert sub.json()["steps"][0]["setup"] is True
        finally:
            db.query(Scenario).delete()
            db.query(Skill).filter(Skill.name == "编排技能").delete()
            db.commit()
            db.close()

    async def test_validation_exclusive_ids(self, client: AsyncClient):
        """skill_id 与 scenario_id 互斥（二选一）；都缺 422。"""
        db = SessionLocal()
        try:
            sid = await _mk(db, "互斥技能")
            r1 = await client.post("/api/v1/scenarios", json={
                "name": "子链", "system": "x",
                "steps": [{"skill_id": sid}]})
            cid = r1.json()["id"]
            both = await client.post("/api/v1/scenarios", json={
                "name": "双 ID", "system": "x",
                "steps": [{"skill_id": sid, "scenario_id": cid}]})
            assert both.status_code == 422
            neither = await client.post("/api/v1/scenarios", json={
                "name": "无 ID", "system": "x", "steps": [{}]})
            assert neither.status_code == 422
        finally:
            db.query(Scenario).delete()
            db.query(Skill).filter(Skill.name == "互斥技能").delete()
            db.commit()
            db.close()


class TestExpandChain:
    def test_expand_subchain_with_setup_semantics(self):
        """子链展开：scenario_id 步骤替换为子链的步骤（继承 setup 标记）；
        深度≤3 防环。"""
        from app.replay.scenario_runner import expand_steps
        steps = [
            {"scenario_id": 1, "setup": True},
            {"skill_id": 42},
        ]
        sub = {1: [{"skill_id": 7}, {"skill_id": 8}]}
        out = expand_steps(steps, sub, depth=0)
        # 子链展开且 setup 传染（登录链整体是前置）
        assert [s["skill_id"] for s in out] == [7, 8, 42]
        assert all(s.get("setup") for s in out[:2])
        assert not out[2].get("setup")

    def test_expand_depth_limit(self):
        from app.replay.scenario_runner import expand_steps
        import pytest as _pytest
        sub = {1: [{"scenario_id": 1}]}  # 自引用环
        with _pytest.raises(ValueError, match="深度"):
            expand_steps([{"scenario_id": 1}], sub, depth=0)


class TestSetupSemantics:
    async def test_setup_fail_not_fatal(self, client: AsyncClient, monkeypatch):
        """setup 步骤 fail 不判链失败（warning 记录）——业务步骤照跑。"""
        db = SessionLocal()
        try:
            sid = await _mk(db, "setup 语义技能")
            cid = (await client.post("/api/v1/scenarios", json={
                "name": "setup 链", "system": "x",
                "steps": [{"skill_id": sid, "setup": True},
                          {"skill_id": sid}]})).json()["id"]

            import app.replay.scenario_runner as cr
            import app.replay.runner as runner_mod
            calls = []

            async def fake_replay(db_, skill_id, ovr, confirm):
                calls.append(skill_id)
                from types import SimpleNamespace
                run = SimpleNamespace(
                    status="fail" if len(calls) == 1 else "pass",
                    id=900 + len(calls),
                    plan={"observed": []})
                return run
            monkeypatch.setattr(runner_mod, "run_replay", fake_replay)

            result = await cr.run_scenario_server(db, cid, True)
            # setup 第一步 fail（登录已有效场景）但链整体 pass
            assert result["status"] == "pass"
            assert len(calls) == 2
            assert result.get("warnings"), "setup fail 应记 warning"
        finally:
            db.query(Scenario).delete()
            db.query(Skill).filter(Skill.name == "setup 语义技能").delete()
            db.commit()
            db.close()


class TestAJ5:
    async def test_step_enabled_toggle(self, client: AsyncClient):
        """步骤启停：enabled=false 跳过（不删配置）。"""
        db = SessionLocal()
        try:
            sid = await _mk(db, "启停技能")
            r = await client.post("/api/v1/scenarios", json={
                "name": "启停链", "system": "x",
                "steps": [{"skill_id": sid, "enabled": False},
                          {"skill_id": sid}]})
            cid = r.json()["id"]
            one = await client.get(f"/api/v1/scenarios/{cid}")
            assert one.json()["steps"][0]["enabled"] is False
            # 执行侧：禁用步被跳过（monkeypatch 验证只跑 1 步）
            import app.replay.scenario_runner as cr
            import app.replay.runner as runner_mod
            calls = []
            async def fake(db_, skill_id, ovr, confirm, system=None):
                calls.append(skill_id)
                from types import SimpleNamespace
                return SimpleNamespace(status="pass", id=991, plan={"observed": []})
            monkeypatch_local = runner_mod.run_replay
            runner_mod.run_replay = fake
            async def no_login(a): return True
            orig_login = cr._adapter_login
            cr._adapter_login = no_login
            try:
                result = await cr.run_scenario_server(db, cid, True)
                assert len(calls) == 1  # 禁用步没跑
                assert result["status"] == "pass"
            finally:
                runner_mod.run_replay = monkeypatch_local
                cr._adapter_login = orig_login
        finally:
            from app.models import Scenario
            db.query(Scenario).delete()
            db.query(Skill).filter(Skill.name == "启停技能").delete()
            db.commit(); db.close()

    async def test_reverse_references(self, client: AsyncClient):
        """反向引用表：技能被哪些链引用。"""
        db = SessionLocal()
        try:
            sid = await _mk(db, "引用技能")
            await client.post("/api/v1/scenarios", json={
                "name": "引用链 A", "system": "x",
                "steps": [{"skill_id": sid}]})
            await client.post("/api/v1/scenarios", json={
                "name": "引用链 B", "system": "x",
                "steps": [{"skill_id": sid, "setup": True}]})
            r = await client.get(f"/api/v1/skills/{sid}/scenario-references")
            assert r.status_code == 200
            names = {x["scenario_name"] for x in r.json()}
            assert names == {"引用链 A", "引用链 B"}
        finally:
            from app.models import Scenario
            db.query(Scenario).delete()
            db.query(Skill).filter(Skill.name == "引用技能").delete()
            db.commit(); db.close()
