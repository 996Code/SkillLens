"""批回放 system 传递（禅道矩阵轮实证）：run_replay_batch 逐 skill 调
_execute_skill 时必须传 system——漏传则登录态不注入（_open_context 无
state）且 AJ2 登录守卫条件 `and system` 永假（40/40 error 根因）。"""
import pytest

from app.db import SessionLocal
from app.models import Alignment, Skill


async def _mk_skill(db, name="批回放技能"):
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


@pytest.mark.asyncio
async def test_batch_passes_system_per_skill(client, monkeypatch):
    import app.replay.runner as rm

    db = SessionLocal()
    try:
        s = await _mk_skill(db)
        captured = {}

        async def fake_execute(db_, browser_, skill_id_, overrides_,
                               confirm_, system=None):
            captured[skill_id_] = system
            class _R:  # 最小 run 替身（批只读 id/skill_id/status/mode）
                id, skill_id, status, mode = 1, skill_id_, "pass", "execute"
            return _R()

        def fake_launch():
            class _P:
                async def __aenter__(self): return self
                async def __aexit__(self, *a): return False
            return _P()

        async def fake_open_browser(p):
            class _B:
                async def close(self): pass
            return _B()

        async def fake_shadow(db_, sid, confirm_):
            return None

        monkeypatch.setattr(rm, "_execute_skill", fake_execute)
        monkeypatch.setattr(rm, "_launch", fake_launch)
        monkeypatch.setattr(rm, "_open_browser", fake_open_browser)
        monkeypatch.setattr(rm, "_shadow_run_if_gated", fake_shadow)
        runs = await rm.run_replay_batch(db, [s.id], {}, True)
        assert len(runs) == 1
        # system 必须按 skill 派生传入（None = 守卫失效+state 不注入）
        assert captured[s.id] is not None
    finally:
        db.query(Skill).filter(Skill.name == "批回放技能").delete()
        db.commit(); db.close()
