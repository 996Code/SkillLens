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


async def test_system_derivation_skips_error_pages(client):
    """P2-11 实证：首帧补发会把录制开始时的停留页记为首 navigation——
    若停留页是 njmind 网关 404（/404 结尾）会污染系统派生（Odoo 技能
    被标成 njmind）。错误页 navigation 跳过，取首条有效 navigation。"""
    import uuid
    from app.db import SessionLocal
    from app.models import RecordingSession, RawEvent, Alignment, Skill
    from app.system import skill_systems as ss
    db = SessionLocal()
    try:
        sid = str(uuid.uuid4())
        db.add(RecordingSession(id=sid, note="t-err-nav"))
        db.flush()
        for seq, url in ((0, "http://192.168.99.22/404"),
                         (1, "http://127.0.0.1:8069/web#action=x"),
                         (2, "http://127.0.0.1:8069/web#id=1")):
            db.add(RawEvent(session_id=sid, page_id="p", seq=seq, ts=seq,
                            kind="navigation", payload={"type": "page-load", "url": url}))
        al = Alignment(session_ids=[sid], skeleton=[], buckets=[],
                       input_variables=[], param_variables=[], window_params={})
        db.add(al); db.flush()
        sk = Skill(alignment_id=al.id, name="错误页派生技能", description="",
                   status="learned", skeleton=[], param_variables=[],
                   input_variables=[], confidence=0.9, evidence_count=1)
        db.add(sk); db.commit()
        got = ss(db, [sk.id]).get(sk.id)
        assert got == "Odoo 销售", got  # 404 页跳过，取 8069
    finally:
        db.query(Skill).filter(Skill.name == "错误页派生技能").delete()
        db.query(Alignment).filter(Alignment.session_ids == [sid] if False else True).filter(Alignment.id == al.id).delete()
        db.query(RawEvent).filter(RawEvent.session_id == sid).delete()
        db.query(RecordingSession).filter(RecordingSession.id == sid).delete()
        db.commit(); db.close()


async def test_system_derivation_majority_host(client):
    """P2-11 二轮实证：首帧补发把录制开始的跨系统停留页记为首 navigation
    （Odoo 页开录→goto ERPNext）——首条派生串系统。多数派 host 派生：
    navigation host 计数取众数（平票取最后——录制后段更接近真实目标）。"""
    import uuid
    from app.db import SessionLocal
    from app.models import RecordingSession, RawEvent, Alignment, Skill
    from app.system import skill_systems as ss
    db = SessionLocal()
    try:
        sid = str(uuid.uuid4())
        db.add(RecordingSession(id=sid, note="t-majority"))
        db.flush()
        navs = [(0, "http://127.0.0.1:8069/web"),      # 首帧补发（Odoo 停留页）
                (1, "http://127.0.0.1:8090/desk"),      # goto ERPNext
                (2, "http://127.0.0.1:8090/desk/customer/new-x")]
        for seq, url in navs:
            db.add(RawEvent(session_id=sid, page_id="p", seq=seq, ts=seq,
                            kind="navigation", payload={"type": "page-load", "url": url}))
        db.add(RawEvent(session_id=sid, page_id="p", seq=3, ts=3, kind="action",
                        payload={"type": "input", "target": {"label": "x"},
                                 "url": "http://127.0.0.1:8090/desk/customer/new-x"}))
        al = Alignment(session_ids=[sid], skeleton=[], buckets=[],
                       input_variables=[], param_variables=[], window_params={})
        db.add(al); db.flush()
        sk = Skill(alignment_id=al.id, name="多数派派生技能", description="",
                   status="learned", skeleton=[], param_variables=[],
                   input_variables=[], confidence=0.9, evidence_count=1)
        db.add(sk); db.commit()
        got = ss(db, [sk.id]).get(sk.id)
        assert got == "ERPNext 客户", got  # 多数派 8090 胜过首帧 8069
    finally:
        db.query(Skill).filter(Skill.name == "多数派派生技能").delete()
        db.query(Alignment).filter(Alignment.id == al.id).delete()
        db.query(RawEvent).filter(RawEvent.session_id == sid).delete()
        db.query(RecordingSession).filter(RecordingSession.id == sid).delete()
        db.commit(); db.close()
