"""AI4 库治理：批量归档（supersede 语义复用）+ 系统通过率趋势。

- POST /skills/bulk-archive {ids: [..]}：批量归档（status=archived——
  新状态，不物理删；列表/执行端点排除 archived）
- GET /skills/trends：按系统聚合最近 30 天 pass 率趋势（dashboard 卡）
"""
import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Alignment, ReplayRun, Skill


async def _mk(db, name, status="learned"):
    al = Alignment(session_ids=[], skeleton=[], buckets=[],
                   input_variables=[], param_variables=[], window_params={})
    db.add(al)
    db.flush()
    s = Skill(alignment_id=al.id, name=name, description="", status=status,
              skeleton=[], param_variables=[], input_variables=[],
              confidence=0.9, evidence_count=1)
    db.add(s)
    db.commit()
    return s.id


class TestBulkArchive:
    async def test_archive_and_exclusion(self, client: AsyncClient):
        """归档：status=archived；技能列表与 executor 列表排除。"""
        db = SessionLocal()
        try:
            sid = await _mk(db, "归档测试技能")
            r = await client.post("/api/v1/skills/bulk-archive", json={"ids": [sid]})
            assert r.status_code == 200
            assert r.json()["archived"] == 1
            # 列表排除
            lst = await client.get("/api/v1/skills")
            assert not any(s["id"] == sid for s in lst.json())
            ex = await client.get("/api/v1/executor/skills")
            assert not any(s["id"] == sid for s in ex.json())
        finally:
            db.query(Skill).filter(Skill.name == "归档测试技能").delete()
            db.commit()
            db.close()

    async def test_archive_role_gate(self, client: AsyncClient):
        """viewer 只读：归档是写操作——403。"""
        from app.api.auth import hash_password
        from app.models import User, AuthToken
        import secrets, hashlib
        from datetime import datetime, timedelta
        db = SessionLocal()
        try:
            sid = await _mk(db, "角色归档技能")
            u = User(username="arch_viewer", role="viewer",
                     password_hash=hash_password("pw-arch"))
            db.add(u); db.flush()
            raw = secrets.token_urlsafe(24)
            db.add(AuthToken(user_id=u.id,
                             token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                             expires_at=datetime.utcnow() + timedelta(days=1)))
            db.commit()
            resp = await client.post("/api/v1/skills/bulk-archive",
                                     headers={"Authorization": f"Bearer {raw}"},
                                     json={"ids": [sid]})
            assert resp.status_code == 403
        finally:
            db.query(User).filter(User.username == "arch_viewer").delete()
            db.query(Skill).filter(Skill.name == "角色归档技能").delete()
            db.commit()
            db.close()


class TestTrends:
    async def test_trends_shape(self, client: AsyncClient):
        """趋势卡：按系统聚合 pass/fail 计数（无数据系统不出现）。"""
        r = await client.get("/api/v1/skills/trends")
        assert r.status_code == 200
        body = r.json()
        assert isinstance(body, list)
        for row in body:
            assert {"system", "total", "pass", "fail"} <= set(row.keys())
