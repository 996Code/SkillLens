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


def requires_confirmation(skill_skeleton: list[dict]) -> bool:
    return any("POST:" in (step.get("signature") or "") for step in skill_skeleton)
