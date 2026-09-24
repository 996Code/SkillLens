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
