from app.change.classify import classify_delta


def test_all_four_categories():
    expected_changes = [
        {"type": "ui_action", "value": "点击 保存"},          # 会命中
        {"type": "api_add", "value": "/a/save"},              # 会命中
        {"type": "ui_action", "value": "新增复制按钮"},        # 不命中 → missing
        {"type": "api_status", "value": "/a/save -> 200"},    # api 在但 500 → drift
    ]
    observed_items = [
        {"type": "ui_action", "value": "点击 保存"},
        {"type": "api_add", "value": "/a/save"},
        {"type": "api_status", "value": "/a/save -> 500"},
        {"type": "api_add", "value": "/a/export"},            # 无对应预期 → unexpected
    ]
    r = classify_delta(expected_changes, observed_items)
    assert {"type": "ui_action", "value": "点击 保存"} in r["expected"]
    assert {"type": "api_add", "value": "/a/save"} in r["expected"]
    assert {"type": "ui_action", "value": "新增复制按钮"} in r["missing"]
    assert {"type": "api_add", "value": "/a/export"} in r["unexpected"]
    assert any("/a/save" in d["value"] and "200" in d["value"] and "500" in d["value"]
               for d in r["drift"])
    # drift 的 api_status expected 项不再计入 expected/missing
    assert not any("-> 200" in e["value"] for e in r["expected"])
    assert not any("-> 200" in m["value"] for m in r["missing"])


def test_empty_edges():
    r = classify_delta([], [{"type": "api_add", "value": "/x"}])
    assert r["unexpected"] and not r["expected"] and not r["missing"]
    r2 = classify_delta([{"type": "api_add", "value": "/x"}], [])
    assert r2["missing"] and not r2["unexpected"]
