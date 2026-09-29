IDLE_MS = 2000
MAX_WINDOW_MS = 8000
ANCHOR_TYPES = {"click", "submit"}


def build_windows(events: list[dict]) -> list[dict]:
    windows: list[dict] = []
    current: dict | None = None
    last_net_ts: int | None = None
    for e in events:
        payload = e.get("payload") or {}
        is_anchor = e["kind"] == "action" and payload.get("type") in ANCHOR_TYPES
        is_network = e["kind"] == "network"
        if is_anchor:
            # S35：表单提交双计治理——同一按钮先 click 后 submit（同 label）
            # 是同一用户动作，submit 不另开窗（否则骨架重复步、回放二次点击
            # 时页面已离开必失败）；label 不同（如键盘回车直提表单）仍开新窗
            if (payload.get("type") == "submit" and current is not None
                    and (current["anchor"].get("payload") or {}).get("type") == "click"):
                cur_label = (((current["anchor"].get("payload") or {})
                              .get("target") or {}).get("label") or "")
                new_label = (payload.get("target") or {}).get("label") or ""
                if cur_label and new_label and cur_label == new_label:
                    continue
            current = {"anchor": e, "members": [], "end_ts": e["ts"]}
            windows.append(current)
            last_net_ts = None
            continue
        if is_network and current is not None:
            reference = last_net_ts if last_net_ts is not None else current["anchor"]["ts"]
            within_idle = e["ts"] - reference <= IDLE_MS
            within_max = e["ts"] - current["anchor"]["ts"] <= MAX_WINDOW_MS
            if within_idle and within_max:
                current["members"].append(e)
                current["end_ts"] = e["ts"]
                last_net_ts = e["ts"]
            else:
                current = None  # 窗口关闭，其后请求视为背景流量
    return windows
