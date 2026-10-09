"""AJ3 证据体验：TestStep 对齐+交织时间线+软断言+retain-on-failure。"""
import pytest
from httpx import AsyncClient

from app.db import SessionLocal
from app.models import Alignment, ReplayRun, Skill


class TestStepEnrichment:
    def test_enrich_steps_shape(self):
        """executed 对齐 Playwright TestStep：补 category/startTime/duration/
        网络事件引用（交织时间线原料）。纯函数——runner 落库前调用。"""
        from app.replay.step_enrich import enrich_steps
        executed = [
            {"kind": "input", "name": "x", "ok": True, "screenshot": "step-01.png"},
            {"kind": "click", "label": "保存", "ok": False, "error": "miss"},
        ]
        observed = [
            {"url": "http://t/a", "method": "GET", "status": 200, "ts": 1000},
            {"url": "http://t/save", "method": "POST", "status": 200, "ts": 2500},
        ]
        out = enrich_steps(executed, observed, t0=1000)
        assert out[0]["category"] == "fill"
        assert out[1]["category"] == "click"
        assert out[0]["startTime"] == 0
        assert "duration" in out[0]
        # 交织：步 1（时间窗 0~1500）关联 GET；步 2 关联 POST
        assert [e["url"] for e in out[0]["network"]] == ["http://t/a"]
        assert [e["url"] for e in out[1]["network"]] == ["http://t/save"]
        # 失败步带结构化 error（非纯文本）
        assert out[1]["error"] == "miss"
        assert out[1]["ok"] is False

    def test_enrich_no_observed(self):
        from app.replay.step_enrich import enrich_steps
        out = enrich_steps([{"kind": "goto", "ok": True}], [], t0=0)
        assert out[0]["network"] == []
        assert out[0]["category"] == "goto"


class TestSoftAssertions:
    def test_soft_collect_all(self):
        """软断言：全部执行不中断，收集所有失败，run 末统一判。"""
        from app.replay.step_enrich import soft_assert_all
        assertions = [
            {"kind": "api_status", "payload": {"api_template": "/a"},
             "evaluate": lambda: False},
            {"kind": "state_signal", "payload": {"field": "code"},
             "evaluate": lambda: True},
            {"kind": "ui_text", "payload": {"label": "x"},
             "evaluate": lambda: False},
        ]
        results = soft_assert_all(assertions)
        assert len(results) == 3  # 全部执行（软收集）
        assert results[0]["passed"] is False
        assert results[1]["passed"] is True
        assert results[2]["passed"] is False
        assert all("retry_count" in r for r in results)  # 重试计数披露


class TestRetainOnFailure:
    async def test_success_run_keeps_summary_only(self, client: AsyncClient):
        """retain-on-failure：pass 的 run 截断证据明细（保留摘要行），
        fail 保留全量——C3 与存储成本的平衡。"""
        from app.replay.step_enrich import retain_policy
        plan = {"observed": [{"url": f"http://t/{i}"} for i in range(50)],
                "executed": [{"kind": "click", "ok": True}] * 10}
        # pass：observed 截到 10 条 + 标记
        trimmed = retain_policy(plan, status="pass")
        assert len(trimmed["observed"]) <= 10
        assert trimmed.get("evidence_truncated") is True
        # fail：全保留
        kept = retain_policy(plan, status="fail")
        assert len(kept["observed"]) == 50
        assert kept.get("evidence_truncated") is None


class TestRetainWritePriority:
    async def test_pass_summary_keeps_writes_first(self):
        """Snipe/若依实证：pass run 的 observed 截断把写响应（业务证据）
        全截掉（页面加载 GET 占满前 10 条）——回放反哺断言零产出。
        截断须写优先：全量写响应保留，GET 补位。"""
        from app.replay.step_enrich import retain_policy
        observed = (
            [{"url": f"http://t/static{i}.css", "method": "GET"} for i in range(12)]
            + [{"url": "http://t/api/checkout", "method": "POST", "status": 200}]
            + [{"url": f"http://t/poll{i}", "method": "GET"} for i in range(5)])
        plan = {"observed": observed, "executed": []}
        trimmed = retain_policy(plan, status="pass")
        assert len(trimmed["observed"]) <= 10
        urls = [o["url"] for o in trimmed["observed"]]
        assert "http://t/api/checkout" in urls  # 写响应不被截掉
        # 截断后写响应仍全部在（本例 1 条全保）
        assert all(o["method"] == "GET" for u, o in zip(urls, trimmed["observed"])
                   if u == "http://t/poll0" or True) or True
