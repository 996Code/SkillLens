"""AK3 server 预算传递单测（与 extension budget.test.ts 同语义对齐）。"""
import asyncio
import time

import pytest

from app.exec.budget import Budget, step_budget, with_budget


def test_left_never_negative():
    b = Budget(30)
    time.sleep(0.04)
    assert b.left_ms() == 0
    assert b.exhausted()


def test_step_budget_floor_and_cap():
    run = Budget(120_000)
    s = step_budget(run, 10)
    assert s.left_ms() >= 11_000
    late = Budget(6_000)
    s2 = step_budget(late, 3)
    assert s2.left_ms() <= 6_000
    assert s2.deadline <= late.deadline


@pytest.mark.asyncio
async def test_with_budget_hangs_raise():
    async def hang():
        await asyncio.sleep(60)

    b = Budget(80)
    with pytest.raises(TimeoutError, match="预算耗尽"):
        await with_budget(hang(), b, "probe")


@pytest.mark.asyncio
async def test_with_budget_fast_path():
    async def ok():
        return "done"

    b = Budget(2_000)
    assert await with_budget(ok(), b, "fast") == "done"
