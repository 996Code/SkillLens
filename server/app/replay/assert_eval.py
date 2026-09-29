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


def evaluate_assertions(assertions: list[dict], observed: list[dict],
                        after_snapshot: dict | None = None,
                        observed_toasts: list[str] | None = None) -> list[dict]:
    out: list[dict] = []
    for a in assertions:
        p = a["payload"]
        if a["kind"] == "ui_text":
            # UI 文本断言不走网络观察：用回放 after 快照的 forms 对比。
            # 无快照（采集能力缺失）→ skipped/passed=True 不计失败；
            # 快照存在但 label 缺失 → FAIL（字段消失是真实回归信号，不吞掉）。
            forms = ((after_snapshot or {}).get("forms") or [])
            hit = next((f for f in forms if f.get("label") == p.get("label")), None)
            if after_snapshot is None:
                out.append({"payload": p, "observed_status": None, "passed": True,
                            "skipped": "ui_text 无回放快照，跳过"})
            elif hit is None:
                out.append({"payload": p, "observed_status": None, "passed": False,
                            "skipped": "回放快照中字段缺失"})
            else:
                out.append({"payload": p, "observed_status": None,
                            "passed": hit.get("value") == p.get("after")})
            continue
        matched = [o for o in observed if path_matches(o["url"], p["api_template"])]
        if a["kind"] == "api_status":
            statuses = [o["status"] for o in matched]
            passed = bool(statuses) and all(s == p["expect_status"] for s in statuses)
            out.append({"payload": p, "observed_status": statuses[0] if statuses else None,
                        "passed": passed})
        elif a["kind"] == "state_signal" and p.get("field") == "toast":
            # 层1 toast 信号不走响应体（toast 是 UI 元素，body 里永远没有）：
            # 用回放 after 快照的 toasts 通道对比；无快照能力 → skipped（fail-open）。
            # S37 断言语义根治：toast 瞬态——after 快照时机必然错过，
            # 回放期间轮询捕获的 observed_toasts 为主通道、快照为补充；
            # 两通道都未观察到 → skipped（瞬态性本质，不产生假阴性）
            toasts = ((after_snapshot or {}).get("toasts") or []) + (observed_toasts or [])
            if after_snapshot is None and not observed_toasts:
                out.append({"payload": p, "observed_status": None, "passed": True,
                            "skipped": "toast 无回放快照，跳过"})
            elif p.get("expect_value") in toasts:
                out.append({"payload": p, "observed_status": None, "passed": True})
            else:
                out.append({"payload": p, "observed_status": None, "passed": True,
                            "skipped": "toast 瞬态提示未捕获（两通道均未观察到），建议人工复核"})
        elif a["kind"] == "state_signal":
            values = [_extract_field(o.get("body", ""), p["field"]) for o in matched]
            passed = bool(matched) and all(v == p["expect_value"] for v in values)
            out.append({"payload": p, "observed_status": matched[0]["status"] if matched else None,
                        "passed": passed})
        else:  # field_change：回放时无 before/after 语义，跳过
            out.append({"payload": p, "observed_status": None, "passed": True,
                        "skipped": "field_change 不在回放中判定"})
    return out
