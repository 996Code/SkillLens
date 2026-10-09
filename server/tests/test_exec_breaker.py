"""AK4 熔断器单测：滑窗→OPEN 快败→冷却→HALF_OPEN 探测→恢复/再开。"""
from app.exec.breaker import BreakerState, CircuitBreaker, breaker_for


def test_opens_after_threshold():
    b = CircuitBreaker(fail_threshold=5, window=10, cooldown_s=60)
    for _ in range(4):
        b.record(False)
    assert b.state == BreakerState.CLOSED
    b.record(False)  # 第 5 次 fatal
    assert b.state == BreakerState.OPEN
    assert b.allow() is False  # 快败：零调用


def test_success_resets_window():
    b = CircuitBreaker(fail_threshold=5, window=10, cooldown_s=60)
    for _ in range(4):
        b.record(False)
    b.record(True)  # 成功重置（Playwright flaky 哲学：单败不算）
    b.record(False)
    assert b.state == BreakerState.CLOSED  # 窗口内 fail 数仍 <5


def test_half_open_probe_then_recover():
    b = CircuitBreaker(fail_threshold=2, window=10, cooldown_s=0.05)
    b.record(False); b.record(False)
    assert b.state == BreakerState.OPEN
    import time
    time.sleep(0.06)
    assert b.state == BreakerState.HALF_OPEN
    assert b.allow() is True       # 放探测
    assert b.allow() is False      # 并发第二个快败
    b.record(True)                 # 探测成功
    assert b.state == BreakerState.CLOSED
    assert b.allow() is True


def test_half_open_probe_fail_reopens():
    b = CircuitBreaker(fail_threshold=2, window=10, cooldown_s=0.05)
    b.record(False); b.record(False)
    import time
    time.sleep(0.06)
    assert b.allow() is True
    b.record(False)                # 探测失败 → 再开闸（冷却重计）
    assert b.state == BreakerState.OPEN
    assert b.allow() is False


def test_channel_instances_independent():
    ext = breaker_for("extension")
    srv = breaker_for("server")
    assert ext is not srv
    for _ in range(5):
        ext.record(False)
    assert ext.state == BreakerState.OPEN
    assert srv.state == BreakerState.CLOSED
