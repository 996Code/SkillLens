"""AF2 探针运行时：manifest 探针的确定性执行器（主计划块 AF2）。

探针是第一公民——同服务实体验证（AF5）、状态注入（换参前查最新实体）、
未来块 X 的 DB 断言。执行形态两种：
- docker-exec：宿主 docker exec（lesson #28：utf-8+replace；MSYS_NO_PATHCONV=1
  防路径转换）；输出按行/制表符切为元组行；
- http：httpx 请求+确定性断言（status/contains），返回布尔。

凭据红线：password 值只在运行时从 os.environ 取（清单只存变量名）。
"""
import asyncio
import os
import re
import subprocess
from pathlib import Path

import httpx

from app.adapters.manifest import Manifest, Probe


def interpolate(template: str, manifest: Manifest) -> str:
    """${base_url}/${username}/${password}/${env:VAR} 插值。"""
    cred = manifest.credentials
    out = template
    out = out.replace("${base_url}", manifest.target.base_url)
    out = out.replace("${username}", cred.username)
    if cred.password_env:
        out = out.replace("${password}", os.environ.get(cred.password_env, ""))
    elif cred.password_literal:
        out = out.replace("${password}", cred.password_literal)
    def _env(m):
        return os.environ.get(m.group(1), "")
    out = re.sub(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}", _env, out)
    return out


def _ensure_helper_scripts(container: str) -> None:
    """辅助脚本注入：adapters/scripts/*.sh → 指定容器 /opt/skilllens/（幂等）。
    复杂 shell（密码抽取等）不塞 manifest——设计原则①的 escape hatch。"""
    scripts_dir = Path(__file__).resolve().parent.parent.parent / "adapters" / "scripts"
    if not scripts_dir.is_dir():
        return
    subprocess.run(
        ["docker", "exec", container, "sh", "-c", "mkdir -p /opt/skilllens"],
        capture_output=True, timeout=30)
    for f in scripts_dir.glob("*.sh"):
        subprocess.run(
            ["docker", "cp", str(f), f"{container}:/opt/skilllens/{f.name}"],
            capture_output=True, timeout=30)


def _exec_docker(manifest: Manifest, probe: Probe) -> list[tuple]:
    _ensure_helper_scripts(probe.container or "")
    shell = interpolate(probe.shell or "", manifest)
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    out = subprocess.run(
        ["docker", "exec", probe.container or "", "sh", "-c", shell],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, env=env,
    ).stdout.strip()
    return [tuple(l.split("\t")) for l in out.splitlines() if l]


async def _exec_http(manifest: Manifest, probe: Probe) -> bool:
    req = probe.request
    url = interpolate(req.url, manifest)
    json_body = None
    if req.json_body is not None:
        json_body = {k: interpolate(str(v), manifest)
                     for k, v in req.json_body.items()}
    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.request(req.method, url, json=json_body)
    a = probe.probe_assert
    if a is None:
        return resp.status_code < 400
    if a.status is not None and resp.status_code != a.status:
        return False
    if a.contains is not None and a.contains not in resp.text:
        return False
    return True


def run_probe(manifest: Manifest, probe: Probe):
    if probe.kind == "docker-exec":
        return _exec_docker(manifest, probe)
    return asyncio.run(_exec_http(manifest, probe))


def parse_probe_output(raw: str, regex: str | None) -> str:
    if not regex:
        return raw
    m = re.search(regex, raw)
    return m.group(1) if m else ""


def compare_expect(expect: str, before, after) -> bool:
    if expect == "increased":
        def n(v):
            try:
                return int(str(v[0][0]))
            except (IndexError, ValueError, TypeError):
                return -1
        return n(after) > n(before)
    if expect == "equals":
        return before == after
    raise ValueError(f"未知 expect 语义: {expect}")
