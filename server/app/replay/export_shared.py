"""导出脚本共享判定逻辑（单一事实源，评审#1）。

exporter.py 把本文件源码**逐字内嵌**进生成的 Playwright 脚本（生成脚本
必须自包含、零 SkillLens 依赖）；服务端与导出脚本共用同一份文本——
消除手抄副本导致的判定漂移（导出脚本与工作台 PASS/FAIL 不一致会击穿
"确定性可审计"的产品主张）。

语义与 app/replay/assert_eval.py 对齐（该文件不在本轮修改范围，漂移由
tests/test_export.py 以 assert_eval 为基准比对 pattern/判定行为守护）：
- _ID_SEGMENT：S43-5 动态 id 段归一（{id} 模板/纯数字/UUID/长 hex ≥16）；
- judge_api_status：命中非空且**全部**等于期望（混合结果判 FAIL）；
- judge_state_signal：S42-7/S42-12 取最后一次写响应（无写取最后一次
  命中）的终态语义 + 若依 258 空 body 回退 HTTP status。

只允许依赖标准库（生成脚本独立运行）。
"""
import json
import re
from urllib.parse import urlsplit

_ID_SEGMENT = re.compile(r"^(?:\d+|[0-9a-fA-F-]{36}|[0-9a-fA-F]{16,})$")

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def static_segments(path):
    """路径段序列，剔除动态段（模板 {id}、纯数字段、UUID 段、长 hex 段）。"""
    return [seg for seg in path.split("/")
            if seg and seg != "{id}" and not _ID_SEGMENT.match(seg)]


def path_matches(url, template):
    """template 的 {id} 段视为通配（数字/UUID/长 hex）；url path 中模板
    未捕获的动态段同样忽略；query 规则与 assert_eval.path_matches 同源
    （P2-10：模板带 query 时 URL query 须同值全含；无 query 旧语义）。"""
    from urllib.parse import parse_qsl
    t_path, _, t_query = template.partition("?")
    parts = urlsplit(url)
    if static_segments(parts.path) != static_segments(t_path):
        return False
    if not t_query.strip():
        return True
    want = dict(parse_qsl(t_query))
    have = dict(parse_qsl(parts.query))
    return all(have.get(k) == v for k, v in want.items())


def extract_field(body, field):
    """响应体 JSON 按 a.b.c 路径取值；解析失败/路径缺失返回 None。"""
    try:
        node = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    for part in field.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def judge_api_status(hits, expect_status):
    """api_status 判定：命中非空且全部状态等于期望才通过（与 assert_eval
    的 all(s == expect) 同语义——混合结果判 FAIL，而非"有一个不等才 FAIL"）。"""
    statuses = [h.get("status") for h in hits]
    return bool(statuses) and all(s == expect_status for s in statuses)


def judge_state_signal(hits, field, expect_value):
    """state_signal 判定：取最后一次写响应（POST/PUT/PATCH/DELETE）为终态，
    无写响应回退最后一次命中（assert_eval S42-7/S42-12 同语义）；空 body
    且 field=code 时回退 HTTP status 判定（若依 258 铁证：logout 返回
    200 空 body——body 里永远没有 code 字段）。"""
    writes = [h for h in hits
              if str(h.get("method") or "").upper() in WRITE_METHODS]
    terminal = (writes or hits)[-1] if hits else None
    value = extract_field(terminal.get("body", ""), field) if terminal else None
    if (value is None and terminal
            and not (terminal.get("body") or "").strip()
            and field == "code"
            and str(expect_value) == str(terminal.get("status"))):
        value = terminal.get("status")
    return bool(hits) and value == expect_value
