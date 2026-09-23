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
