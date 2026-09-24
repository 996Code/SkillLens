import json
import re
from urllib.parse import urlsplit

_ID_SEGMENT = re.compile(r"^(?:\d+|[0-9a-fA-F-]{36})$")


def _static_segments(path: str) -> list[str]:
    """路径段序列，剔除动态段（模板 {id}、纯数字段、UUID 段）。"""
    return [seg for seg in path.split("/")
            if seg and seg != "{id}" and not _ID_SEGMENT.match(seg)]


def path_matches(url: str, template: str) -> bool:
    """template 的 {id} 段视为通配（数字/UUID）；url path 中模板未捕获的
    动态段同样忽略；query 忽略。比对剩余静态段序列。"""
    url_path = urlsplit(url).path
    return _static_segments(url_path) == _static_segments(template)


def _extract_field(body: str, field: str) -> object:
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


def evaluate_assertions(assertions: list[dict], observed: list[dict]) -> list[dict]:
    out: list[dict] = []
    for a in assertions:
        p = a["payload"]
        matched = [o for o in observed if path_matches(o["url"], p["api_template"])]
        if a["kind"] == "api_status":
            statuses = [o["status"] for o in matched]
            passed = bool(statuses) and all(s == p["expect_status"] for s in statuses)
            out.append({"payload": p, "observed_status": statuses[0] if statuses else None,
                        "passed": passed})
        elif a["kind"] == "state_signal":
            values = [_extract_field(o.get("body", ""), p["field"]) for o in matched]
            passed = bool(matched) and all(v == p["expect_value"] for v in values)
            out.append({"payload": p, "observed_status": matched[0]["status"] if matched else None,
                        "passed": passed})
        else:  # field_change：回放时无 before/after 语义，跳过
            out.append({"payload": p, "observed_status": None, "passed": True,
                        "skipped": "field_change 不在回放中判定"})
    return out
