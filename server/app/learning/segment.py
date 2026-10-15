"""AP2 task segmentation + noise gates (pure deterministic rules).

设计（docs/specs/2026-10-14-ap-zero-ritual-recording-design.md §4）：
- 切分信号：短空闲（idle_s 无交互）/ 导航闭环（列表→详情→回列表）/
  写边界（写请求 + write_quiet_s 无新交互——神策边界事件模式）
- 闸门（discard 不进学习，C3 留痕 reason）：
  ① 无写且无导航闭环 → 纯浏览
  ② 事件数 < min_events → 误触
  ③ 全输入无提交 → 半途而废
判定全确定性（宪法 C1）；参数可配（GateConfig）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


@dataclass
class GateConfig:
    idle_s: int = 90            # 短空闲边界（会话级 30min 的任务级缩小版）
    write_quiet_s: int = 30     # 写后静默窗口（写边界信号）
    min_events: int = 5         # 闸门②：误触下限
    loop_path_depth: int = 2    # 导航闭环：详情页路径深度（/items/42 → 2 段）


@dataclass
class Segment:
    events: list[dict]
    has_write: bool = False
    has_nav_loop: bool = False
    discarded: bool = False
    discard_reason: str = ""
    start_ts: int = 0
    end_ts: int = 0
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "events": self.events, "has_write": self.has_write,
            "has_nav_loop": self.has_nav_loop, "discarded": self.discarded,
            "discard_reason": self.discard_reason,
            "start_ts": self.start_ts, "end_ts": self.end_ts,
            **self.meta,
        }


def _is_write(e: dict) -> bool:
    p = e.get("payload") or {}
    return e.get("kind") == "network" and p.get("method") in WRITE_METHODS


def _is_interaction(e: dict) -> bool:
    return e.get("kind") == "action"


def _nav_path_segments(url: str) -> list[str]:
    from urllib.parse import urlparse
    path = urlparse(url or "").path.strip("/")
    return [s for s in path.split("/") if s] if path else []


def _detect_nav_loop(events: list[dict], cfg: GateConfig) -> bool:
    """导航闭环：列表→详情→回列表（同前缀路径，详情更深，再回浅层）。"""
    navs = [e for e in events if e.get("kind") == "navigation"]
    paths = [_nav_path_segments((e.get("payload") or {}).get("url", ""))
             for e in navs]
    paths = [p for p in paths if p]
    for i in range(len(paths) - 2):
        a, b, c = paths[i], paths[i + 1], paths[i + 2]
        # 列表 a（浅）→ 详情 b（a 前缀+更深）→ 回列表 c（≈a 浅层）
        if (a == c or c[:len(a)] == a) and b[:len(a)] == a and len(b) > len(a) \
                and len(b) - len(a) <= cfg.loop_path_depth:
            return True
    return False


def _split_indices(events: list[dict], cfg: GateConfig) -> list[int]:
    """返回切分点（事件索引）：该事件开启新任务段。"""
    cuts: list[int] = [0]
    last_interaction_ts = None
    last_write_ts = None
    for i, e in enumerate(events):
        ts = e.get("ts", 0)
        if _is_interaction(e):
            cut_here = False
            if last_interaction_ts is not None:
                gap = (ts - last_interaction_ts) / 1000
                if gap >= cfg.idle_s and i > cuts[-1]:
                    cuts.append(i)  # 信号①：短空闲
                    cut_here = True
            # 信号③（写边界）：写后 write_quiet_s 无新交互——新交互
            # 属于下一任务（神策边界事件模式：写+静默=任务完成）
            if last_write_ts is not None:
                quiet = (ts - last_write_ts) / 1000
                if quiet >= cfg.write_quiet_s and i > cuts[-1]:
                    cuts.append(i)
                    cut_here = True
            if cut_here:
                last_write_ts = None  # 边界已消费——同事件/后续不重复触发
            last_interaction_ts = ts
        if _is_write(e):
            last_write_ts = ts
    return cuts


def _apply_gate(seg_events: list[dict], has_write: bool,
                has_nav_loop: bool, cfg: GateConfig) -> Segment:
    seg = Segment(events=seg_events, has_write=has_write,
                  has_nav_loop=has_nav_loop,
                  start_ts=seg_events[0].get("ts", 0) if seg_events else 0,
                  end_ts=seg_events[-1].get("ts", 0) if seg_events else 0)
    if not has_write and not has_nav_loop:
        seg.discarded = True
        seg.discard_reason = "pure_browsing"  # 闸门①
        return seg
    if len(seg_events) < cfg.min_events:
        seg.discarded = True
        seg.discard_reason = "too_few_events"  # 闸门②
        return seg
    has_submit = has_write or any(
        (e.get("payload") or {}).get("type") == "click"
        for e in seg_events if e.get("kind") == "action")
    has_input = any((e.get("payload") or {}).get("type") == "input"
                    for e in seg_events if e.get("kind") == "action")
    if has_input and not has_submit and not has_nav_loop:
        seg.discarded = True
        seg.discard_reason = "no_submit"  # 闸门③
    return seg


def segment_session(events: list[dict],
                    cfg: GateConfig | None = None) -> list[dict]:
    """会话事件流 → 任务段列表（dict 形态；discard 段保留留痕）。

    导航闭环信号在段级生效：若空闲/写边界切出的段内含闭环，不再细分
    （闭环是任务完成的佐证，不是切分点本身——回列表即下任务开始）。
    """
    cfg = cfg or GateConfig()
    if not events:
        return []
    cuts = _split_indices(events, cfg)
    out: list[dict] = []
    for si, start in enumerate(cuts):
        end = cuts[si + 1] if si + 1 < len(cuts) else len(events)
        seg_events = events[start:end]
        if not seg_events:
            continue
        # 段内导航闭环 → 该段在回列表处结束（闭环点即边界）
        has_loop = _detect_nav_loop(seg_events, cfg)
        if has_loop:
            # 找回列表的 navigation 索引，段在其后切开
            navs = [(j, e) for j, e in enumerate(seg_events)
                    if e.get("kind") == "navigation"]
            for j in range(len(navs) - 2):
                a, b, c = (navs[j][1], navs[j + 1][1], navs[j + 2][1])
                pa = _nav_path_segments((a.get("payload") or {}).get("url", ""))
                pb = _nav_path_segments((b.get("payload") or {}).get("url", ""))
                pc = _nav_path_segments((c.get("payload") or {}).get("url", ""))
                if pa and (pa == pc or pc[:len(pa)] == pa) \
                        and pb[:len(pa)] == pa and len(pb) > len(pa) \
                        and len(pb) - len(pa) <= cfg.loop_path_depth:
                    cut_at = navs[j + 2][0]
                    if 0 < cut_at < len(seg_events):
                        first = _apply_gate(seg_events[:cut_at], True, True, cfg)
                        out.append(first.as_dict())
                        seg_events = seg_events[cut_at:]
                    break
        seg = _apply_gate(seg_events, any(_is_write(e) for e in seg_events),
                          _detect_nav_loop(seg_events, cfg), cfg)
        out.append(seg.as_dict())
    return out
