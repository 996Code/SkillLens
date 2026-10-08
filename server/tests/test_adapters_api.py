"""AF6 清单管理 API（TDD）：工作台读/校验/保存 adapters/*.yaml。

- GET /adapters → 清单列表（id/label/base_url/probes/chains 计数+lints）
- POST /adapters/validate → YAML 文本校验（不落盘）——向导实时反馈
- PUT /adapters/{id} → 保存（校验通过才写盘；password_literal 保留 lint）
"""
import pytest
from pathlib import Path

from fastapi.testclient import TestClient


@pytest.fixture
def adapter_client(tmp_path: Path, monkeypatch):
    """独立 app+临时 adapters 目录（不碰真实清单）+登录 token。"""
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    import os
    d = tmp_path / "adapters"
    d.mkdir()
    (d / "t1.yaml").write_text("""
id: t1
label: 测试系统
target: {base_url: "http://t:1"}
credentials: {username: u, password_env: T_PW}
login:
  steps: [{goto: /login}]
probes:
  - id: p1
    kind: http
    request: {method: GET, url: "${base_url}/x"}
    assert: {status: 200}
chains:
  - name: c1
    rounds: 2
    skills: ["1"]
""", encoding="utf-8")
    import importlib
    import app.api.adapters as api_mod
    importlib.reload(api_mod)
    monkeypatch.setattr(api_mod, "ADAPTERS_DIR", d)
    from app.main import app
    from app.db import SessionLocal, engine
    from app.models import Base, User
    from app.auth import hash_password
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    db.add(User(username="af6", password_hash=hash_password("pw"), role="admin"))
    db.commit()
    db.close()
    c = TestClient(app)
    tok = c.post("/api/v1/auth/login",
                 json={"username": "af6", "password": "pw"}).json().get("token")
    c.headers["Authorization"] = f"Bearer {tok}"
    yield c


def test_list_adapters(adapter_client):
    r = adapter_client.get("/api/v1/adapters")
    assert r.status_code == 200
    items = r.json()
    assert items[0]["id"] == "t1"
    assert items[0]["label"] == "测试系统"
    assert items[0]["probe_count"] == 1
    assert items[0]["chain_count"] == 1
    assert items[0]["lints"] == []


def test_validate_yaml_ok(adapter_client):
    r = adapter_client.post("/api/v1/adapters/validate", json={
        "yaml": "id: x\ntarget: {base_url: 'http://x'}\n"
                "credentials: {username: u, password_env: X}\n"})
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_validate_yaml_bad(adapter_client):
    r = adapter_client.post("/api/v1/adapters/validate", json={
        "yaml": "id: x\ntarget: {base_url: 'http://x'}\n"
                "credentials: {username: u}\n"})  # 凭据缺失
    assert r.status_code == 200
    assert r.json()["valid"] is False
    assert r.json()["error"]


def test_validate_yaml_syntax_error(adapter_client):
    r = adapter_client.post("/api/v1/adapters/validate", json={
        "yaml": "id: [unclosed"})
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_put_adapter_saves(adapter_client):
    r = adapter_client.put("/api/v1/adapters/t1", json={
        "yaml": "id: t1\nlabel: 改后\ntarget: {base_url: 'http://t:2'}\n"
                "credentials: {username: u, password_env: T_PW}\n"})
    assert r.status_code == 200
    # 落盘校验
    import app.api.adapters as api_mod
    saved = (api_mod.ADAPTERS_DIR / "t1.yaml").read_text(encoding="utf-8")
    assert "改后" in saved


def test_put_adapter_invalid_rejected(adapter_client):
    r = adapter_client.put("/api/v1/adapters/t1", json={
        "yaml": "id: t1\ntarget: {base_url: 'http://t:2'}\n"
                "credentials: {username: u}\n"})  # 无凭据
    assert r.status_code == 422


def test_get_yaml_redacts_secrets(adapter_client):
    """评审三轮 #1（安全红线）：GET /adapters/{id}/yaml 原文回显——
    password_literal 泄漏给所有登录用户（含 viewer）。响应必须脱敏，
    但保留 id 等非秘密结构（前端编辑器仍可用）。"""
    import app.api.adapters as api_mod
    (api_mod.ADAPTERS_DIR / "t2.yaml").write_text(
        'id: t2\nlabel: 泄漏演示\ntarget: {base_url: "http://t:2"}\n'
        'credentials: {username: u, password_literal: "Sup3rS3cret"}\n',
        encoding="utf-8")
    r = adapter_client.get("/api/v1/adapters/t2/yaml")
    assert r.status_code == 200
    body = r.json()["yaml"]
    assert "Sup3rS3cret" not in body
    assert "***" in body
    assert "t2" in body


