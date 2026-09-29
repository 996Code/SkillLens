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
    S34 多目标泛化：input 步按参考会话**事件时序**交错插入锚点之间
    （Odoo 等系统表单在锚点点击后才出现——New → 填名 → Save，
    一律前置会在表单出现前 fill 必然定位失败）；overrides 造出的
    无事件变量无时序信息，保持旧语义插在最前；
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

    var_by_name = {str(v.get("name") or ""): v for v in (input_variables or [])}
    known_vars: list[str] = []
    seen: set[str] = set()
    for name in var_by_name:
        if name and name not in seen:
            known_vars.append(name)
            seen.add(name)
    for name in overrides:
        if name and name not in seen:
            known_vars.append(name)
            seen.add(name)

    # 骨架 click 步（带窗口序号，用于事件时序定位）
    skel_steps: list[dict] = []
    for step in skeleton or []:
        wq = (step.get("session_window_seqs") or {}).get(ref_session_id)
        if wq is None or wq >= len(windows):
            continue
        payload = (windows[wq].get("anchor") or {}).get("payload") or {}
        if payload.get("type") not in ("click", "submit"):
            continue
        # S26：骨架步 healed label（自愈晋升回写）优先于录制时的 anchor label
        target = payload.get("target") or {}
        label = step.get("label") or target.get("label") or ""
        if label:
            skel_steps.append({"kind": "click", "label": label, "_wq": wq,
                               # S36 多信号：labels/tag/ordinal/path 透传给回放定位
                               "labels": target.get("labels") or [],
                               "tag": target.get("tag"),
                               "ordinal": target.get("ordinal"),
                               "path": target.get("path")})
    # 锚点事件 → 骨架步下标（按序消费）。按对象身份匹配：build_windows
    # 存的是同一批事件 dict 的引用（ts/seq 可能重号，身份唯一可靠）
    anchor_index: dict[int, int] = {}
    for idx, s in enumerate(skel_steps):
        a = windows[s["_wq"]].get("anchor")
        if a is not None:
            anchor_index[id(a)] = idx

    steps: list[dict] = []
    # 无事件且无变量记录的纯 overrides 变量：无时序信息，保持旧语义前置
    for name in known_vars:
        if name in event_inputs or name in var_by_name:
            continue
        steps.append({"kind": "input", "name": name,
                      "value": str(overrides.get(name, "")),
                      "original_value": ""})

    emitted_vars: set[str] = set()
    next_skel = 0
    for e in ordered:
        payload = e.get("payload") or {}
        if e.get("kind") == "action" and payload.get("type") == "input":
            name = payload.get("name") or ""
            if name in seen and name not in emitted_vars:
                var = var_by_name.get(name)
                original = _original_of(var) if var else event_inputs.get(name, "")
                tgt = payload.get("target") or {}
                steps.append({"kind": "input", "name": name,
                              "value": str(overrides.get(name, original)),
                              "original_value": original,
                              "labels": tgt.get("labels") or [],
                              "tag": tgt.get("tag"), "ordinal": tgt.get("ordinal"),
                              "path": tgt.get("path")})
                emitted_vars.add(name)
                continue
        idx = anchor_index.get(id(e))
        if idx is not None and idx == next_skel:
            s = skel_steps[idx]
            steps.append({"kind": "click", "label": s["label"],
                          "labels": s.get("labels") or [],
                          "tag": s.get("tag"), "ordinal": s.get("ordinal"),
                          "path": s.get("path")})
            next_skel += 1
    # 兜底：锚点事件缺失（窗口数据异常）时按序补齐 click 步
    while next_skel < len(skel_steps):
        s = skel_steps[next_skel]
        steps.append({"kind": "click", "label": s["label"],
                      "labels": s.get("labels") or [],
                      "tag": s.get("tag"), "ordinal": s.get("ordinal"),
                      "path": s.get("path")})
        next_skel += 1
    # 兜底：变量有记录但参考会话无其事件（跨会话值域）——按序尾补 input
    emitted_names = {s.get("name") for s in steps if s["kind"] == "input"}
    for name in known_vars:
        if name not in emitted_names:
            var = var_by_name.get(name)
            original = _original_of(var) if var else event_inputs.get(name, "")
            steps.append({"kind": "input", "name": name,
                          "value": str(overrides.get(name, original)),
                          "original_value": original})
    return {"url": _plan_url(ordered), "steps": steps}


_WRITE_METHODS = ("POST:", "PUT:", "PATCH:", "DELETE:")


def requires_confirmation(skill_skeleton: list[dict]) -> bool:
    """任一骨架窗口含写方法 API 即需确认（C1）。GET 查询无副作用不算。"""
    return any(any(m in (step.get("signature") or "") for m in _WRITE_METHODS)
               for step in skill_skeleton)
