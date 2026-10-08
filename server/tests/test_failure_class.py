"""AJ1/AJ2 失败分类学测试：分类器纯函数+blocked 语义+分母口径+登录守卫。"""
import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Alignment, ReplayRun, Skill


class TestClassifier:
    def test_e1_login_url(self):
        from app.change.failure_class import classify_run
        r = {"status": "fail",
             "executed": [{"kind": "input", "ok": False,
                           "error": "semantic locate failed: 'el-id-1' @ http://127.0.0.1:8093/login?redirect=/x"}]}
        assert classify_run(r) == "e1_env"  # 登录态丢失

    def test_e1_chrome_error_and_nav_timeout(self):
        from app.change.failure_class import classify_run
        assert classify_run({"status": "error",
                             "executed": [{"kind": "goto", "ok": False,
                                           "error": "net::ERR_CONNECTION_REFUSED"}]}) == "e1_env"
        assert classify_run({"status": "error",
                             "executed": [{"kind": "goto", "ok": False,
                                           "error": "Timeout 15000ms exceeded @ page.goto"}]}) == "e1_env"

    def test_e2_infra_llm_gateway(self):
        from app.change.failure_class import classify_run
        assert classify_run({"status": "error",
                             "executed": [{"kind": "click", "ok": False,
                                           "error": "Token额度不足，请充值"}]}) == "e2_infra"

    def test_e3_drift_locate_miss(self):
        from app.change.failure_class import classify_run
        # 定位失败但 URL 在正常业务页——元素漂移
        assert classify_run({"status": "fail",
                             "executed": [{"kind": "click", "ok": False,
                                           "error": "semantic locate failed: '保存' @ http://127.0.0.1:8095/online/cgform"}]}) == "e3_drift"

    def test_e3_assertion_fail(self):
        from app.change.failure_class import classify_run
        assert classify_run({"status": "fail", "executed": [{"kind": "click", "ok": True}],
                             "assertions": [{"passed": False, "skipped": None,
                                             "payload": {"api_template": "/x/add"}}]}) == "e3_drift"

    def test_pass_and_shadow_null(self):
        from app.change.failure_class import classify_run
        assert classify_run({"status": "pass"}) is None
        assert classify_run({"status": "shadow"}) is None  # 未执行不分类

    def test_e4_not_implemented_yet(self):
        """E4（预期失败）当前无判定入口——留负向用例占位：普通 fail 不误判 e4。"""
        from app.change.failure_class import classify_run
        assert classify_run({"status": "fail", "executed": []}) is None  # 无证据不猜


class TestBlockedChainSteps:
    async def test_chain_fail_marks_rest_blocked(self, client: AsyncClient, monkeypatch):
        """链 fail 即停：后续步骤标 blocked（没跑≠失败）——落结果不落占位 run
        （占位 run 会污染 executor 列表；skipped 清单在链结果里）。"""
        db = SessionLocal()
        try:
            al = Alignment(session_ids=[], skeleton=[], buckets=[],
                           input_variables=[], param_variables=[], window_params={})
            db.add(al); db.flush()
            s1 = Skill(alignment_id=al.id, name="会败步骤", description="",
                       status="learned", skeleton=[], param_variables=[],
                       input_variables=[], confidence=0.9, evidence_count=1)
            s2 = Skill(alignment_id=al.id, name="被阻塞步骤", description="",
                       status="learned", skeleton=[], param_variables=[],
                       input_variables=[], confidence=0.9, evidence_count=1)
            db.add_all([s1, s2]); db.commit()

            from app.api.chains import Chain  # noqa
            from app.models import Chain
            r = await client.post("/api/v1/chains", json={
                "name": "blocked 语义链", "system": "JeecG 表单",
                "steps": [{"skill_id": s1.id}, {"skill_id": s2.id}]})
            cid = r.json()["id"]

            import app.replay.runner as runner_mod
            async def fake_replay(db_, skill_id, ovr, confirm, system=None):
                from types import SimpleNamespace
                st = "fail" if skill_id == s1.id else "pass"
                return SimpleNamespace(status=st, id=950 + skill_id % 7,
                                       plan={"observed": []})
            monkeypatch.setattr(runner_mod, "run_replay", fake_replay)

            import app.replay.chain_runner as cr
            # 屏蔽自动登录（无网络依赖）
            async def no_login(aid): return True
            monkeypatch.setattr(cr, "_adapter_login", no_login)

            result = await cr.run_chain_server(db, cid, True)
            assert result["status"] == "fail"
            assert result["steps"][0]["status"] == "fail"
            # 后续步骤标 blocked（不是缺失也不是 fail）
            assert result["steps"][1]["status"] == "blocked"
            # 分母：只有执行了的步骤（blocked 不进）
            assert result["total"] == 1
        finally:
            from app.models import Chain as C
            db.query(C).delete()
            db.query(Skill).filter(Skill.name.in_(["会败步骤", "被阻塞步骤"])).delete()
            db.query(Alignment).filter(Alignment.id == al.id).delete()
            db.commit(); db.close()


