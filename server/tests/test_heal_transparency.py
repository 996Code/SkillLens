"""AJ4 自愈透明度（mabl 三件套落地）：晋升 diff+置信面板+一键回滚。"""
import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Alignment, LocateProposal, Skill


async def _mk(db, name="透明度技能"):
    al = Alignment(session_ids=[], skeleton=[{"signature": "click:保存"}],
                   buckets=[], input_variables=[], param_variables=[],
                   window_params={})
    db.add(al); db.flush()
    s = Skill(alignment_id=al.id, name=name, description="", status="learned",
              skeleton=[{"signature": "click:保存", "label": "旧标签"}],
              param_variables=[], input_variables=[],
              confidence=0.9, evidence_count=1)
    db.add(s); db.commit()
    return s


class TestPromotionDiff:
    async def test_diff_view(self, client: AsyncClient):
        """晋升 diff：旧标签→新标签+归因理由+verify 计数——supersede 链
        的呈现层（mabl 元素历史版本表对应物）。"""
        db = SessionLocal()
        try:
            s = await _mk(db)
            prop = LocateProposal(
                skill_id=s.id, step_label="保存", proposed_label="提交表单",
                status="proposed", strategy="page_text",
                verify_count=3, source_run_id=None)
            db.add(prop); db.commit()
            r = await client.get(f"/api/v1/skills/{s.id}/diff")
            assert r.status_code == 200
            body = r.json()
            assert body[0]["step_label"] == "保存"
            assert body[0]["proposed_label"] == "提交表单"
            assert body[0]["verify_count"] == 3
            assert "旧标签" in str(body[0].get("current_label", ""))
        finally:
            db.query(LocateProposal).delete()
            db.query(Skill).filter(Skill.name == "透明度技能").delete()
            db.commit(); db.close()


class TestConfidencePanel:
    async def test_confidence(self, client: AsyncClient):
        """置信面板：verify 计数明细+LLM 归因理由；低置信只告警不晋升
        （mabl Find Summary 语义——低置信直接失败不硬愈）。"""
        db = SessionLocal()
        try:
            s = await _mk(db)
            db.add(LocateProposal(
                skill_id=s.id, step_label="保存", proposed_label="新标签",
                status="proposed", strategy="page_text", verify_count=1))
            db.commit()
            r = await client.get(f"/api/v1/skills/{s.id}/confidence")
            assert r.status_code == 200
            body = r.json()
            # verify_count=1 < 阈值 3 → low_confidence=True（只告警）
            assert body[0]["low_confidence"] is True
            assert body[0]["verify_count"] == 1
            assert body[0]["threshold"] >= 3
        finally:
            db.query(LocateProposal).delete()
            db.query(Skill).filter(Skill.name == "透明度技能").delete()
            db.commit(); db.close()


class TestRollback:
    async def test_rollback_to_previous_version(self, client: AsyncClient):
        """一键回滚：supersede 链回滚到指定前版本（含失效后续版本语义——
        mabl 时钟图标回滚对应物，但我们是技能级版本链业界独有）。"""
        db = SessionLocal()
        try:
            v1 = await _mk(db, "回滚技能 v1")
            v2 = Skill(alignment_id=v1.alignment_id, name="回滚技能 v2",
                       description="", status="learned",
                       skeleton=[{"signature": "click:保存", "label": "新标签"}],
                       param_variables=[], input_variables=[],
                       confidence=0.9, evidence_count=1,
                       version=2, superseded_by=None)
            v1.status = "superseded"; v1.superseded_by = None
            db.add(v2); db.commit()
            v1.superseded_by = v2.id
            db.commit()
            # 回滚：v2 失效（archived），v1 复活（learned）
            r = await client.post(f"/api/v1/skills/{v2.id}/rollback")
            assert r.status_code == 200
            db.expire_all()
            v1r, v2r = db.get(Skill, v1.id), db.get(Skill, v2.id)
            assert v1r.status == "learned"
            assert v2r.status == "archived"  # 失效后续版本
        finally:
            db.query(LocateProposal).delete()
            db.query(Skill).filter(Skill.name.like("回滚技能%")).delete()
            db.commit(); db.close()
