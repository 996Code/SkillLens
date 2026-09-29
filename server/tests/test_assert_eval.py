from app.replay.assert_eval import evaluate_assertions, path_matches


def test_path_matches_templated():
    assert path_matches("http://h/orders/92382/save?x=1", "/orders/{id}/save") is True
    assert path_matches("http://h/orders/abc/save", "/orders/{id}/save") is False


def test_evaluate_api_status():
    assertions = [{"kind": "api_status", "payload": {"api_template": "/a/save", "expect_status": 200}}]
    observed = [{"url": "http://h/a/1/save", "status": 200, "body": ""},
                {"url": "http://h/other", "status": 500, "body": ""}]
    result = evaluate_assertions(assertions, observed)
    assert result[0]["passed"] is True and result[0]["observed_status"] == 200


def test_evaluate_api_status_missing():
    assertions = [{"kind": "api_status", "payload": {"api_template": "/a/save", "expect_status": 200}}]
    result = evaluate_assertions(assertions, [{"url": "http://h/b", "status": 200, "body": ""}])
    assert result[0]["passed"] is False and result[0]["observed_status"] is None


def test_evaluate_state_signal():
    assertions = [{"kind": "state_signal",
                   "payload": {"api_template": "/a/save", "field": "code", "expect_value": 200}}]
    observed = [{"url": "http://h/a/save", "status": 200, "body": '{"code":200,"data":{"state":"OK"}}'}]
    result = evaluate_assertions(assertions, observed)
    assert result[0]["passed"] is True


def _ui_text_payload():
    return {"label": "备注", "before": "旧值", "after": "新值"}


def _after_snapshot(value):
    return {"forms": [{"label": "备注", "value": value}], "labels": [], "tables": []}


def test_evaluate_ui_text_match():
    a = [{"kind": "ui_text", "payload": _ui_text_payload()}]
    r = evaluate_assertions(a, [], after_snapshot=_after_snapshot("新值"))
    assert r[0]["passed"] is True
    assert r[0]["observed_status"] is None


def test_evaluate_ui_text_mismatch():
    a = [{"kind": "ui_text", "payload": _ui_text_payload()}]
    r = evaluate_assertions(a, [], after_snapshot=_after_snapshot("别的值"))
    assert r[0]["passed"] is False


def test_evaluate_ui_text_no_snapshot_skipped():
    """回放无 after 快照（无采集能力）→ skipped（passed=True），不计失败。"""
    a = [{"kind": "ui_text", "payload": _ui_text_payload()}]
    r = evaluate_assertions(a, [])
    assert r[0]["passed"] is True
    assert r[0]["skipped"] == "ui_text 无回放快照，跳过"


def test_evaluate_ui_text_label_missing_fails():
    """快照存在但 label 缺失 → FAIL：字段消失是真实回归信号，不再吞掉。"""
    a = [{"kind": "ui_text", "payload": _ui_text_payload()}]
    r = evaluate_assertions(
        a, [], after_snapshot={"forms": [{"label": "其他", "value": "x"}],
                               "labels": [], "tables": []})
    assert r[0]["passed"] is False, r
    assert r[0]["skipped"] == "回放快照中字段缺失"


def test_evaluate_toast_signal_from_snapshot():
    """层1 toast 断言走 after 快照 toasts 通道（不走响应体）。"""
    from app.replay.assert_eval import evaluate_assertions
    assertions = [{"kind": "state_signal",
                    "payload": {"api_template": "/x/save", "field": "toast",
                                "expect_value": "保存成功"}}]
    # 快照含目标 toast → PASS
    r = evaluate_assertions(assertions, [{"url": "http://t/x/save", "status": 200, "body": ""}],
                            after_snapshot={"toasts": ["保存成功"]})
    assert r[0]["passed"] is True
    # 快照无该 toast → skipped（S37 语义修正：toast 瞬态，未捕获不判失败）
    r2 = evaluate_assertions(assertions, [{"url": "http://t/x/save", "status": 200, "body": ""}],
                             after_snapshot={"toasts": ["别的提示"]})
    assert r2[0]["passed"] is True and r2[0].get("skipped")
    # 无快照能力 → skipped（fail-open，不计失败）
    r3 = evaluate_assertions(assertions, [{"url": "http://t/x/save", "status": 200, "body": ""}],
                              after_snapshot=None)
    assert r3[0]["passed"] is True and r3[0].get("skipped")


def test_evaluate_toast_with_observed_toasts_channel():
    """S37 断言语义根治：toast 是瞬态元素，after 快照时机必然错过——
    回放期间轮询捕获的 toasts（observed_toasts）参与判定；
    两个通道都未观察到 → skipped（瞬态性本质，不产生假阴性）。"""
    assertions = [{"kind": "state_signal",
                   "payload": {"api_template": "/x/save", "field": "toast",
                               "expect_value": "保存成功"}}]
    observed = [{"url": "http://t/x/save", "status": 200, "body": ""}]
    # 轮询通道捕获到（快照错过）→ PASS
    r = evaluate_assertions(assertions, observed,
                            after_snapshot={"toasts": []},
                            observed_toasts=["保存成功"])
    assert r[0]["passed"] is True
    # 两通道都空 → skipped 而非 fail
    r2 = evaluate_assertions(assertions, observed,
                             after_snapshot={"toasts": []},
                             observed_toasts=[])
    assert r2[0]["passed"] is True
    assert "瞬态" in r2[0].get("skipped", "")
    # 快照通道命中（兼容旧路径）→ PASS
    r3 = evaluate_assertions(assertions, observed,
                             after_snapshot={"toasts": ["保存成功"]},
                             observed_toasts=[])
    assert r3[0]["passed"] is True
