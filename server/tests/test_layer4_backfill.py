"""P2-13 层4背书激活（差距报告：evidence_count≥3 全库为 0）——回放 pass
的断言命中也是历史成功样本，与人工 verify 同权重累加（层4=历史成功样本
背书；只认人工 verify 让层4 永远沉睡）。"""
import pytest
from httpx import AsyncClient

from tests.test_replay_api import _seed_skill
from app.db import SessionLocal
from app.models import OutcomeAssertion
import app.replay.runner as rm


def _fake_execute(observed):
    async def fake(page, plan, **kw):
        return {"executed": [
                    {"kind": "input", "name": "请输入", "value": "v1", "ok": True},
                    {"kind": "click", "label": "保存", "ok": True}],
                "observed": observed,
                "observed_toasts": [], "api_latencies": {}}
    return fake


async def _replay_pass(client, monkeypatch, skill_id, observed):
    class FakePage:
        async def goto(self, url): ...
        async def wait_for_load_state(self, s, timeout=None): ...
        def on(self, *a): ...
        async def wait_for_timeout(self, ms): ...
        async def query_selector_all(self, selector): return []
        async def screenshot(self, path=None): ...
        async def title(self): return "t"
    class FakeCtx:
        async def new_page(self): return FakePage()
    class FakeBrowser:
        async def new_context(self, storage_state=None): return FakeCtx()
        async def close(self): ...
    class FakePW:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): ...
        async def chromium_launch(self): return FakeBrowser()
    monkeypatch.setattr(rm, "execute_plan", _fake_execute(observed))
    monkeypatch.setattr(rm, "_launch", lambda: FakePW())
    r = await client.post(f"/api/v1/skills/{skill_id}/replay",
                          json={"overrides": {}, "confirm_side_effect": True})
    assert r.status_code == 200
    return r.json()


async def test_replay_pass_accumulates_evidence(client: AsyncClient, monkeypatch):
    """回放 pass 且断言命中 → evidence_count +1（层4 成功样本背书激活）。"""
    skill_id = await _seed_skill(client, monkeypatch)
    db = SessionLocal()
    try:
        row = db.query(OutcomeAssertion).filter_by(skill_id=skill_id).first()
        assert row is not None
        before = row.evidence_count or 0
        body = await _replay_pass(client, monkeypatch, skill_id, [
            {"url": "http://t/a/1/save", "status": 200, "method": "POST",
             "body": '{"code":200}', "latency_ms": 5}])
        assert body["status"] == "pass", body.get("assertion_results")
        db.expire_all()
        row = db.query(OutcomeAssertion).filter_by(skill_id=skill_id).first()
        assert (row.evidence_count or 0) == before + 1
    finally:
        db.query(OutcomeAssertion).filter_by(skill_id=skill_id).delete()
        db.commit(); db.close()


async def test_replay_fail_does_not_accumulate(client: AsyncClient, monkeypatch):
    """回放断言未命中 → 不累加（失败现场不是成功样本）。"""
    skill_id = await _seed_skill(client, monkeypatch)
    db = SessionLocal()
    try:
        body = await _replay_pass(client, monkeypatch, skill_id, [
            # 断言模板 /a/1/save 无命中 → 断言 fail → run fail
            {"url": "http://t/other", "status": 200, "method": "POST",
             "body": "", "latency_ms": 5}])
        assert body["status"] != "pass"
        db.expire_all()
        row = db.query(OutcomeAssertion).filter_by(skill_id=skill_id).first()
        assert (row.evidence_count or 0) == 0
    finally:
        db.query(OutcomeAssertion).filter_by(skill_id=skill_id).delete()
        db.commit(); db.close()


async def test_layer4_flag_at_three(client: AsyncClient, monkeypatch):
    """三次回放 pass → layer4_verified 标记（与人工 verify 同阈值）。"""
    skill_id = await _seed_skill(client, monkeypatch)
    db = SessionLocal()
    try:
        for _ in range(3):
            await _replay_pass(client, monkeypatch, skill_id, [
                {"url": "http://t/a/1/save", "status": 200, "method": "POST",
                 "body": '{"code":200}', "latency_ms": 5}])
        db.expire_all()
        row = db.query(OutcomeAssertion).filter_by(skill_id=skill_id).first()
        assert row.evidence_count >= 3
        assert row.payload.get("layer4_verified") is True
    finally:
        db.query(OutcomeAssertion).filter_by(skill_id=skill_id).delete()
        db.commit(); db.close()
