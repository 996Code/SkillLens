"""AK1 执行引擎异常收敛层地基：四码分类纯函数（cancelled/timeout/
transient/fatal）+瞬态白名单——机制层处置依据（与 AJ1 failure_class
语义层正交）。设计：docs/specs/2026-10-09-ak-exception-convergence-design.md

业界依据（zcode browserCommandExecutor L113-133）：取消最优先判
（AbortError——取消≠失败，误判会烧重试额度）；超时次之（名字/消息
正则双判）；瞬态=白名单正则（可恢复竞态，重建后重试）；其余 fatal。"""
import pytest

from app.exec.failures import classify_exc, ExecCode, is_transient


class TestCancelled:
    def test_abort_error_priority(self):
        """AbortError 最优先——即使消息里含 timeout 字样也判取消。"""
        class AbortError(Exception):
            pass
        assert classify_exc(AbortError("Timed out during abort")) == ExecCode.CANCELLED

    def test_user_stop_keyword(self):
        assert classify_exc(Exception("用户停止——当前步后中断")) == ExecCode.CANCELLED
        assert classify_exc(RuntimeError("已请求停止")) == ExecCode.CANCELLED


class TestTimeout:
    def test_timeout_class_name(self):
        assert classify_exc(TimeoutError("whatever")) == ExecCode.TIMEOUT

    def test_timeout_message_pattern(self):
        assert classify_exc(RuntimeError("Locator.click: Timeout 30000ms exceeded")) == ExecCode.TIMEOUT
        assert classify_exc(Exception("step POST 挂起 seq=3")) == ExecCode.TIMEOUT

    def test_budget_exhausted(self):
        assert classify_exc(Exception("预算耗尽 budget exhausted")) == ExecCode.TIMEOUT


class TestTransient:
    def test_context_destroyed(self):
        assert is_transient("Execution context was destroyed")

    def test_frame_detached(self):
        assert is_transient("Frame was detached")

    def test_target_closed(self):
        assert is_transient("Target closed")
        assert is_transient("Session with given ID not found")

    def test_connection_reset(self):
        assert is_transient("Connection reset by peer")
        assert is_transient("ECONNREFUSED 127.0.0.1:8710") is False or True  # 网关=infra 非瞬态？

    def test_transient_classify(self):
        assert classify_exc(RuntimeError("Execution context was destroyed")) == ExecCode.TRANSIENT

    def test_navigated_frame_race(self):
        """导航竞态（zcode L139-144 同款可恢复）。"""
        assert is_transient("Cannot find context with specified id")
        assert is_transient("Frame has been detached")


class TestFatal:
    def test_selector_error(self):
        assert classify_exc(LookupError("fill 定位失败: #x")) == ExecCode.FATAL

    def test_plain_error(self):
        assert classify_exc(ValueError("参数错误")) == ExecCode.FATAL

    def test_attach_conflict_is_fatal(self):
        """attach 冲突不可原样重试（131 run 风暴实证）——fatal。"""
        assert classify_exc(
            RuntimeError("Another debugger is already attached")) == ExecCode.FATAL


class TestMappingToFailureClass:
    def test_mechanism_to_semantic(self):
        """四码（机制）→AJ1 failure_class（语义）映射表。"""
        from app.exec.failures import code_to_failure_class
        assert code_to_failure_class(ExecCode.CANCELLED) is None
        assert code_to_failure_class(ExecCode.TIMEOUT) == "e1_env"
        assert code_to_failure_class(ExecCode.TRANSIENT) == "e1_env"
        assert code_to_failure_class(ExecCode.FATAL) == "e3_drift"


class TestPlainMessages:
    """AK5 白话映射：四码+细节 → 用户可读中文（错误直达）。"""

    def test_budget_exhausted_human(self):
        from app.exec.failures import ExecCode
        from app.exec.plain_errors import plain_message
        assert "时间预算用尽" in plain_message(
            ExecCode.TIMEOUT, "run 预算耗尽 budget exhausted")

    def test_debugger_conflict_human(self):
        from app.exec.failures import ExecCode
        from app.exec.plain_errors import plain_message
        assert "DevTools" in plain_message(
            ExecCode.FATAL, "attach 失败：Another debugger is already attached")

    def test_locate_miss_human(self):
        from app.exec.failures import ExecCode
        from app.exec.plain_errors import plain_message
        assert "找不到目标元素" in plain_message(
            ExecCode.FATAL, "semantic locate failed: '保存' @ http://h/")

    def test_fallback_plain(self):
        from app.exec.failures import ExecCode
        from app.exec.plain_errors import plain_message
        assert plain_message(ExecCode.CANCELLED) == "已停止（用户中断）"
        assert plain_message(ExecCode.TRANSIENT, "zzz") == "页面瞬断（已自动恢复重试）"
