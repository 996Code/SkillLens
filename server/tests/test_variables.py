from app.ingestion.variables import input_variables, param_variables


def ev(kind, payload, seq=0):
    return {"seq": seq, "ts": seq, "kind": kind, "payload": payload}


def test_param_variables_detects_changing_id():
    skeleton = [{"signature": "click:保存|POST:/orders/{id}/save", "session_window_seqs": {"s1": 0, "s2": 0}}]
    def win(order_id):
        return [{
            "anchor": {"seq": 0, "ts": 0, "kind": "action",
                       "payload": {"type": "click", "target": {"label": "保存"}}},
            "members": [ev("network", {"method": "POST", "url": f"/orders/{order_id}/save",
                                       "status": 200, "duration": 10, "reqBody": None, "resBody": ""})],
            "end_ts": 1,
        }]
    result = param_variables(skeleton, [("s1", win(111)), ("s2", win(222))])
    assert result == [{"step": "click:保存|POST:/orders/{id}/save",
                       "param": "id_0", "values": {"s1": "111", "s2": "222"}}]


def test_param_variables_constant_not_variable():
    skeleton = [{"signature": "click:保存|POST:/orders/{id}/save", "session_window_seqs": {"s1": 0, "s2": 0}}]
    def win():
        return [{
            "anchor": {"seq": 0, "ts": 0, "kind": "action",
                       "payload": {"type": "click", "target": {"label": "保存"}}},
            "members": [ev("network", {"method": "POST", "url": "/orders/111/save",
                                       "status": 200, "duration": 10, "reqBody": None, "resBody": ""})],
            "end_ts": 1,
        }]
    assert param_variables(skeleton, [("s1", win()), ("s2", win())]) == []


def test_input_variables_detects_values():
    s1 = [ev("action", {"type": "input", "name": "订单名", "value": "A"})]
    s2 = [ev("action", {"type": "input", "name": "订单名", "value": "B"})]
    result = input_variables([("s1", s1), ("s2", s2)])
    assert result == [{"name": "订单名", "values": {"s1": "A", "s2": "B"}, "positions": {"s1": 0, "s2": 0}}]


def test_input_variables_same_value_ignored():
    s1 = [ev("action", {"type": "input", "name": "备注", "value": "X"})]
    s2 = [ev("action", {"type": "input", "name": "备注", "value": "X"})]
    assert input_variables([("s1", s1), ("s2", s2)]) == []
