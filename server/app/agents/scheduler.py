"""S13 F1：夜间调度（v1 简化 asyncio 循环，不引 APScheduler）。

NIGHTLY_CRON：off（默认，不启动）| nightly（每天 02:00 跑一次夜间图）。
v1 简化：启动后延迟到下一个 02:00，之后每 24h（本地时区，无 DST 处理）。
"""
_scheduler_task = None

import asyncio
import logging
import os
from contextlib import suppress
from datetime import datetime, timedelta

from app.db import SessionLocal

RUN_AT_HOUR = 2


def _next_run_at(now: datetime) -> datetime:
    """纯函数：now 之后（含）最近的下一个 02:00。已过今天 02:00 → 次日。"""
    nxt = now.replace(hour=RUN_AT_HOUR, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return nxt


async def _nightly_once() -> None:
    from app.agents.runtime import run_graph  # 延迟导入避免环
    db = SessionLocal()
    try:
        await run_graph(db, "nightly", {"change_set": {}})
    finally:
        db.close()


async def _loop() -> None:
    while True:
        now = datetime.now()
        await asyncio.sleep((_next_run_at(now) - now).total_seconds())
        # run_graph 内部收敛业务异常（status=error 落库），但进它之前的
        # 建连/import 失败同样会打死 task——夜间图静默停摆且只在 GC 时打印。
        # 循环体自兜：单次失败留痕后继续等下一个 02:00。
        try:
            await _nightly_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("夜间图执行失败，调度循环继续")


async def start_nightly_scheduler() -> None:
    """按 NIGHTLY_CRON 拉起后台循环；off/未知值一律不启动。返回 None 便于测试断言。"""
    if os.environ.get("NIGHTLY_CRON", "off") != "nightly":
        return None

    # 持有 task 引用防 GC（asyncio 官方警告）；模块级，进程生命周期存活
    global _scheduler_task
    _scheduler_task = asyncio.create_task(_loop())
    return _scheduler_task


async def stop_nightly_scheduler() -> None:
    """关停清理：lifespan 退出时取消循环，否则留 pending task
    （uvicorn --reload / 测试进程退出时 "Task was destroyed but it is pending"）。"""
    global _scheduler_task
    task, _scheduler_task = _scheduler_task, None
    if task is not None and not task.done():
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
