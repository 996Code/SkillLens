"""S10 Task2：窗口级噪声过滤（v1 启发式，C3——决策落库可审计，不删 raw 数据）。

输入：process 管道 build_windows 的窗口结构
  {"anchor": {...action 事件...}, "members": [network...], 可选 "snapshots": [snapshot...]}
输出：每窗 {"window_seq": int, "kept": bool, "reason": str}（kept=True 时 reason=""）

四规则（全部可配常量）：
  ①empty_label：锚点 label strip 后为空（最廉价，先判）
  ②overlong：窗口时长（anchor ts → 最后成员 ts）> OVERLONG_FACTOR × MAX_WINDOW_MS
  ③orphan_click：无 network 成员且无快照/后续事件（纯点击无下文）
  ④read_only：有 network 成员但无写方法（POST/PUT/DELETE/PATCH）且无 state_signals

设计说明：
- classify_windows 是纯函数（不碰 DB），process.py 挂接处负责落 filtered_window；
- snapshots 归属由 process.assign_snapshots 计算，此处经 windows[i]["snapshots"]
  消费——锚点后有快照说明动作产生了可观测的 UI 后续，不是孤儿点击
  （既有 S8 快照链路 test_process_multiple_after_snapshots_takes_last 依赖此判定）。
"""
import re

from app.ingestion.signals import extract_state_signals
from app.ingestion.windows import MAX_WINDOW_MS

# 规则③超长倍数：> MAX_WINDOW_MS×2 → overlong
OVERLONG_FACTOR = 2
# 规则④写方法集合
WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}
# 规则①label 剥离：控制字符/零宽字符不算有效内容
_LABEL_STRIP = re.compile(r"[\s\x00-\x1f\x7f\u200b-\u200d\uFEFF]")


def _anchor_label(anchor: dict) -> str:
    target = (anchor.get("payload") or {}).get("target") or {}
    label = target.get("label")
    return label if isinstance(label, str) else ""


def _has_write(members: list[dict]) -> bool:
    return any(
        ((m.get("payload") or {}).get("method") or "").upper() in WRITE_METHODS
        for m in members
    )


def _has_state_signals(members: list[dict]) -> bool:
    return any(
        extract_state_signals((m.get("payload") or {}).get("resBody"))
        for m in members
    )


def classify_windows(windows: list[dict]) -> list[dict]:
    """对 build_windows 产物逐窗判定，返回过滤决策（顺序与输入一致）。"""
    out: list[dict] = []
    for i, w in enumerate(windows):
        reason = _classify_one(w)
        out.append({"window_seq": i, "kept": reason == "", "reason": reason})
    return out


def _classify_one(w: dict) -> str:
    anchor = w.get("anchor") or {}
    members: list[dict] = w.get("members") or []
    snapshots: list[dict] = w.get("snapshots") or []

    # ① 空锚点 label：无语义锚，后续规则无意义
    if not _LABEL_STRIP.sub("", _anchor_label(anchor)):
        return "empty_label"

    # ② 超长窗口：锚点到最后成员跨度异常（正常窗 build_windows 已限 MAX_WINDOW_MS，
    #    超限意味着输入结构异常/时钟跳变，双倍容错后仍超 → 过滤）
    if members:
        duration = members[-1]["ts"] - anchor["ts"]
        if duration > OVERLONG_FACTOR * MAX_WINDOW_MS:
            return "overlong"

    # ③ 孤儿点击：无 network 也无快照/后续事件——点了但什么都没发生
    if not members and not snapshots:
        return "orphan_click"

    # ④ 纯读窗口：有 network 成员但全是读方法且无状态信号（浏览、查询，非事务）；
    #    无成员仅快照的窗（S8 UI 状态证据通道）不在此列
    if members and not _has_write(members) and not _has_state_signals(members):
        return "read_only"

    return ""
