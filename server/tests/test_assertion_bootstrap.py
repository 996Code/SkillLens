"""P0-3 回放反哺断言（Dolibarr 断言 0→有的通用解）：经典表单系统
（Dolibarr 整页提交）录制侧 net-hook 只包 fetch/XHR 抓不到写请求，
而服务端回放 observed 走 Playwright 全响应捕获——从 pass run 的
observed 写响应引导 api_status 断言（确定性规则，无 LLM 判定，C3）。"""
import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Alignment, OutcomeAssertion, ReplayRun, Skill


async def _mk_skill(db, name="反哺技能"):
    al = Alignment(session_ids=[], skeleton=[{"signature": "click:保存"}],
                   buckets=[], input_variables=[], param_variables=[],
                   window_params={})
    db.add(al); db.flush()
    s = Skill(alignment_id=al.id, name=name, description="", status="learned",
              skeleton=[{"signature": "click:保存", "label": "保存"}],
              param_variables=[], input_variables=[],
              confidence=0.9, evidence_count=1)
    db.add(s); db.commit()
    return s


def _mk_run(db, skill_id, status, observed):
    run = ReplayRun(skill_id=skill_id, mode="execute", status=status,
                    plan={"steps": [], "observed": observed},
                    executed=[], assertion_results=[])
    db.add(run); db.commit()
    return run


