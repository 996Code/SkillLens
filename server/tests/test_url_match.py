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


async def test_match_api(client):
    r = await client.get("/api/v1/adapters/match",
                         params={"url": "http://127.0.0.1:8095/online/cgform"})
    assert r.status_code == 200
    body = r.json()
    assert body["adapter_id"] == "jeecg"
