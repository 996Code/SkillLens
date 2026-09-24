def _api_of(value: str) -> tuple[str, str] | None:
    """"/a -> 200" 拆 (api, code)；非该形态返回 None。"""
    if " -> " not in value:
        return None
    api, _, code = value.partition(" -> ")
    return api.strip(), code.strip()


def classify_delta(expected_changes: list[dict], observed_items: list[dict],
                   baseline_ms: int = 0, observed_ms: int = 0) -> dict:
    expected: list[dict] = []
    missing: list[dict] = []
    unexpected: list[dict] = []
    drift: list[dict] = []

    obs_by_type: dict[str, list[dict]] = {}
    for o in observed_items:
        obs_by_type.setdefault(o["type"], []).append(o)

    matched_obs_ids: set[int] = set()  # 用 (type,value) 做身份
    obs_keys = [(o["type"], o["value"]) for o in observed_items]

    for e in expected_changes:
        pair = _api_of(e["value"])
        hit = None
        if e["type"] == "api_status" and pair:
            api, want_code = pair
            for o in obs_by_type.get("api_status", []):
                opair = _api_of(o["value"])
                if opair and opair[0] == api:
                    if opair[1] == want_code:
                        hit = o
                    else:
                        drift.append({"type": "api_status",
                                      "value": f"{api}: {want_code} -> {opair[1]}"})
                    break
        else:
            for o in obs_by_type.get(e["type"], []):
                if o["value"] == e["value"] or (
                        e["type"] == "ui_action" and (
                            e["value"] in o["value"] or o["value"] in e["value"])):
                    hit = o
                    break
        if hit is not None:
            expected.append(e)
            matched_obs_ids.add(obs_keys.index((hit["type"], hit["value"])))
        elif not (e["type"] == "api_status" and pair and any(
                d["value"].startswith(_api_of(e["value"])[0] + ":") for d in drift)):
            missing.append(e)

    for i, o in enumerate(observed_items):
        if i not in matched_obs_ids:
            # drift 项的 observed 对应条目不算 unexpected
            pair = _api_of(o["value"])
            if pair and any(d["value"].startswith(pair[0] + ":") for d in drift):
                continue
            unexpected.append(o)

    if baseline_ms and observed_ms and observed_ms > baseline_ms * 3:
        drift.append({"type": "timing", "value": f"耗时 {baseline_ms}ms -> {observed_ms}ms"})
    return {"expected": expected, "missing": missing,
            "unexpected": unexpected, "drift": drift}
