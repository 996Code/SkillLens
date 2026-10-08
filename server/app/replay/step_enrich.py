"""AJ3 证据体验（Playwright/Cypress 调研落地）：

- enrich_steps：executed 对齐 TestStep（category/startTime/duration/
  步内网络事件引用——Command Log 交织时间线的原料）
- soft_assert_all：软断言收集（全量执行不中断+有界重试+计数披露）
- retain_policy：retain-on-failure（pass 截证据保摘要，fail 全保留）
"""
import time

_KIND_CATEGORY = {
    "input": "fill", "click": "click", "goto": "goto",
    "submit": "submit", "snapshot": "snapshot",
}


def enrich_steps(executed: list, observed: list, t0: int = 0) -> list:
    """步骤富化（纯函数，runner 落库前调）。

    时间窗交织：步骤按执行序均分观察窗（无真实步级时间戳时的近似——
    有 startTime 的步骤用真实值），窗内 observed 事件引用挂步骤。
    """
    out = []
    n = len(executed) or 1
    window = 1500  # ms/步 近似窗（与 toast 轮询节奏同量级）
    for i, st in enumerate(executed):
        s = dict(st)
        s["category"] = _KIND_CATEGORY.get(str(st.get("kind")), str(st.get("kind")))
        start = st.get("startTime")
        if start is None:
            start = i * window
            s["startTime"] = start
        s["duration"] = st.get("duration") or window
        lo, hi = start, start + (s["duration"] or window)
        evts = []
        for o in observed or []:
            ts = o.get("ts")
            if ts is None:
                continue
            # observed ts 是绝对时间——相对化到 t0 后按窗归属
            rel = ts - t0 if t0 and ts >= t0 else ts
            if lo <= rel < hi:
                evts.append({k: o.get(k) for k in ("url", "method", "status")})
        s["network"] = evts
        out.append(s)
    return out


def soft_assert_all(assertions: list, retry_window_ms: int = 2000,
                    retry_interval_ms: int = 500) -> list:
    """软断言（Cypress/Playwright expect.soft 语义）：全部执行不中断，
    每条失败后有界重试（瞬态内容窗口），重试计数披露（flaky 预警信号）。

    assertions 元素带 evaluate() -> bool（同步判定）。
    """
    results = []
    for a in assertions:
        retry_count = 0
        passed = False
        deadline = time.monotonic() + retry_window_ms / 1000
        while True:
            try:
                passed = bool(a["evaluate"]())
            except Exception:
                passed = False
            if passed or time.monotonic() >= deadline:
                break
            retry_count += 1
            time.sleep(retry_interval_ms / 1000)
        results.append({
            "kind": a.get("kind"),
            "payload": a.get("payload"),
            "passed": passed,
            "retry_count": retry_count,  # >0 即瞬态嫌疑（flaky 预警）
        })
    return results


_SUMMARY_KEEP = 10  # pass run 保留的 observed 条数上限


def retain_policy(plan: dict, status: str) -> dict:
    """retain-on-failure（Playwright Trace 采集策略）：

    pass：observed 截到摘要上限+evidence_truncated 标记（C3 摘要仍可查）；
    fail/error：全保留（归因原料完整）。
    """
    if status not in ("pass",):
        return plan
    observed = plan.get("observed") or []
    if len(observed) <= _SUMMARY_KEEP:
        return plan
    out = dict(plan)
    out["observed"] = observed[:_SUMMARY_KEEP]
    out["evidence_truncated"] = True
    out["evidence_total"] = len(observed)
    return out
