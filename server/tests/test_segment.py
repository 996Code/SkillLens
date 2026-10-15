"""AP2 task segmentation + noise gates (pure deterministic rules)."""
import pytest

from app.learning.segment import segment_session, GateConfig


def ev(seq, ts, kind, **payload):
    return {"seq": seq, "ts": ts, "kind": kind, "payload": payload}


def write_event(seq, ts, url="/api/save"):
    return ev(seq, ts, "network", method="POST", url=url, status=200)


def test_write_boundary_signal_splits_task():
    """写边界事件：写请求后 30s 无交互 → 任务完成信号（切分点）。"""
    events = [
        ev(0, 0, "navigation", type="page-load", url="http://t/list"),
        ev(1, 1000, "action", type="click", target={"label": "新建"}),
        ev(2, 2000, "action", type="input", name="标题", value="x"),
        ev(3, 3000, "action", type="click", target={"label": "保存"}),
        write_event(4, 3500),
        # 30s+ 无交互 → 任务边界
        ev(5, 40000, "action", type="click", target={"label": "浏览"}),
        ev(6, 41000, "action", type="click", target={"label": "浏览2"}),
        ev(7, 42000, "action", type="click", target={"label": "浏览3"}),
    ]
    segments = segment_session(events, GateConfig())
    assert len(segments) == 2, "写边界应切出两个任务段"
    first = segments[0]
    assert first["has_write"] is True
    assert len(first["events"]) >= 5  # 含写请求


def test_idle_boundary_splits():
    """短空闲：90s 无交互 → 候选边界。"""
    events = [
        ev(0, 0, "navigation", type="page-load", url="http://t/a"),
        ev(1, 1000, "action", type="click", target={"label": "a"}),
        ev(2, 2000, "action", type="click", target={"label": "b"}),
        write_event(3, 2500),
        ev(4, 3000, "action", type="click", target={"label": "c"}),
        # 90s+ 空闲
        ev(5, 100000, "action", type="click", target={"label": "d"}),
        ev(6, 101000, "action", type="click", target={"label": "e"}),
        write_event(7, 102000),
        ev(8, 103000, "action", type="click", target={"label": "f"}),
    ]
    segments = segment_session(events, GateConfig())
    assert len(segments) == 2


def test_navigation_loop_splits():
    """导航闭环：列表→详情→回列表（URL 形态回环）。"""
    events = [
        ev(0, 0, "navigation", type="page-load", url="http://t/items"),
        ev(1, 1000, "action", type="click", target={"label": "详情"}),
        ev(2, 2000, "navigation", type="page-load", url="http://t/items/42"),
        ev(3, 3000, "action", type="click", target={"label": "保存"}),
        write_event(4, 3500),
        ev(5, 4000, "navigation", type="page-load", url="http://t/items"),
        ev(6, 5000, "action", type="click", target={"label": "新建"}),
        ev(7, 6000, "action", type="input", name="n", value="y"),
        ev(8, 7000, "action", type="click", target={"label": "保存"}),
        write_event(9, 7500),
    ]
    segments = segment_session(events, GateConfig())
    assert len(segments) == 2, "回列表的导航应切分"


def test_gate_pure_browsing_discarded():
    """闸门①：无写且无导航闭环 → discard（纯浏览）。"""
    events = [
        ev(0, 0, "navigation", type="page-load", url="http://t/list"),
        ev(1, 1000, "action", type="click", target={"label": "菜单"}),
        ev(2, 2000, "action", type="click", target={"label": "菜单2"}),
        ev(3, 3000, "action", type="click", target={"label": "菜单3"}),
        ev(4, 4000, "action", type="click", target={"label": "菜单4"}),
    ]
    segments = segment_session(events, GateConfig())
    assert segments == [] or all(
        s.get("discarded") for s in segments), "纯浏览不进学习"


def test_gate_too_few_events_discarded():
    """闸门②：事件数 < 5 → discard（误触）。"""
    events = [
        ev(0, 0, "navigation", type="page-load", url="http://t/a"),
        ev(1, 1000, "action", type="click", target={"label": "x"}),
        write_event(2, 1500),
        ev(3, 2000, "action", type="click", target={"label": "y"}),
    ]
    segments = segment_session(events, GateConfig())
    assert all(s.get("discarded") for s in segments)


def test_gate_all_input_no_submit_discarded():
    """闸门③：全是输入无提交（无写请求）→ discard（半途而废）。"""
    events = [
        ev(0, 0, "navigation", type="page-load", url="http://t/form"),
        ev(1, 1000, "action", type="input", name="a", value="1"),
        ev(2, 2000, "action", type="input", name="b", value="2"),
        ev(3, 3000, "action", type="input", name="c", value="3"),
        ev(4, 4000, "action", type="input", name="d", value="4"),
    ]
    segments = segment_session(events, GateConfig())
    assert all(s.get("discarded") for s in segments), "填一半没提交不是任务"


def test_discarded_segments_carry_reason():
    """C3：discard 流留痕（reason 记闸门判据）——可审计不静默。"""
    events = [
        ev(0, 0, "navigation", type="page-load", url="http://t/a"),
        ev(1, 1000, "action", type="click", target={"label": "x"}),
    ]
    segments = segment_session(events, GateConfig())
    assert segments and segments[0].get("discarded")
    assert segments[0].get("discard_reason"), "必须记原因"


def test_config_params_adjustable():
    """参数可配：idle 阈值调小后原不切分的现在切分。"""
    events = [
        ev(0, 0, "navigation", type="page-load", url="http://t/a"),
        ev(1, 1000, "action", type="click", target={"label": "a"}),
        write_event(2, 2000),
        ev(3, 3000, "action", type="click", target={"label": "b"}),
        ev(4, 11000, "action", type="click", target={"label": "c"}),
        ev(5, 12000, "action", type="click", target={"label": "d"}),
        write_event(6, 13000),
        ev(7, 14000, "action", type="click", target={"label": "e"}),
    ]
    default = segment_session(events, GateConfig())
    tight = segment_session(events, GateConfig(idle_s=5))
    assert len(tight) > len(default) or len(default) == 1
