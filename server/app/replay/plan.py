from app.ingestion.windows import build_windows


def compile_replay_plan(events: list[dict], overrides: dict[str, str]) -> dict:
    url = ""
    url_from_action = ""
    steps: list[dict] = []
    for e in events:
        payload = e.get("payload") or {}
        if e["kind"] == "navigation" and not url:
            url = payload.get("url", "")
        if e["kind"] != "action":
            continue
        if not url_from_action and payload.get("url"):
            url_from_action = payload["url"]
        if payload.get("type") == "click":
            label = (payload.get("target") or {}).get("label") or ""
            if label:
                steps.append({"kind": "click", "label": label})
        elif payload.get("type") == "input":
            name = payload.get("name") or ""
            original = str(payload.get("value", ""))
            steps.append({"kind": "input", "name": name,
                          "value": str(overrides.get(name, original)),
                          "original_value": original})
    return {"url": url or url_from_action, "steps": steps}


def _plan_url(events: list[dict]) -> str:
    """URL 兜底链与 compile_replay_plan 一致：navigation 优先，否则 action.url。"""
    url = ""
    url_from_action = ""
    for e in events:
        payload = e.get("payload") or {}
        if e["kind"] == "navigation" and not url:
            url = payload.get("url", "")
        if e["kind"] != "action":
            continue
        if not url_from_action and payload.get("url"):
            url_from_action = payload["url"]
    return url or url_from_action


def compile_skeleton_plan(events: list[dict], skeleton: list[dict], ref_session_id: str,
                          overrides: dict[str, str],
                          input_variables: list[dict] | None = None) -> dict:
    """只编译骨架窗口内的 action：按 skeleton 步序，每步从该步
    session_window_seqs[ref_session_id] 指示的窗口取 anchor action；
    窗口内 members 不含 action，故步骤=各骨架窗的 anchor click/submit。
    变量注入（MVP 简化）：所有 input 变量统一插在第一个骨架步之前，
    顺序按 input_variables 列表序（overrides 里未覆盖的变量名随后补插，
    原值兜底取 events 中同名 input action 的首值）；
    value=overrides.get(name, 原首值)。"""
    ordered = sorted(events, key=lambda e: (e["ts"], e["seq"]))
    windows = build_windows(ordered)

    # 原值兜底表：参考 session 中各 input 字段的首次取值
    event_inputs: dict[str, str] = {}
    for e in ordered:
        payload = e.get("payload") or {}
        if e.get("kind") == "action" and payload.get("type") == "input":
            name = payload.get("name") or ""
            if name and name not in event_inputs:
                event_inputs[name] = str(payload.get("value", ""))

    def _original_of(var: dict) -> str:
        values = var.get("values") or {}
        val = values.get(ref_session_id)
        if val is None and values:
            val = next(iter(values.values()))
        return str(val if val is not None else event_inputs.get(var.get("name"), ""))

    steps: list[dict] = []
    seen: set[str] = set()
    for var in input_variables or []:
        name = str(var.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        original = _original_of(var)
        steps.append({"kind": "input", "name": name,
                      "value": str(overrides.get(name, original)),
                      "original_value": original})
    for name in overrides:
        if name in seen:
            continue
        seen.add(name)
        original = event_inputs.get(name, "")
        steps.append({"kind": "input", "name": name,
                      "value": str(overrides.get(name, original)),
                      "original_value": original})

    for step in skeleton or []:
        wq = (step.get("session_window_seqs") or {}).get(ref_session_id)
        if wq is None or wq >= len(windows):
            continue
        payload = (windows[wq].get("anchor") or {}).get("payload") or {}
        if payload.get("type") not in ("click", "submit"):
            continue
        label = (payload.get("target") or {}).get("label") or ""
        if label:
            steps.append({"kind": "click", "label": label})
    return {"url": _plan_url(ordered), "steps": steps}


_WRITE_METHODS = ("POST:", "PUT:", "PATCH:", "DELETE:")


def requires_confirmation(skill_skeleton: list[dict]) -> bool:
    """任一骨架窗口含写方法 API 即需确认（C1）。GET 查询无副作用不算。"""
    return any(any(m in (step.get("signature") or "") for m in _WRITE_METHODS)
               for step in skill_skeleton)
