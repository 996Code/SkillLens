"""AK4 通道级熔断器（设计 §3.4）：滑窗失败率 → OPEN 快败（e2_infra，
零浏览器调用）→ HALF_OPEN 放 1 个探测 → 成功关闸。

业界依据：resilience4j/Polly 标准状态机；按通道独立实例
（extension CDP / server Playwright 各一）。
131 run/13s 风暴复盘：若有此闸，第 6 个 run 起直接快败不触浏览器。
"""
import time
from collections import deque
from enum import Enum


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """进程内滑窗熔断：window 次采样中 fail_threshold 次 fatal → OPEN
    cooldown 秒 → HALF_OPEN 放行一个探测（成功 CLOSED / 失败再 OPEN）。"""

    def __init__(self, fail_threshold: int = 5, window: int = 10,
                 cooldown_s: float = 60.0):
        self.fail_threshold = fail_threshold
        self.window = window
        self.cooldown_s = cooldown_s
        self._samples: deque[tuple[float, bool]] = deque(maxlen=window)
        self._state = BreakerState.CLOSED
        self._opened_at = 0.0
        self._half_open_probe_inflight = False

    @property
    def state(self) -> BreakerState:
        if self._state == BreakerState.OPEN and \
                time.monotonic() - self._opened_at >= self.cooldown_s:
            self._state = BreakerState.HALF_OPEN
            self._half_open_probe_inflight = False
        return self._state

    def allow(self) -> bool:
        """是否放行调用。OPEN=False（快败）；HALF_OPEN 放单探测。"""
        st = self.state
        if st == BreakerState.CLOSED:
            return True
        if st == BreakerState.OPEN:
            return False
        # HALF_OPEN：单探测（并发下第二个调用快败）
        if self._half_open_probe_inflight:
            return False
        self._half_open_probe_inflight = True
        return True

    def record(self, ok: bool) -> None:
        if ok and self.state == BreakerState.CLOSED:
            # 任一次成功即 reset（zcode 截图重试同款哲学——连败计数归零，
            # 偶发单败不算通道劣化）
            self._samples.clear()
            return
        self._samples.append((time.monotonic(), ok))
        if self.state == BreakerState.HALF_OPEN:
            self._half_open_probe_inflight = False
            if ok:
                self._state = BreakerState.CLOSED
                self._samples.clear()
            else:
                self._state = BreakerState.OPEN
                self._opened_at = time.monotonic()
            return
        if not ok:
            fails = sum(1 for _, good in self._samples if not good)
            if fails >= self.fail_threshold:
                self._state = BreakerState.OPEN
                self._opened_at = time.monotonic()


# 通道级单例（进程内）：extension=插件 CDP 通道；server=Playwright 通道
BREAKERS: dict[str, CircuitBreaker] = {
    "extension": CircuitBreaker(),
    "server": CircuitBreaker(),
}


def breaker_for(channel: str) -> CircuitBreaker:
    return BREAKERS.setdefault(channel, CircuitBreaker())
