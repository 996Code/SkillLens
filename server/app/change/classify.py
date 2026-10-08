def _api_of(value: str) -> tuple[str, str] | None:
    """"/a -> 200" 拆 (api, code)；非该形态返回 None。"""
    if not isinstance(value, str) or " -> " not in value:
        return None
    api, _, code = value.partition(" -> ")
    return api.strip(), code.strip()


def _well_formed(item) -> bool:
    """人工修订的 changes 原样保留（change/expected.py），元素可能缺
    type/value 甚至不是 dict——畸形条目不参与匹配，按 C3 带 reason 记入
    missing/unexpected（可见不吞），不得 KeyError 500。"""
    return isinstance(item, dict) and item.get("type") is not None \
        and item.get("value") is not None


def _malformed_entry(item, bucket_note: str) -> dict:
    base = dict(item) if isinstance(item, dict) else {"value": repr(item)}
    base["reason"] = f"畸形条目（缺 type/value），未参与匹配：{bucket_note}"
    return base


def classify_delta(expected_changes: list[dict], observed_items: list[dict]) -> dict:
    expected: list[dict] = []
    missing: list[dict] = []
    unexpected: list[dict] = []
    drift: list[dict] = []

    obs_by_type: dict[str, list[dict]] = {}
    for o in observed_items:
        if _well_formed(o):
            obs_by_type.setdefault(o["type"], []).append(o)

    # 评审#8：按对象身份消费 matched 条目——list.index 对重复 (type,value)
    # 永远返回首个，第二条重复观测永不被标记 matched 而误报 unexpected
    matched_ids: set[int] = set()

    for e in expected_changes:
        if not _well_formed(e):
            missing.append(_malformed_entry(e, "计入 missing"))
            continue
        pair = _api_of(e["value"])
        hit = None
        if e["type"] == "api_status" and pair:
            api, want_code = pair
            for o in obs_by_type.get("api_status", []):
                if id(o) in matched_ids:
                    continue
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
                if id(o) in matched_ids:
                    continue
                if o["value"] == e["value"] or (
                        e["type"] == "ui_action" and (
                            e["value"] in o["value"] or o["value"] in e["value"])):
                    hit = o
                    break
        if hit is not None:
            expected.append(e)
            matched_ids.add(id(hit))
        elif not (e["type"] == "api_status" and pair and any(
                d["value"].startswith(_api_of(e["value"])[0] + ":") for d in drift)):
            missing.append(e)

    for o in observed_items:
        if not _well_formed(o):
            unexpected.append(_malformed_entry(o, "计入 unexpected"))
            continue
        if id(o) in matched_ids:
            continue
        # drift 项的 observed 对应条目不算 unexpected
        pair = _api_of(o["value"])
        if pair and any(d["value"].startswith(pair[0] + ":") for d in drift):
            continue
        unexpected.append(o)

    return {"expected": expected, "missing": missing,
            "unexpected": unexpected, "drift": drift}