class TestPassRateDenominator:
    def test_trend_excludes_e1e2(self):
        """趋势卡口径：E1/E2 不进分母（TestRail blocked 语义）。"""
        from app.change.failure_class import pass_rate
        runs = [
            {"status": "pass", "failure_class": None},
            {"status": "fail", "failure_class": "e1_env"},   # 环境失败不计
            {"status": "fail", "failure_class": "e3_drift"},  # 真失败计
        ]
        rate = pass_rate(runs)
        assert rate == {"pass": 1, "total": 2, "rate": 0.5}


class TestExtensionClassification:
    async def test_finish_fail_classified(self, client: AsyncClient):
        """AJ1 补线：extension finish fail → failure_class 非空（主通道
        占 fail/error 54%，此前零产出——抽查实锤）。"""
        db = SessionLocal()
        try:
            from app.models import ReplayRun
            run = ReplayRun(skill_id=1, mode="execute", status="running",
                            plan={"steps": [], "url": "http://t/",
                                  "executor_instructions": [
                                      {"seq": 1, "op": "detach"}],
                                  "executor_state": {"cursor": 0, "received": [],
                                                     "interventions": 0,
                                                     "overrides": {}}},
                            executor="extension")
            db.add(run); db.commit()
            rid = run.id
            # finish 带 fail + 定位失败证据（URL 在业务页=e3）
            resp = await client.post(f"/api/v1/executor/runs/{rid}/finish",
                json={"status": "fail", "summary": {
                    "executed": [{"kind": "click", "ok": False,
                                  "error": "semantic locate failed: '保存' @ http://127.0.0.1:8095/x"}],
                    "observed": []}})
            assert resp.status_code == 200
            db.expire_all()
            r = db.get(ReplayRun, rid)
            assert r.status == "fail"
            assert r.failure_class == "e3_drift"  # 主通道分类生效
        finally:
            from app.models import ReplayRun as RR
            db.query(RR).filter(RR.id == rid).delete()
            db.commit(); db.close()

    async def test_finish_login_fail_e1(self, client: AsyncClient):
        """登录态丢失（URL 落 login）→ e1_env（AJ2 守卫的分类基础）。"""
        db = SessionLocal()
        try:
            from app.models import ReplayRun
            run = ReplayRun(skill_id=1, mode="execute", status="running",
                            plan={"steps": [], "url": "http://t/",
                                  "executor_instructions": [{"seq": 1, "op": "detach"}],
                                  "executor_state": {"cursor": 0, "received": [],
                                                     "interventions": 0, "overrides": {}}},
                            executor="extension")
            db.add(run); db.commit()
            rid = run.id
            resp = await client.post(f"/api/v1/executor/runs/{rid}/finish",
                json={"status": "fail", "summary": {
                    "executed": [{"kind": "input", "ok": False,
                                  "error": "locate failed @ http://127.0.0.1:8093/login?redirect=/x"}],
                    "observed": []}})
            assert resp.status_code == 200
            db.expire_all()
            assert db.get(ReplayRun, rid).failure_class == "e1_env"
        finally:
            from app.models import ReplayRun as RR
            db.query(RR).filter(RR.id == rid).delete()
            db.commit(); db.close()
