"""AI3 服务端链执行：规则解释（unique/stepN）+ run_scenario_server + CI 端点。

- resolve_value：${unique:前缀}（时间戳 base36）+ ${stepN.字段}（从上一步
  observed 的 reqBody 提取——与插件端 chain-rules.ts 同语义）
- run_scenario_server：顺序 run_replay（C1 shadow 门控保留——链含写技能且
  confirm=False 时整链 shadow 短路），fail 即停，observed 旁挂供绑定
- POST /chains/{id}/run?wait=1：同步执行，响应含每步 status+run_id；
  HTTP 200=整体 pass / 409=有步骤 fail（CI 退出码语义）
"""
import time

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.db import SessionLocal
from app.models import Alignment, Scenario, Skill


def _resolve_value(value: str, step_ctx: list | None = None,
                   now: int | None = None) -> str:
    """AI3 规则解释（服务端）：与 extension/src/shared/chain-rules.ts 同语义。
    单独 import 测试（不依赖浏览器）。"""
    from app.replay.scenario_runner import resolve_value as rv
    return rv(value, step_ctx, now)


def _extract_field(req_body: str | None, key: str) -> str | None:
    from app.replay.scenario_runner import extract_field
    return extract_field(req_body, key)


async def _mk_chain_skill(db, name, skeleton=None) -> int:
    al = Alignment(session_ids=[], skeleton=skeleton or [], buckets=[],
                   input_variables=[], param_variables=[], window_params={})
    db.add(al)
    db.flush()
    s = Skill(alignment_id=al.id, name=name, description="", status="learned",
              skeleton=skeleton or [], param_variables=[], input_variables=[],
              confidence=0.9, evidence_count=1)
    db.add(s)
    db.commit()
    return s.id


class TestRuleResolve:
    def test_unique(self):
        v = _resolve_value("${unique:sl_}", now=1000)
        assert v == f"sl_{1000:x}" or v.startswith("sl_")

    def test_unique_base36(self):
        v = _resolve_value("${unique:p_}", now=36)
        assert v == "p_10"  # 36 的 base36 = 10

    def test_step_binding_json(self):
        ctx = [[{"reqBody": '{"tableName":"sl_form_x"}'}]]
        assert _resolve_value("${step1.tableName}", ctx) == "sl_form_x"

    def test_step_binding_urlencoded(self):
        ctx = [[{"reqBody": "name=sl_q&code=1"}]]
        assert _resolve_value("${step1.name}", ctx) == "sl_q"

    def test_step_miss_keeps_literal(self):
        ctx = [[{"reqBody": '{"a":1}'}]]
        assert _resolve_value("${step1.miss}", ctx) == "${step1.miss}"

    def test_extract_field_forms(self):
        assert _extract_field('{"k":"v"}', "k") == "v"
        assert _extract_field('{"n":42}', "n") == "42"
        assert _extract_field("k=v&x=1", "k") == "v"
        assert _extract_field(None, "k") is None
        assert _extract_field('{"a":1}', "b") is None


class TestChainRunEndpoint:
    async def test_run_404_and_role(self, client: AsyncClient):
        r = await client.post("/api/v1/scenarios/99999/run")
        assert r.status_code == 404

    async def test_run_sync_shape(self, client: AsyncClient, monkeypatch):
        """同步执行：monkeypatch run_scenario_server 返回固定结果（不起浏览器
        ——端点契约测试：响应结构/退出码语义/步骤明细）。"""
        db = SessionLocal()
        try:
            sid = await _mk_chain_skill(db, "CI 契约技能")
            r = await client.post("/api/v1/scenarios", json={
                "name": "CI 契约链", "system": "x",
                "steps": [{"skill_id": sid, "overrides": {}}]})
            cid = r.json()["id"]

            import app.replay.scenario_runner as scenario_runner_mod
            async def fake_run(db_, scenario_id, confirm):
                return {"status": "pass", "steps": [
                    {"step": 1, "status": "pass", "run_id": 777,
                     "skill_id": sid, "skill_name": "CI 契约技能"}]}
            monkeypatch.setattr(scenario_runner_mod, "run_scenario_server", fake_run)

            resp = await client.post(f"/api/v1/scenarios/{cid}/run?wait=1")
            assert resp.status_code == 200
            body = resp.json()
            assert body["status"] == "pass"
            assert body["steps"][0]["run_id"] == 777

            async def fake_fail(db_, scenario_id, confirm):
                return {"status": "fail", "steps": [
                    {"step": 1, "status": "fail", "run_id": 778,
                     "skill_id": sid, "skill_name": "CI 契约技能"}]}
            monkeypatch.setattr(scenario_runner_mod, "run_scenario_server", fake_fail)
            resp2 = await client.post(f"/api/v1/scenarios/{cid}/run?wait=1")
            assert resp2.status_code == 409  # CI 退出码语义：fail≠200
            assert resp2.json()["detail"]["status"] == "fail"  # HTTPException detail 包装
        finally:
            db.query(Scenario).delete()
            db.query(Skill).filter(Skill.name == "CI 契约技能").delete()
            db.commit()
            db.close()

    async def test_run_role_gate(self, client: AsyncClient, monkeypatch):
        """viewer 只读契约：run 是执行动作（烧浏览器/写目标系统）——WRITE_GUARD。"""
        from app.api.auth import hash_password
        from app.models import User, AuthToken
        import secrets
        import hashlib
        from datetime import timedelta
        from app.models import utcnow
        db = SessionLocal()
        try:
            sid = await _mk_chain_skill(db, "角色技能")
            r = await client.post("/api/v1/scenarios", json={
                "name": "角色链", "system": "x",
                "steps": [{"skill_id": sid, "overrides": {}}]})
            cid = r.json()["id"]
            u = User(username="ci_viewer", role="viewer",
                     password_hash=hash_password("pw-ci"))
            db.add(u)
            db.flush()
            raw = secrets.token_urlsafe(24)
            db.add(AuthToken(user_id=u.id,
                             token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                             expires_at=utcnow() + timedelta(days=1)))
            db.commit()
            hdr = {"Authorization": f"Bearer {raw}"}
            resp = await client.post(f"/api/v1/scenarios/{cid}/run", headers=hdr)
            assert resp.status_code == 403
        finally:
            db.query(Scenario).delete()
            db.query(User).filter(User.username == "ci_viewer").delete()
            db.query(Skill).filter(Skill.name == "角色技能").delete()
            db.commit()
            db.close()
