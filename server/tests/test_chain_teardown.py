"""AI5 数据卫生：链 teardown（cleanup 步）+ unique 自动推荐。

- chain.steps 元素可带 "cleanup": {"docker": {"container": ..., "shell": ...}}
  ——链执行结束（无论成败）后执行（probes 同款 docker-exec 通道）
- GET /chains/{id}/recommend：分析链步骤的 fill 字段，对"疑似唯一字段"
  （原值匹配 sl_*/时间戳/编号模式）推荐 ${unique:} 规则
"""
import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Alignment, Scenario, Skill


async def _mk(db, name, fills=None):
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


class TestTeardown:
    async def test_cleanup_declared_and_persisted(self, client: AsyncClient):
        """cleanup 声明随链存储（执行侧消费——docker 通道与 probes 同款）。"""
        db = SessionLocal()
        try:
            sid = await _mk(db, "teardown 技能")
            r = await client.post("/api/v1/scenarios", json={
                "name": "teardown 链", "system": "x",
                "steps": [{
                    "skill_id": sid, "overrides": {},
                    "cleanup": {"docker": {"container": "jeecg-boot-mysql",
                                           "shell": "echo cleanup"}}}]})
            assert r.status_code == 201
            cid = r.json()["id"]
            one = await client.get(f"/api/v1/scenarios/{cid}")
            step = one.json()["steps"][0]
            assert step["cleanup"]["docker"]["container"] == "jeecg-boot-mysql"
        finally:
            db.query(Scenario).delete()
            db.query(Skill).filter(Skill.name == "teardown 技能").delete()
            db.commit()
            db.close()


class TestRecommend:
    async def test_recommend_unique_fields(self, client: AsyncClient):
        """唯一字段推荐：原值匹配 sl_ 前缀/长数字/时间戳形态的字段推荐
        ${unique:原前缀}。"""
        from app.replay.scenario_runner import recommend_unique_overrides
        fills = [
            {"name": "*表名", "value": "sl_form_a26513"},
            {"name": "*表描述", "value": "SL表单x"},
            {"name": "备注", "value": "普通文本"},
            {"name": "编号", "value": "12345678"},
        ]
        rec = recommend_unique_overrides(fills)
        assert rec == {"*表名": "${unique:sl_form_}", "编号": "${unique:}"}
