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


def test_duplicate_observed_consumed_one_per_expected():
    """评审#8：list.index 永远返回首个匹配 → 重复 (type,value) 观测条目
    第二条永不被标记 matched。修复语义=逐条消费：两条相同 expected 各
    消费一条相同 observed → 全 matched，无 unexpected。"""
    exp = [{"type": "api_add", "value": "/a/save"},
           {"type": "api_add", "value": "/a/save"}]
    obs = [{"type": "api_add", "value": "/a/save"},
           {"type": "api_add", "value": "/a/save"}]
    r = classify_delta(exp, obs)
    assert len(r["expected"]) == 2
    assert r["unexpected"] == []
    assert r["missing"] == []


def test_duplicate_observed_single_expected_reports_extra():
    """一条 expected 只消费一条 observed——多出的重复条目是真实的
    额外发生（如重复提交），必须报 unexpected，不得静默吞掉。"""
    r = classify_delta([{"type": "api_add", "value": "/a/save"}],
                       [{"type": "api_add", "value": "/a/save"},
                        {"type": "api_add", "value": "/a/save"}])
    assert len(r["expected"]) == 1
    assert len(r["unexpected"]) == 1


def test_malformed_entries_recorded_not_raising():
    """评审#7：人工修订的 changes 原样保留（expected.py），缺 type/value
    的条目不得 KeyError 500——按 C3 记入 missing/unexpected 并带 reason，
    可见不吞。"""
    r = classify_delta(
        [{"type": "api_add"},                    # 缺 value
         {"value": "/a/save"},                   # 缺 type
         {"type": "api_add", "value": "/ok"}],
        [{"type": "api_add", "value": "/ok"},
         {"type": "api_add"}])                   # observed 缺 value
    assert len(r["expected"]) == 1
    assert len(r["missing"]) == 2
    assert all("reason" in m for m in r["missing"])
    assert len(r["unexpected"]) == 1
    assert "reason" in r["unexpected"][0]
