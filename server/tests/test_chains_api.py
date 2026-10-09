"""AH1 链（chain）数据层 API 测试：链=纯数据（steps JSON），插件空间组链的存储。

- POST /chains（WRITE_GUARD：viewer 403）
- GET /chains（列表，?system= 过滤）
- GET /chains/{id}（详情）
- DELETE /chains/{id}（WRITE_GUARD）
- steps 结构校验（skill_id 必须存在、overrides 值含 ${unique:} 规则字符串）
"""
import pytest
from httpx import AsyncClient

from app.main import app
from app.db import SessionLocal
from app.models import Alignment, Chain, Skill


@pytest.fixture
def chain_client(client: AsyncClient):
    yield client


async def _mk_skill(db, name="链测试技能", system="JeecG 表单") -> int:
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


async def test_create_list_get_delete_chain(chain_client):
    db = SessionLocal()
    try:
        sid = await _mk_skill(db)
        r = await chain_client.post("/api/v1/chains", json={
            "name": "JeecG 建表单+建字典",
            "system": "JeecG 表单",
            "steps": [
                {"skill_id": sid, "overrides": {"*表名称": "${unique:sl_form_}"}},
                {"skill_id": sid, "overrides": {}},
            ],
        })
        assert r.status_code == 201, r.text
        cid = r.json()["id"]
        assert r.json()["steps"][0]["overrides"]["*表名称"] == "${unique:sl_form_}"

        lst = await chain_client.get("/api/v1/chains")
        assert any(c["id"] == cid for c in lst.json())

        # ?system= 过滤
        lst2 = await chain_client.get("/api/v1/chains?system=JeecG%20表单")
        assert any(c["id"] == cid for c in lst2.json())
        lst3 = await chain_client.get("/api/v1/chains?system=Odoo%20销售")
        assert not any(c["id"] == cid for c in lst3.json())

        one = await chain_client.get(f"/api/v1/chains/{cid}")
        assert one.status_code == 200
        assert one.json()["name"] == "JeecG 建表单+建字典"
        assert len(one.json()["steps"]) == 2

        # 详情带技能概要（空间小窗渲染用）
        steps = one.json()["steps"]
        assert steps[0]["skill"]["id"] == sid
        assert steps[0]["skill"]["name"] == "链测试技能"
        # AI2 防呆：fill_fields 候选键集（lesson #49：override key=录制的
        # input 事件 name——空骨架技能无 input，空列表合法；有 input 的
        # 技能必须列出 name+首值）
        assert "fill_fields" in steps[0]["skill"]
        assert isinstance(steps[0]["skill"]["fill_fields"], list)

        d = await chain_client.delete(f"/api/v1/chains/{cid}")
        assert d.status_code == 200
        assert (await chain_client.get(f"/api/v1/chains/{cid}")).status_code == 404
    finally:
        for s in db.query(Skill).filter(Skill.name == "链测试技能").all():
            db.query(Alignment).filter(Alignment.id == s.alignment_id).delete()
            db.delete(s)
        db.query(Chain).delete()
        db.commit()
        db.close()


async def test_chain_validation(chain_client):
    db = SessionLocal()
    try:
        sid = await _mk_skill(db)
        # 空 steps 拒绝
        r = await chain_client.post("/api/v1/chains", json={
            "name": "空链", "system": "x", "steps": []})
        assert r.status_code == 422
        # skill_id 不存在拒绝（防悬空引用——技能删除后链不可静默失效）
        r2 = await chain_client.post("/api/v1/chains", json={
            "name": "悬空链", "system": "x",
            "steps": [{"skill_id": 999999, "overrides": {}}]})
        assert r2.status_code == 422
        assert "999999" in r2.text
        return sid
    finally:
        db.query(Chain).delete()
        db.commit()
        db.close()


async def test_chain_role_gates(chain_client):
    """viewer=只读契约：POST/DELETE 挂 WRITE_GUARD。"""
    db = SessionLocal()
    try:
        sid = await _mk_skill(db)
        # client fixture 登录身份是 admin（conftest），先建一条
        r = await chain_client.post("/api/v1/chains", json={
            "name": "角色链", "system": "x",
            "steps": [{"skill_id": sid, "overrides": {}}]})
        assert r.status_code == 201
        cid = r.json()["id"]
        db.close()

        # viewer 身份
        from app.api.auth import hash_password
        from app.models import User, AuthToken
        import secrets
        db2 = SessionLocal()
        u = User(username="chain_viewer", role="viewer",
                 password_hash=hash_password("pw-chain-viewer"))
        db2.add(u)
        db2.flush()
        raw = secrets.token_urlsafe(24)
        from datetime import datetime, timedelta
        db2.add(AuthToken(user_id=u.id, token_hash=__import__("hashlib").sha256(
            raw.encode()).hexdigest(),
            expires_at=datetime.utcnow() + timedelta(days=1)))
        db2.commit()
        db2.close()

        hdr = {"Authorization": f"Bearer {raw}"}
        r2 = await chain_client.post("/api/v1/chains", headers=hdr, json={
            "name": "viewer 链", "system": "x",
            "steps": [{"skill_id": sid, "overrides": {}}]})
        assert r2.status_code == 403
        r3 = await chain_client.delete(f"/api/v1/chains/{cid}", headers=hdr)
        assert r3.status_code == 403
        # 只读可看
        r4 = await chain_client.get("/api/v1/chains", headers=hdr)
        assert r4.status_code == 200
    finally:
        db = SessionLocal()
        for s in db.query(Skill).filter(Skill.name == "链测试技能").all():
            db.query(Alignment).filter(Alignment.id == s.alignment_id).delete()
            db.delete(s)
        db.query(Chain).delete()
        db.query(User).filter(User.username == "chain_viewer").delete()
        db.commit()
        db.close()


async def test_chain_step_row_anchor_from(chain_client):
    """AN 跨步状态传递：步骤声明 row_anchor_from（前序步 pickedRow 注入
    本步行锚——选择类输出→输入）。schema 校验 ge=1；存储往返保真。"""
    db = SessionLocal()
    try:
        sid = await _mk_skill(db)
        r = await chain_client.post("/api/v1/chains", json={
            "name": "Snipe 查找→更新（行锚注入）",
            "system": "Snipe 资产",
            "steps": [
                {"skill_id": sid, "overrides": {}},
                {"skill_id": sid, "overrides": {}, "row_anchor_from": 1},
            ],
        })
        assert r.status_code == 201, r.text
        steps = r.json()["steps"]
        assert steps[1]["row_anchor_from"] == 1
        # 非法值（0）拒绝
        r2 = await chain_client.post("/api/v1/chains", json={
            "name": "x", "system": "s",
            "steps": [{"skill_id": sid, "overrides": {}},
                      {"skill_id": sid, "overrides": {}, "row_anchor_from": 0}],
        })
        assert r2.status_code == 422
    finally:
        db.close()
