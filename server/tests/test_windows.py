from app.ingestion.windows import build_windows


def ev(seq, ts, kind, ptype=None, label="保存"):
    payload = {"type": ptype} if ptype else {}
    if ptype in ("click", "submit") and label is not None:
        payload["target"] = {"label": label}
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
        ev(1, 0, "action", "click", label="查询"),
        ev(2, 100, "network"),
        ev(3, 5000, "action", "submit", label="保存"),
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


def test_cross_tab_network_not_attached():
    """S42-12：跨标签页流量不入窗——录制会话期间其他标签页的后台轮询
    （禅道 ajaxGetMessage）会带活跃 session_id 混入事件流，被窗口吸收后
    污染 API 证据（Jeecg 技能学到 /index.php 断言，回放永假失败）。
    网络事件带 pageUrl（发出页面），与锚点页面不同源则不入窗。"""
    events = [
        _ev_t(1, 0, "action", "click", "保存"),
        {"seq": 2, "ts": 200, "kind": "network",
         "payload": {"method": "GET", "url": "/index.php?m=message",
                     "pageUrl": "http://zentao:8082/index.php"}},
        {"seq": 3, "ts": 300, "kind": "network",
         "payload": {"method": "POST", "url": "/jeecgboot/sys/dict/add",
                     "pageUrl": "http://jeecg:8095/system/dict"}},
    ]
    # 锚点页面是 jeecg
    events[0] = _ev_url(1, 0, "action", "click", "保存", "http://jeecg:8095/system/dict")
    windows = build_windows(events)
    assert [m["seq"] for m in windows[0]["members"]] == [3]


def _ev_url(seq, ts, kind, ptype, label, url):
    return {"seq": seq, "ts": ts, "kind": kind,
            "payload": {"type": ptype, "target": {"label": label}, "url": url}}


def test_same_page_network_attached_and_legacy_kept():
    """同源网络照常入窗；无 pageUrl 的旧格式事件兼容保留。"""
    events = [
        _ev_url(1, 0, "action", "click", "保存", "http://jeecg:8095/system/dict"),
        {"seq": 2, "ts": 200, "kind": "network",
         "payload": {"method": "POST", "url": "/api/save",
                     "pageUrl": "http://jeecg:8095/system/dict"}},
        {"seq": 3, "ts": 300, "kind": "network",
         "payload": {"method": "GET", "url": "/api/list"}},
    ]
    windows = build_windows(events)
    assert [m["seq"] for m in windows[0]["members"]] == [2, 3]


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
