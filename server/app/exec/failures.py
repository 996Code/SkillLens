"""AK 执行引擎异常收敛层：四码分类纯函数（机制层）。

设计：docs/specs/2026-10-09-ak-exception-convergence-design.md
业界依据：zcode browserCommandExecutor L113-133（取消最优先/结构化
返回永不 throw）+ 瞬态白名单（L139-144 可恢复竞态正则）。

与 AJ1 failure_class（语义层：e1_env/e2_infra/e3_drift）正交：
四码决定"怎么处置"（重试/熔断/直达用户），failure_class 决定
"怎么归因"（是否进通过率分母）。
"""
import logging
import re
from enum import Enum

from app.sanitize import sanitize_error

_logger = logging.getLogger("skilllens")


class ExecCode(str, Enum):
    CANCELLED = "cancelled"   # 用户停止/中止——不算失败，不烧额度
    TIMEOUT = "timeout"       # 预算耗尽——换通道重试或快败
    TRANSIENT = "transient"   # 瞬态白名单——重建上下文后有界重试
    FATAL = "fatal"           # 业务/选择器/参数错——不重试直达用户


_CANCEL_PAT = re.compile(
    r"AbortError|aborted|用户停止|已请求停止|shouldStop|中断", re.IGNORECASE)
_TIMEOUT_PAT = re.compile(
    r"Timeout|TimeoutError|超时|挂起 seq=|预算耗尽|budget exhausted", re.IGNORECASE)
# 瞬态白名单（zcode L139-144 同族：页面竞态/通道抖动，重建可恢复）
_TRANSIENT_PAT = re.compile(
    r"Execution context was destroyed|Frame (has been |was )?detached"
    r"|Cannot find context with specified id|Target closed"
    r"|Session with given ID not found|Connection reset by peer"
    r"|WebSocket is already closed|net::ERR_CONNECTION_RESET", re.IGNORECASE)


def is_transient(message: str) -> bool:
    """错误消息是否瞬态白名单（可恢复竞态——重建后重试有效）。"""
    return bool(_TRANSIENT_PAT.search(message or ""))


def classify_exc(exc: BaseException | str) -> ExecCode:
    """异常 → 四码。判定顺序（zcode 共识）：取消 > 超时 > 瞬态 > fatal。

    取消最优先：AbortError 消息可能含 timeout 字样，先判取消防误烧
    重试额度；attach 冲突/选择器错等不在白名单= fatal（原样重试无意义）。
    """
    name = exc.__class__.__name__ if isinstance(exc, BaseException) else ""
    msg = str(exc)
    if name == "AbortError" or _CANCEL_PAT.search(msg):
        return ExecCode.CANCELLED
    if name == "TimeoutError" or _TIMEOUT_PAT.search(msg):
        # 超时内含瞬态形态（如 context destroyed 在等待中出现）优先瞬态
        if is_transient(msg):
            return ExecCode.TRANSIENT
        return ExecCode.TIMEOUT
    if is_transient(msg):
        return ExecCode.TRANSIENT
    return ExecCode.FATAL


# 四码（机制）→ AJ1 failure_class（语义）映射：同一次失败两层各取所需
def code_to_failure_class(code: ExecCode) -> str | None:
    return {
        ExecCode.CANCELLED: None,
        ExecCode.TIMEOUT: "e1_env",
        ExecCode.TRANSIENT: "e1_env",
        ExecCode.FATAL: "e3_drift",
    }.get(code)


def swallow(where: str, exc: BaseException, *, warning: bool = False) -> ExecCode:
    """AK6 fail-open 站点收敛：分类+留痕（C3 可观测），行为不变。

    散落 `except Exception: pass` 的统一替代——吞错仍吞（fail-open 语义
    不变），但错误经四码分类+脱敏后进日志：debug 级（探测类，默认不可见
    不噪声）/ warning 级（决策相关——恢复失败、基线缺失等静默降级）。
    返回四码供调用方按需分支。"""
    code = classify_exc(exc)
    _logger.log(logging.WARNING if warning else logging.DEBUG,
                "swallow[%s] %s: %s", code.value, where, sanitize_error(exc))
    return code
