"""AF2 探针运行时（TDD：主计划块 AF2）。

验收语义：
- docker-exec 探针：subprocess docker exec（encoding utf-8 errors replace——
  lesson #28；MSYS_NO_PATHCONV 由实现层统一注入），输出行→元组；
- http 探针：request（method/url/json）+assert（status/contains）→ 命中布尔；
- 变量插值：${base_url}/${username}/${password}/${env:VAR}（凭据经环境变量
  注入——password_env 的值永不入清单，运行时从 os.environ 取）；
- parse_regex：输出正则抽取（bench 探针取 "name": "..."）；
- expect 语义：increased（前后探针对比）/ equals。
"""
from pathlib import Path

import pytest

from app.adapters.manifest import load_manifest_text
from app.adapters.probes import interpolate, run_probe, compare_expect


def _manifest():
    doc = """
id: t
target: {base_url: "http://127.0.0.1:9999"}
credentials: {username: admin, password_env: T_PW}
probes:
  - id: cnt
    kind: docker-exec
    container: c1
    shell: 'mysql -N -e "SELECT COUNT(*)"'
  - id: login_ok
    kind: http
    request: {method: POST, url: "${base_url}/login", json: {u: "${username}", p: "${password}"}}
    assert: {status: 200, contains: token}
"""
    m, _ = load_manifest_text(doc)
    return m


def test_interpolate_env_and_context():
    import os
    os.environ["T_PW"] = "secret-value"
    m = _manifest()
    out = interpolate("${username}:${password}@${base_url}", m)
    assert out == "admin:secret-value@http://127.0.0.1:9999"
    # env:VAR 形态
    assert interpolate("v=${env:T_PW}", m) == "v=secret-value"


def test_run_probe_docker_exec(monkeypatch):
    m = _manifest()
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw))
        class R:
            stdout = "3\n"
            returncode = 0
        return R()

    import app.adapters.probes as P
    monkeypatch.setattr(P, "_ensure_helper_scripts", lambda c: None)
    monkeypatch.setattr(P.subprocess, "run", fake_run)
    rows = run_probe(m, m.probes[0])
    assert rows == [("3",)]
    # lesson #28：subprocess 必须 utf-8 + errors replace
    cmd, kw = calls[0]
    assert kw.get("encoding") == "utf-8" and kw.get("errors") == "replace"


def test_run_probe_http(monkeypatch):
    m = _manifest()
    import os
    monkeypatch.setenv("T_PW", "secret-value")
    seen = {}

    class FakeResp:
        status_code = 200
        text = '{"token": "abc"}'

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def request(self, method, url, json=None):
            seen.update({"method": method, "url": url, "json": json})
            return FakeResp()

    import app.adapters.probes as P
    monkeypatch.setattr(P.httpx, "AsyncClient", FakeClient)
    import asyncio
    ok = asyncio.run(P._exec_http(m, m.probes[1]))
    assert ok is True
    assert seen["method"] == "POST" and seen["url"] == "http://127.0.0.1:9999/login"
    assert seen["json"] == {"u": "admin", "p": "secret-value"}


def test_parse_regex_extracts():
    m = _manifest()
    # parse_regex 语义：从原始输出抽取首捕获组
    from app.adapters.probes import parse_probe_output
    assert parse_probe_output('[(\'"name": "SAL-00021",)', r'"name": "(.+?)"') == "SAL-00021"


def test_compare_expect():
    before = [("3",)]
    after = [("4",)]
    assert compare_expect("increased", before, after) is True
    assert compare_expect("increased", before, [("3",)]) is False
    assert compare_expect("equals", [("4",)], [("4",)]) is True


def test_compare_expect_equals_empty_observed_false():
    """评审三轮 #3：空观测（死探针/容器名错/脚本报错 → stdout 空）不得
    判 equals 通过——[] == [] 曾让断链静默"状态一致"。"""
    assert compare_expect("equals", [], []) is False
    assert compare_expect("equals", [("4",)], []) is False
    assert compare_expect("equals", [], [("4",)]) is False
    assert compare_expect("equals", None, None) is False
    assert compare_expect("equals", [("4",)], [("4",)]) is True


def test_exec_docker_raises_on_nonzero_returncode(monkeypatch):
    """评审三轮 #3：returncode != 0 必须抛错（带 rc+脱敏 stderr 摘要），
    不得吞错返回空行集。"""
    m = _manifest()
    import app.adapters.probes as P
    monkeypatch.setattr(P, "_ensure_helper_scripts", lambda c: None)

    class R:
        stdout = ""
        stderr = "Error: connect http://internal.example.invalid/db refused"
        returncode = 3

    monkeypatch.setattr(P.subprocess, "run", lambda *a, **k: R())
    with pytest.raises(RuntimeError) as ei:
        run_probe(m, m.probes[0])
    msg = str(ei.value)
    assert "3" in msg
    # 安全红线：URL/主机名不得原样进异常文本（sanitize_error 收口）
    assert "http://" not in msg and "internal.example.invalid" not in msg


def test_ensure_helper_scripts_raises_on_failure(monkeypatch):
    """docker cp/mkdir 失败同样不得静默（脚本缺失 → 探针假通过链）。"""
    import app.adapters.probes as P

    class R:
        stdout = ""
        stderr = "permission denied"
        returncode = 1

    monkeypatch.setattr(P.subprocess, "run", lambda *a, **k: R())
    with pytest.raises(RuntimeError, match="docker"):
        P._ensure_helper_scripts("c1")


def test_container_guard_rejects_option_like_name(monkeypatch):
    """评审三轮 #2 防御层：绕过 schema 的程序化构造（model_construct）也
    必须在 subprocess 之前被拦——`-` 开头即 docker 选项注入面。"""
    import app.adapters.probes as P
    from app.adapters.manifest import Manifest, Probe, Target, Credentials

    calls = []
    monkeypatch.setattr(P.subprocess, "run", lambda *a, **k: calls.append(a))
    probe = Probe.model_construct(id="x", kind="docker-exec",
                                  container="--user=0", shell="id")
    m = Manifest.model_construct(
        id="t", target=Target(base_url="http://t"),
        credentials=Credentials(username="u", password_env="P"), probes=[probe])
    with pytest.raises(ValueError, match="container"):
        P._exec_docker(m, probe)
    with pytest.raises(ValueError, match="container"):
        P._ensure_helper_scripts("-x")
    assert not calls
