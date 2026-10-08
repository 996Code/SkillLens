"""P2.5 URL 通配符匹配（油猴 @match 语义）：adapter.url_matches 声明 →
goto URL 自动定位系统（组件/链路/画像自动配对+隔离）。

油猴语义：* 通配任意段；精确 host:port 优先于通配；无声明=不参与匹配。
"""
import pytest

from app.adapters.manifest import load_manifest_text
from app.adapters.urlmatch import match_adapter, url_pattern_match


def _manifest(url_matches):
    doc = f"""
id: demo
target: {{base_url: "http://fallback"}}
credentials: {{username: u, password_literal: p}}
url_matches: {url_matches}
"""
    m, _ = load_manifest_text(doc)
    return m


def test_exact_port_match():
    m = _manifest('["http://127.0.0.1:8095/*"]')
    assert url_pattern_match("http://127.0.0.1:8095/online/cgform", m.url_matches[0])
    assert not url_pattern_match("http://127.0.0.1:8096/other", m.url_matches[0])


def test_wildcard_host():
    m = _manifest('["http://*.mycompany.com/*"]')
    assert url_pattern_match("http://erp.mycompany.com/sales/order", m.url_matches[0])
    assert not url_pattern_match("http://othercompany.net/x", m.url_matches[0])


def test_match_adapter_picks_most_specific():
    """多清单命中同一 URL——模式越长（ specificity ）越优先（油猴同语义：
    具体规则胜过通配）。"""
    m1 = _manifest('["http://*.local/*"]')
    m1.id = "generic-local"
    m2 = _manifest('["http://127.0.0.1:8095/*"]')
    m2.id = "jeecg"
    hit = match_adapter("http://127.0.0.1:8095/online/cgform", [m1, m2])
    assert hit is not None and hit.id == "jeecg"


def test_match_adapter_none():
    m1 = _manifest('["http://a.local/*"]')
    assert match_adapter("http://b.other/x", [m1]) is None


def test_no_declaration_excluded():
    """无 url_matches 的存量清单不参与匹配（显式声明制）。"""
    doc = """
id: legacy
target: {base_url: "http://old"}
credentials: {username: u, password_literal: p}
"""
    m, _ = load_manifest_text(doc)
    assert m.url_matches == []
    assert match_adapter("http://old/x", [m]) is None


def test_host_wildcard_no_cross_boundary_spoof():
    """评审三轮 #5a：host 段 `*` 曾编译为 `.*`——可跨 `/`、`.` 边界，
    `http://evil.com/.example.com/x` 伪装命中 `http://*.example.com/*`。
    host 段必须收敛为单 label（[^./]*）。"""
    pat = "http://*.example.com/*"
    assert not url_pattern_match("http://evil.com/.example.com/x", pat)
    assert not url_pattern_match("http://evil.com/x.example.com/y", pat)
    assert not url_pattern_match("http://a.b.example.com/x", pat)
    # 合法单子域照常命中
    assert url_pattern_match("http://erp.example.com/sales/order", pat)


def test_path_wildcard_still_crosses_slash():
    """路径段 `*` 保持油猴语义（跨 `/`）——5a 只收敛 host 段。"""
    assert url_pattern_match("http://h:1/a/b/c", "http://h:1/*")
    assert url_pattern_match("http://h/app/online/cgform?id=3", "http://h/app/*")


def test_query_pattern_never_matches_but_lints():
    """评审三轮 #5b（选定方案：query 保持剥离+loader lint 警示）——
    含 `?` 的模式按油猴语义永不命中，作者必须收到警告而非静默失效。"""
    assert not url_pattern_match("http://x/app", "http://x/app?a=1")
    doc = """
id: q
target: {base_url: "http://x"}
credentials: {username: u, password_literal: p}
url_matches: ["http://x/app?a=1"]
"""
    _, lints = load_manifest_text(doc)
    assert any(l.code == "url_match_query" for l in lints)


def test_equal_specificity_resolves_by_manifest_id():
    """评审三轮 #5c：同 specificity 曾按迭代序（文件名序）偶中——
    收敛为确定性 (specificity desc, manifest id asc)。"""
    m1 = _manifest('["http://tie.local/*"]')
    m1.id = "zzz"
    m2 = _manifest('["http://tie.local/*"]')
    m2.id = "aaa"
    assert match_adapter("http://tie.local/x", [m1, m2]).id == "aaa"
    assert match_adapter("http://tie.local/x", [m2, m1]).id == "aaa"


async def test_match_api(client):
    r = await client.get("/api/v1/adapters/match",
                         params={"url": "http://127.0.0.1:8095/online/cgform"})
    assert r.status_code == 200
    body = r.json()
    assert body["adapter_id"] == "jeecg"


async def test_match_api_requires_auth(client):
    """安全红线（评审实锤）：/adapters/match 挂鉴权守卫——插件侧裸 fetch
    401 静默回退 njmind 曾致 P2.5 配对失效。守卫语义必须保持，插件侧带 Bearer。"""
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app),
                           base_url="http://test") as bare:
        r = await bare.get("/api/v1/adapters/match",
                           params={"url": "http://127.0.0.1:8095/x"})
        assert r.status_code == 401