class TestBootstrapFromRun:
    async def test_write_response_becomes_assertion(self, client: AsyncClient):
        """pass run 的写响应（含表单整页 POST）→ api_status 断言；
        GET 噪音与轮询查询型模板不进。"""
        db = SessionLocal()
        try:
            s = await _mk_skill(db)
            run = _mk_run(db, s.id, "pass", [
                {"url": "http://127.0.0.1:8080/societe/card.php?action=create",
                 "status": 200, "method": "GET", "body": ""},
                {"url": "http://127.0.0.1:8080/societe/card.php?action=create",
                 "status": 200, "method": "POST", "body": ""},
                {"url": "http://127.0.0.1:8080/index.php?m=message&f=ajaxGetMessage",
                 "status": 200, "method": "GET", "body": ""},
            ])
            r = await client.post(
                f"/api/v1/skills/{s.id}/assertions/from-run",
                json={"run_id": run.id})
            assert r.status_code == 200
            assert r.json()["assertions"] == 1
            rows = db.query(OutcomeAssertion).filter(
                OutcomeAssertion.skill_id == s.id).all()
            assert len(rows) == 1
            assert rows[0].kind == "api_status"
            assert rows[0].api_template == "/societe/card.php"
            assert rows[0].payload["expect_status"] == 200
        finally:
            db.query(OutcomeAssertion).delete()
            db.query(ReplayRun).delete()
            db.query(Skill).filter(Skill.name == "反哺技能").delete()
            db.commit(); db.close()

    async def test_dynamic_segment_normalized(self, client: AsyncClient):
        """动态 id 段归一 {id}——回放命中行≠录制行，路径漂移不假失败。"""
        db = SessionLocal()
        try:
            s = await _mk_skill(db)
            run = _mk_run(db, s.id, "pass", [
                {"url": "http://h/api/data/123456789012/save",
                 "status": 200, "method": "POST", "body": ""},
            ])
            r = await client.post(
                f"/api/v1/skills/{s.id}/assertions/from-run",
                json={"run_id": run.id})
            assert r.status_code == 200
            rows = db.query(OutcomeAssertion).filter(
                OutcomeAssertion.skill_id == s.id).all()
            assert rows[0].api_template == "/api/data/{id}/save"
        finally:
            db.query(OutcomeAssertion).delete()
            db.query(ReplayRun).delete()
            db.query(Skill).filter(Skill.name == "反哺技能").delete()
            db.commit(); db.close()

    async def test_fail_run_rejected(self, client: AsyncClient):
        """只从 pass run 引导——fail run 的响应是失败现场不是成功证据。"""
        db = SessionLocal()
        try:
            s = await _mk_skill(db)
            run = _mk_run(db, s.id, "fail", [
                {"url": "http://h/x", "status": 500, "method": "POST", "body": ""},
            ])
            r = await client.post(
                f"/api/v1/skills/{s.id}/assertions/from-run",
                json={"run_id": run.id})
            assert r.status_code == 409
        finally:
            db.query(OutcomeAssertion).delete()
            db.query(ReplayRun).delete()
            db.query(Skill).filter(Skill.name == "反哺技能").delete()
            db.commit(); db.close()

    async def test_run_of_other_skill_rejected(self, client: AsyncClient):
        db = SessionLocal()
        try:
            a = await _mk_skill(db)
            b = await _mk_skill(db, name="反哺技能B")
            run = _mk_run(db, b.id, "pass", [
                {"url": "http://h/x", "status": 200, "method": "POST", "body": ""},
            ])
            r = await client.post(
                f"/api/v1/skills/{a.id}/assertions/from-run",
                json={"run_id": run.id})
            assert r.status_code == 409
        finally:
            db.query(OutcomeAssertion).delete()
            db.query(ReplayRun).delete()
            db.query(Skill).filter(Skill.name.like("反哺技能%")).delete()
            db.commit(); db.close()

    async def test_dedupe_against_existing(self, client: AsyncClient):
        """同模板已有断言不重复建（幂等）。"""
        db = SessionLocal()
        try:
            s = await _mk_skill(db)
            db.add(OutcomeAssertion(
                skill_id=s.id, layer=3, kind="api_status",
                api_template="/societe/card.php",
                payload={"api_template": "/societe/card.php",
                         "expect_status": 200}))
            db.commit()
            run = _mk_run(db, s.id, "pass", [
                {"url": "http://127.0.0.1:8080/societe/card.php",
                 "status": 200, "method": "POST", "body": ""},
            ])
            r = await client.post(
                f"/api/v1/skills/{s.id}/assertions/from-run",
                json={"run_id": run.id})
            assert r.status_code == 200
            assert r.json()["assertions"] == 0
        finally:
            db.query(OutcomeAssertion).delete()
            db.query(ReplayRun).delete()
            db.query(Skill).filter(Skill.name == "反哺技能").delete()
            db.commit(); db.close()

    async def test_query_like_templates_excluded(self, client: AsyncClient):
        """查询型写调用（list_view/search 等轮询走 POST）不进——与
        generate_assertions 的排除词表同语义。"""
        db = SessionLocal()
        try:
            s = await _mk_skill(db)
            run = _mk_run(db, s.id, "pass", [
                {"url": "http://h/api/list_view", "status": 200,
                 "method": "POST", "body": ""},
                {"url": "http://h/api/search_link", "status": 200,
                 "method": "POST", "body": ""},
            ])
            r = await client.post(
                f"/api/v1/skills/{s.id}/assertions/from-run",
                json={"run_id": run.id})
            assert r.status_code == 200
            assert r.json()["assertions"] == 0
        finally:
            db.query(OutcomeAssertion).delete()
            db.query(ReplayRun).delete()
            db.query(Skill).filter(Skill.name == "反哺技能").delete()
            db.commit(); db.close()


class TestUnverifiedPassFlag:
    async def test_trends_marks_unverified_pass(self, client: AsyncClient):
        """空断言 pass 显性化：技能 0 断言时的 pass run 计入
        unverified_pass（假 pass 工厂可见，不混入 fail）。"""
        from datetime import datetime
        db = SessionLocal()
        try:
            s = await _mk_skill(db)
            db.add(ReplayRun(skill_id=s.id, mode="execute", status="pass",
                             plan={"steps": []}, executed=[],
                             assertion_results=[], created_at=datetime.utcnow()))
            db.commit()
            r = await client.get("/api/v1/skills/trends")
            assert r.status_code == 200
            body = r.json()
            hit = [a for a in body if a.get("unverified_pass")]
            assert hit, f"unverified_pass 未出现: {body}"
        finally:
            db.query(ReplayRun).delete()
            db.query(Skill).filter(Skill.name == "反哺技能").delete()
            db.commit(); db.close()
