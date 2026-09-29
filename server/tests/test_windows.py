from app.ingestion.windows import build_windows


def ev(seq, ts, kind, ptype=None):
    payload = {"type": ptype} if ptype else {}
    return {"seq": seq, "ts": ts, "kind": kind, "payload": payload}


def test_click_then_post_in_same_window():
    events = [
        ev(0, 0, "navigation", "page-load"),
        ev(1, 100, "network"),
        ev(2, 1000, "action", "click"),
        ev(3, 1500, "network"),   # 距 anchor 500ms
        ev(4, 1700, "network"),   # 距上一网络 200ms
    ]
    windows = build_windows(events)
    assert len(windows) == 1
    assert windows[0]["anchor"]["seq"] == 2
    assert [m["seq"] for m in windows[0]["members"]] == [3, 4]
    assert windows[0]["end_ts"] == 1700


def test_idle_gap_closes_window():
    events = [
        ev(1, 1000, "action", "click"),
        ev(2, 1500, "network"),
        ev(3, 4500, "network"),   # 距上一网络 3000ms > IDLE_MS，关窗丢弃
    ]
    windows = build_windows(events)
    assert len(windows) == 1
    assert [m["seq"] for m in windows[0]["members"]] == [2]


def test_max_window_ms():
    events = [ev(1, 0, "action", "click"), ev(2, 9000, "network")]  # 超过 8000 上限
    assert [m["seq"] for m in build_windows(events)[0]["members"]] == []


def test_second_anchor_starts_new_window():
    events = [
        ev(1, 0, "action", "click"),
        ev(2, 100, "network"),
        ev(3, 5000, "action", "submit"),
        ev(4, 5100, "network"),
    ]
    windows = build_windows(events)
    assert [w["anchor"]["seq"] for w in windows] == [1, 3]
    assert [m["seq"] for m in windows[1]["members"]] == [4]


def test_input_events_ignored_as_anchor():
    events = [ev(1, 0, "action", "input"), ev(2, 100, "network")]
    assert build_windows(events) == []


def _ev_t(seq, ts, kind, ptype, label=None):
    payload = {"type": ptype}
    if label is not None:
        payload["target"] = {"label": label}
    return {"seq": seq, "ts": ts, "kind": kind, "payload": payload}


def test_submit_same_label_as_click_anchor_not_new_window():
    """S35：表单提交的 click+submit 双计——同一按钮先 click 后 submit
    （同 label），submit 不另开窗（同一用户动作），否则骨架出现重复步、
    回放第二次点击时页面已离开必失败。"""
    events = [
        _ev_t(1, 0, "action", "click", "创建第三方"),
        _ev_t(2, 500, "action", "submit", "创建第三方"),
        ev(3, 600, "network"),
    ]
    windows = build_windows(events)
    assert [w["anchor"]["seq"] for w in windows] == [1]
    assert [m["seq"] for m in windows[0]["members"]] == [3]


def test_submit_different_label_still_new_window():
    events = [
        _ev_t(1, 0, "action", "click", "按钮A"),
        _ev_t(2, 500, "action", "submit", "表单B"),
        ev(3, 600, "network"),
    ]
    windows = build_windows(events)
    assert [w["anchor"]["seq"] for w in windows] == [1, 2]
