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

from app.adapters.manifest import Manifest, Probe, _CONTAINER_PATTERN
from app.sanitize import sanitize_error

# 评审三轮 #2 防御层：schema pattern 之外的运行时复验——程序化构造的
# manifest（model_construct）不得绕过 docker argv 选项注入面
_CONTAINER_RE = re.compile(_CONTAINER_PATTERN)


def _check_container(container: str) -> None:
    if not _CONTAINER_RE.match(container or ""):
        raise ValueError(
            f"非法 container 名（docker argv 选项注入面）: {container!r}")


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


def _run_docker(cmd: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """docker 子进程统一出口：非零 rc 必抛（评审三轮 #3——曾只读 stdout，
    容器名错/脚本缺/SQL 报错全被吞成"空输出=通过"）；stderr 摘要经
    sanitize_error 脱敏（URL/主机不落日志与库）。"""
    res = subprocess.run(cmd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace", timeout=timeout)
    if res.returncode != 0:
        detail = sanitize_error((res.stderr or "").strip())[:200]
        raise RuntimeError(
            f"docker 命令失败 rc={res.returncode}: {' '.join(cmd[:3])}… {detail}")
    return res


def _ensure_helper_scripts(container: str) -> None:
    """辅助脚本注入：adapters/scripts/*.sh → 指定容器 /opt/skilllens/（幂等）。
    复杂 shell（密码抽取等）不塞 manifest——设计原则①的 escape hatch。"""
    _check_container(container)
    scripts_dir = Path(__file__).resolve().parent.parent.parent / "adapters" / "scripts"
    if not scripts_dir.is_dir():
        return
    _run_docker(["docker", "exec", container, "sh", "-c",
                 "mkdir -p /opt/skilllens"])
    for f in scripts_dir.glob("*.sh"):
        _run_docker(["docker", "cp", str(f),
                     f"{container}:/opt/skilllens/{f.name}"])


def _exec_docker(manifest: Manifest, probe: Probe) -> list[tuple]:
    _check_container(probe.container or "")
    _ensure_helper_scripts(probe.container or "")
    shell = interpolate(probe.shell or "", manifest)
    env = {**os.environ, "MSYS_NO_PATHCONV": "1"}
    res = subprocess.run(
        ["docker", "exec", probe.container or "", "sh", "-c", shell],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60, env=env,
    )
    if res.returncode != 0:
        detail = sanitize_error((res.stderr or "").strip())[:200]
        raise RuntimeError(
            f"探针 {probe.id} docker exec 失败 "
            f"rc={res.returncode}: {detail}")
    out = (res.stdout or "").strip()
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


def _empty_observation(v) -> bool:
    """观测空值判定：None/空行集/空串视为"命令无产出"（死探针信号）。
    bool False 是 http 探针的合法观测值——不算空。"""
    if v is None:
        return True
    if isinstance(v, str):
        return v == ""
    return hasattr(v, "__len__") and len(v) == 0


def compare_expect(expect: str, before, after) -> bool:
    if expect == "increased":
        def n(v):
            try:
                return int(str(v[0][0]))
            except (IndexError, ValueError, TypeError):
                return -1
        return n(after) > n(before)
    if expect == "equals":
        # 评审三轮 #3：空观测（容器名错/脚本缺/SQL 报错 → 无产出）不得判
        # "状态一致"——[] == [] 曾让死探针静默通过。仓内存量清单无
        # "期望空"合法用例（equals 全部前后实体对比），空即 False。
        if _empty_observation(before) or _empty_observation(after):
            return False
        return before == after
    raise ValueError(f"未知 expect 语义: {expect}")
