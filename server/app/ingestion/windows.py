IDLE_MS = 2000
MAX_WINDOW_MS = 8000
ANCHOR_TYPES = {"click", "submit"}


def _origin(url: str | None) -> str | None:
    if not url:
        return None
    try:
        from urllib.parse import urlsplit
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}" if parts.netloc else None
    except Exception:
        return None


def build_windows(events: list[dict]) -> list[dict]:
    windows: list[dict] = []
    current: dict | None = None
    last_net_ts: int | None = None
    for e in events:
        payload = e.get("payload") or {}
        is_anchor = e["kind"] == "action" and payload.get("type") in ANCHOR_TYPES
        # S42-10：空 label 点击不开窗——必被噪声过滤丢弃，却会破坏
        # submit-after-click 去重的相邻性（保存 click 与 submit 之间夹
        # 1ms 空点击 → 重复保存步进骨架 → 回放二次点击超时）
        if is_anchor and payload.get("type") == "click":
            label = ((payload.get("target") or {}).get("label") or "").strip()
            if not label:
                is_anchor = False
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
            # S42-12：跨标签页流量不入窗——录制期间其他标签页的后台轮询
            # （禅道 ajaxGetMessage）带活跃 session_id 混入，污染 API 证据
            # （Jeecg 技能学到 /index.php 断言，回放永假失败）。网络事件带
            # pageUrl（发出页面），与锚点页面不同源则丢弃；无 pageUrl 的
            # 旧事件兼容保留
            anchor_origin = _origin((current["anchor"].get("payload") or {}).get("url"))
            member_origin = _origin(payload.get("pageUrl"))
            if anchor_origin and member_origin and anchor_origin != member_origin:
                continue
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
