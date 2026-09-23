import json
import re

STATE_KEY = re.compile(r"^(status|state)$", re.I)


def extract_state_signals(res_body: str | None) -> list[dict]:
    if not res_body:
        return []
    try:
        data = json.loads(res_body)
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[dict] = []

    def walk(node: object, path: str) -> None:
        if not isinstance(node, dict) or path.count(".") >= 1:
            return
        for k, v in node.items():
            if STATE_KEY.match(k) and isinstance(v, (str, int, bool)):
                out.append({"field": f"{path}.{k}".lstrip("."), "value": v})
            elif isinstance(v, dict):
                # 与 field 组装一致地剥掉前导点，避免根路径 ".data" 被误判为已嵌套一层
                walk(v, f"{path}.{k}".lstrip("."))

    walk(data, "")
    return out
