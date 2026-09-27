"""S23 块 V：性能基线与漂移判定——确定性纯函数（无 LLM，无新表）。

基线=滚动中位数（历史从 replay_run 重算，避免基线表状态同步问题）；
判定=current > median × ratio（严格大于），历史 <3 次不判定（防 N=1 噪声）。
阈值 PERF_DRIFT_RATIO 经 config env 配置（默认 1.5）。
"""
from typing import Sequence

from sqlalchemy.orm import Session

from app import config
from app.models import ReplayRun

MIN_HISTORY = 3
DEFAULT_RATIO = float(getattr(config, "PERF_DRIFT_RATIO", 1.5))
BASELINE_WINDOW = 10


def _median(values: Sequence[int]) -> int | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) // 2


def rolling_baseline(values: Sequence[int]) -> dict:
    """滚动基线：中位数 + 样本数。空历史 median=None。"""
    return {"median": _median(values), "n": len(values)}


def perf_drift(history: Sequence[int], current: int,
               ratio: float = DEFAULT_RATIO) -> dict | None:
    """回放耗时漂移判定：current > median×ratio → drift 项；历史不足 3 次不判定。"""
    if len(history) < MIN_HISTORY:
        return None
    median = _median(history)
    if median is None or median <= 0 or current <= median * ratio:
        return None
    pct = round((current - median) / median * 100)
    return {"type": "perf",
            "value": f"回放耗时 中位数 {median}ms -> {current}ms (+{pct}%)"}


def api_latency_drift(history: Sequence[dict], current: dict,
                      ratio: float = DEFAULT_RATIO) -> list[dict]:
    """API 延迟逐模板漂移：history 每项形如 {template: latency_ms}。

    模板历史 <3 次跳过；current > median×ratio → drift 项。
    """
    out: list[dict] = []
    for tpl, cur in sorted(current.items()):
        values = [h[tpl] for h in history if tpl in h]
        if len(values) < MIN_HISTORY:
            continue
        median = _median(values)
        if median is None or median <= 0 or cur <= median * ratio:
            continue
        pct = round((cur - median) / median * 100)
        out.append({"type": "perf",
                    "value": f"API 延迟 {tpl} 中位数 {median}ms -> {cur}ms (+{pct}%)"})
    return out


def perf_context(db: Session, skill_id: int, replay_run_id: int) -> tuple[dict, list[dict]]:
    """性能上下文 + 漂移项（report 生成与 /reports/{id}/perf 共用，确定性）。

    返回 (perf_ctx, drift_items)：
    - perf_ctx = {baseline: {median,n}, current_ms, history_ms}（history 时间正序）；
    - drift_items = 耗时漂移（0/1 条）+ API 延迟漂移（逐模板 0..N 条）。
    """
    hist = db.query(ReplayRun).filter(
        ReplayRun.skill_id == skill_id, ReplayRun.mode == "execute",
        ReplayRun.id != replay_run_id,
        ReplayRun.duration_ms.isnot(None)
    ).order_by(ReplayRun.id.desc()).limit(BASELINE_WINDOW).all()
    durations = [r.duration_ms for r in reversed(hist)]
    current_run = db.get(ReplayRun, replay_run_id)
    current_ms = current_run.duration_ms if current_run else None
    drift_items: list[dict] = []
    if current_ms:
        d = perf_drift(durations, current_ms)
        if d:
            drift_items.append(d)
    hist_lat = [(r.plan or {}).get("api_latencies") or {} for r in reversed(hist)]
    cur_lat = ((current_run.plan or {}).get("api_latencies") or {}
               if current_run else {})
    drift_items.extend(api_latency_drift(hist_lat, cur_lat))
    perf_ctx = {"baseline": rolling_baseline(durations),
                "current_ms": current_ms, "history_ms": durations}
    return perf_ctx, drift_items
