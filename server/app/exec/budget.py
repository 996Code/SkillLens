"""AK3 server 侧预算传递（与 extension/src/shared/budget.ts 同语义）。

run 总预算 → 每步 = 剩余/剩余步数（下限 5s）；剩余制天然封顶。
用于 server replay 的 attempt 级硬封顶（asyncio.wait_for 包裹）。
"""
import asyncio
import time


class Budget:
    def __init__(self, total_ms: int):
        self.deadline = time.monotonic() + total_ms / 1000

    def left_ms(self) -> int:
        return max(0, int((self.deadline - time.monotonic()) * 1000))

    def exhausted(self) -> bool:
        return time.monotonic() >= self.deadline

    def timeout_error(self, what: str) -> TimeoutError:
        return TimeoutError(f"{what} 预算耗尽 budget exhausted")


def step_budget(run: Budget, remaining_steps: int, step_floor_ms: int = 5000) -> Budget:
    n = max(1, remaining_steps)
    ms = max(run.left_ms() // n, min(step_floor_ms, run.left_ms()))
    b = Budget(ms)
    b.deadline = min(b.deadline, run.deadline)
    return b


async def with_budget(coro, b: Budget, what: str):
    """预算内执行协程；耗尽抛 TimeoutError（预算耗尽语义——四码分类锚点）。"""
    left = b.left_ms()
    if left <= 0:
        raise b.timeout_error(what)
    try:
        return await asyncio.wait_for(coro, timeout=left / 1000)
    except asyncio.TimeoutError as e:
        raise b.timeout_error(what) from e