def test_put_round_trip_preserves_masked_secret(adapter_client):
    """脱敏回显的回归面（评审三轮 #1 后续）：GET 拿到的是 password_literal: '***'，
    编辑器只改 label 就 PUT 时，掩码必须回填磁盘旧值——否则一次无关编辑就把
    演示容器口令写成 "***"，登录静默失败且无从排查。"""
    import app.api.adapters as api_mod
    (api_mod.ADAPTERS_DIR / "t3.yaml").write_text(
        'id: t3\nlabel: 原名\ntarget: {base_url: "http://t:3"}\n'
        'credentials: {username: u, password_literal: "Sup3rS3cret"}\n',
        encoding="utf-8")
    echoed = adapter_client.get("/api/v1/adapters/t3/yaml").json()["yaml"]
    assert "Sup3rS3cret" not in echoed

    r = adapter_client.put("/api/v1/adapters/t3",
                           json={"yaml": echoed.replace("原名", "改名")})
    assert r.status_code == 200, r.text
    saved = (api_mod.ADAPTERS_DIR / "t3.yaml").read_text(encoding="utf-8")
    assert "Sup3rS3cret" in saved, "掩码被写回清单，凭据已销毁"
    assert "改名" in saved


def test_put_explicit_secret_overrides_mask(adapter_client):
    """用户在编辑器里显式改写凭据 → 以新值为准（回填只针对仍是掩码的键）。"""
    import re

    import app.api.adapters as api_mod
    (api_mod.ADAPTERS_DIR / "t4.yaml").write_text(
        'id: t4\nlabel: L\ntarget: {base_url: "http://t:4"}\n'
        'credentials: {username: u, password_literal: "OldPass1"}\n',
        encoding="utf-8")
    echoed = adapter_client.get("/api/v1/adapters/t4/yaml").json()["yaml"]
    edited = re.sub(r"(password_literal:\s*)\S+", r"\1'NewPass9'", echoed)
    assert "NewPass9" in edited
    r = adapter_client.put("/api/v1/adapters/t4", json={"yaml": edited})
    assert r.status_code == 200, r.text
    saved = (api_mod.ADAPTERS_DIR / "t4.yaml").read_text(encoding="utf-8")
    assert "NewPass9" in saved and "OldPass1" not in saved


def test_adapter_id_traversal_rejected(adapter_client):
    """安全红线（全量评审）：adapter_id 拼文件路径——Windows 反斜杠穿越
    （%5C 解码后单段命中路由）必须被白名单字符校验拦截。"""
    import app.api.adapters as api_mod
    d = api_mod.ADAPTERS_DIR
    r = adapter_client.get("/api/v1/adapters/..%5C..%5Capp/yaml")
    assert r.status_code == 422
    r2 = adapter_client.put("/api/v1/adapters/..%5C..%5Cevil", json={
        "yaml": "id: evil\ntarget: {base_url: 'http://e:1'}\n"
                "credentials: {username: u, password_env: E_PW}\n"})
    assert r2.status_code == 422
    assert not (d.parent / "evil.yaml").exists()


def test_put_adapter_requires_write_role(adapter_client, monkeypatch):
    """评审 #3：清单写盘可触发 docker-exec 探针——viewer 只读 403，
    reviewer/admin 可写。"""
    from app.db import SessionLocal
    from app.models import User
    from app.auth import hash_password, issue_token

    db = SessionLocal()
    try:
        db.add(User(username="af6-viewer", password_hash=hash_password("pw"),
                    role="viewer"))
        db.commit()
        viewer = db.query(User).filter_by(username="af6-viewer").first()
        vtok = issue_token(db, viewer.id)
    finally:
        db.close()

    body = {"yaml": "id: t1\ntarget: {base_url: 'http://t:1'}\n"
                    "credentials: {username: u, password_env: T_PW}\n"}
    old = adapter_client.headers["Authorization"]
    adapter_client.headers["Authorization"] = f"Bearer {vtok}"
    try:
        r = adapter_client.put("/api/v1/adapters/t1", json=body)
        assert r.status_code == 403
    finally:
        adapter_client.headers["Authorization"] = old
