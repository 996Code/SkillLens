"""三轮评审 F1/F2：viewer=只读契约的门控矩阵 + C1 确认门不可冒充。

F1 根因：角色门只覆盖 adapters PUT / locate_proposals / reviews / visual reset
四处，其余约 27 个变更端点仅挂 require_user——viewer 可直接触发真实浏览器
回放（对目标系统写数据）、执行开发计划、烧 LLM 配额，与文档宣称的
"viewer 只读"契约相反。

结构测试遍历路由依赖树而非逐端点造 body：既锁住当前矩阵，也让后续新增的
变更端点在漏挂门控时立刻红。
"""
import pytest

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# 设计上豁免写门控的变更端点（每条都有明确理由）。路径为 router 相对路径
# ——main.py 统一加 API_PREFIX(/api/v1)，遍历 original_router 时无前缀
EXEMPT = {
    ("POST", "/auth/login"),          # 匿名登录入口
    ("POST", "/auth/logout"),         # 只吊销所持 token，无越权面
    ("POST", "/sessions"),            # 插件采集通道（X-SkillLens-Agent 守卫）
    ("POST", "/sessions/{session_id}/events"),
    ("POST", "/adapters/validate"),   # 纯分析，不落盘不写库
    ("POST", "/adapters/fingerprint"),
    # 免登录换票（174bfb4）：PLUGIN_TRUST=1 时插件凭共享头换 admin token
    # ——匿名入口是设计本身（内部部署；默认关=公网零暴露）。角色门无意义：
    # 换到的就是 admin，不存在"viewer 越权"面（不开 PLUGIN_TRUST 时 403）。
    ("POST", "/auth/plugin-session"),
}


def _iter_api_routes():
    """app.routes 在当前 FastAPI 版本里是 _IncludedRouter 包装（路由挂在
    original_router 上）——两层都走，避免结构测试悄悄跑成空集假绿。"""
    from app.main import app
    for entry in app.routes:
        for r in getattr(getattr(entry, "original_router", None), "routes", None) or [entry]:
            yield r


def _collect_role_gates(dependant, out: set) -> None:
    for sub in getattr(dependant, "dependencies", None) or []:
        roles = getattr(getattr(sub, "call", None), "roles", None)
        if roles:
            out.add(tuple(roles))
        _collect_role_gates(sub, out)


def _route_gates():
    for r in _iter_api_routes():
        dependant = getattr(r, "dependant", None)
        if dependant is None:
            continue
        for m in (getattr(r, "methods", None) or set()) & WRITE_METHODS:
            roles: set = set()
            _collect_role_gates(dependant, roles)
            yield m, r.path, roles


def test_route_walk_is_not_vacuous():
    """守卫测试自身：路由遍历必须真的看到端点，否则下面两条恒绿无意义。"""
    live = {(m, p) for m, p, _ in _route_gates()}
    assert len(live) >= 40, f"只遍历到 {len(live)} 个变更端点，路由遍历方式已失效"
    assert ("POST", "/auth/login") in live


def test_every_mutating_route_blocks_viewer():
    ungated = sorted(f"{m} {p}" for m, p, roles in _route_gates()
                     if (m, p) not in EXEMPT
                     and not any("viewer" not in r for r in roles))
    assert not ungated, f"viewer 可达的变更端点（须挂 WRITE_GUARD）：{ungated}"


def test_exempt_list_has_no_stale_entries():
    live = {(m, p) for m, p, _ in _route_gates()}
    stale = sorted(f"{m} {p}" for m, p in EXEMPT if (m, p) not in live)
    assert not stale, f"豁免清单里的端点已不存在：{stale}"


@pytest.fixture
async def viewer_client(client):
    from httpx import ASGITransport, AsyncClient

    from app.auth import create_user, issue_token
    from app.db import SessionLocal
    from app.main import app
    db = SessionLocal()
    try:
        user = create_user(db, "r3-viewer", "viewer-pw-test-only", "viewer")
        token = issue_token(db, user.id)
    finally:
        db.close()
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as c:
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


@pytest.mark.parametrize("method,path", [
    ("post", "/api/v1/dev-plans/99999/execute"),
    ("post", "/api/v1/canvas/99999/run"),
    ("post", "/api/v1/sessions/no-such-session/process"),
    ("delete", "/api/v1/field-types/99999"),
    ("post", "/api/v1/skills/99999/replay"),
])
async def test_viewer_gets_403_not_404_on_write_endpoints(viewer_client, method, path):
    """门控在资源查找之前生效——viewer 拿到 403 而非 404（不泄漏资源存在性）。"""
    resp = await viewer_client.request(method.upper(), path, json={})
    assert resp.status_code == 403, resp.text


async def test_viewer_can_still_read(viewer_client):
    assert (await viewer_client.get("/api/v1/dashboard")).status_code == 200


async def test_viewer_cannot_confirm_dev_plan(viewer_client):
    """F2：C1 确认门曾把 reviewed_by 取自请求体——viewer 自报 admin 即可完成
    人工确认再触发执行，审计不可抵赖性失效。"""
    resp = await viewer_client.post("/api/v1/dev-plans/99999/confirm",
                                    json={"reviewed_by": "admin"})
    assert resp.status_code == 403


async def test_viewer_cannot_confirm_expected_delta(viewer_client):
    resp = await viewer_client.post("/api/v1/expected-deltas/99999/confirm",
                                    json={"reviewed_by": "admin"})
    assert resp.status_code == 403
