import json

from app.ingestion.signals import extract_state_signals


def test_top_level_status():
    body = json.dumps({"code": 200, "status": "APPROVED"})
    assert extract_state_signals(body) == [{"field": "status", "value": "APPROVED"}]


def test_nested_data_state():
    body = json.dumps({"data": {"state": "DRAFT", "id": 1}})
    assert extract_state_signals(body) == [{"field": "data.state", "value": "DRAFT"}]


def test_ignores_deep_and_non_scalar():
    body = json.dumps({"data": {"row": {"status": "x"}}, "state": {"nested": 1}})
    assert extract_state_signals(body) == []


def test_none_and_invalid():
    assert extract_state_signals(None) == []
    assert extract_state_signals("not json") == []
    assert extract_state_signals('{"status": 200}') == [{"field": "status", "value": 200}]
