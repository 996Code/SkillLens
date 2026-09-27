"""S23 块 V：性能基线与漂移判定（TDD 先红）——确定性，无 LLM。

覆盖：滚动基线中位数、漂移阈值边界、历史不足不判定、API 延迟逐模板判定。
"""
from app.change.perf import perf_drift, rolling_baseline


def test_rolling_baseline_median_odd():
    r = rolling_baseline([100, 200, 300])
    assert r == {"median": 200, "n": 3}


def test_rolling_baseline_median_even():
    # 偶数个取中间两数均值
    r = rolling_baseline([100, 200, 300, 400])
    assert r["median"] == 250
    assert r["n"] == 4


def test_rolling_baseline_empty():
    assert rolling_baseline([]) == {"median": None, "n": 0}


def test_perf_drift_over_threshold():
    # 中位 200，当前 400 = 2.0x > 1.5x → drift
    d = perf_drift([100, 200, 300], 400)
    assert d is not None
    assert d["type"] == "perf"
    assert "200ms" in d["value"] and "400ms" in d["value"]
    assert "+100%" in d["value"]


def test_perf_drift_within_threshold():
    # 中位 200，当前 250 = 1.25x < 1.5x → 无 drift
    assert perf_drift([100, 200, 300], 250) is None


def test_perf_drift_boundary_exactly_ratio():
    # 恰好 1.5x → 不判 drift（严格大于才漂移）
    assert perf_drift([100, 200, 300], 300) is None


def test_perf_drift_insufficient_history():
    # 历史不足 3 次 → 不判定（防 N=1 噪声）
    assert perf_drift([], 9999) is None
    assert perf_drift([100], 9999) is None
    assert perf_drift([100, 100], 9999) is None


def test_perf_drift_ratio_configurable():
    assert perf_drift([100, 200, 300], 250, ratio=1.2) is not None


def test_api_latency_drift_per_template():
    from app.change.perf import api_latency_drift
    history = [  # 每次回放一档 api_latencies
        {"/a/save": 100, "/b/list": 200},
        {"/a/save": 120, "/b/list": 220},
        {"/a/save": 110, "/b/list": 210},
    ]
    current = {"/a/save": 300, "/b/list": 215}
    drifts = api_latency_drift(history, current)
    # /a/save 中位 110 → 300 = 2.7x 漂移；/b/list 中位 210 → 215 正常
    assert len(drifts) == 1
    assert "/a/save" in drifts[0]["value"]
    assert drifts[0]["type"] == "perf"
