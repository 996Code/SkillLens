"""三轮评审：夜间调度循环的两处韧性缺口（S13 F1）。

① 循环体裸奔：原注释断言「run_graph 内部已收敛异常」，但 _nightly_once 在进
   run_graph 之前就可能抛（SessionLocal 建连失败/库锁/迁移未跑导致的 import 期
   错误）——task 被打死后夜间图静默停摆，异常只在 GC 时打印一行，无人察觉。
② 关停不取消：lifespan yield 之后没有清理，uvicorn --reload 与测试进程退出时
   留 pending task（"Task was destroyed but it is pending!"）。
"""
import asyncio

import pytest

from app.agents import scheduler


async def test_loop_survives_nightly_failure(monkeypatch):
    calls: list[int] = []

    async def boom():
        calls.append(1)
        raise RuntimeError("database is locked")

    async def fake_sleep(_sec):
        if len(calls) >= 2:
            raise asyncio.CancelledError      # 测试收尾：让循环退出
        return None

    monkeypatch.setattr(scheduler, "_nightly_once", boom)
    monkeypatch.setattr(scheduler.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await scheduler._loop()
    assert len(calls) == 2, "单次失败即退出循环——夜间图静默停摆"


async def test_stop_cancels_running_task(monkeypatch):
    monkeypatch.setenv("NIGHTLY_CRON", "nightly")
    started = asyncio.Event()

    async def hang(_sec):
        started.set()
        await asyncio.get_running_loop().create_future()   # 永不完成，可取消

    monkeypatch.setattr(scheduler.asyncio, "sleep", hang)
    task = await scheduler.start_nightly_scheduler()
    assert task is not None
    await asyncio.wait_for(started.wait(), timeout=2)

    await scheduler.stop_nightly_scheduler()
    assert task.cancelled()
    assert scheduler._scheduler_task is None


async def test_stop_without_start_is_noop():
    scheduler._scheduler_task = None
    await scheduler.stop_nightly_scheduler()      # 不抛


async def test_off_by_default(monkeypatch):
    monkeypatch.delenv("NIGHTLY_CRON", raising=False)
    assert await scheduler.start_nightly_scheduler() is None


def test_next_run_at_wraps_to_tomorrow():
    from datetime import datetime
    assert scheduler._next_run_at(datetime(2026, 10, 7, 1, 0)) == datetime(2026, 10, 7, 2, 0)
    assert scheduler._next_run_at(datetime(2026, 10, 7, 2, 0)) == datetime(2026, 10, 8, 2, 0)
    assert scheduler._next_run_at(datetime(2026, 10, 7, 23, 30)) == datetime(2026, 10, 8, 2, 0)
