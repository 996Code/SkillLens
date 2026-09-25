"""S10 Task2：噪声过滤——classify_windows 四规则 + process 挂接 + 幂等。

窗口结构（process 管道 build_windows 产物）：
  {"anchor": {seq, ts, kind="action", payload{type, target{label}}}, "members": [network...]}
规则（v1 启发式，常量可配）：
  ①read_only：无写方法（POST/PUT/DELETE/PATCH）且无 state_signals → 过滤
  ②orphan_click：成员仅锚点动作（无 network 无后续 action/snapshot）→ 过滤
  ③overlong：窗口时长（anchor ts → 最后成员 ts）> MAX_WINDOW_MS×2 → 过滤
  ④empty_label：锚点 label strip 后为空 → 过滤
"""
import json

from app.ingestion.noise_filter import classify_windows


def _net(seq, ts, method="POST", url="/orders/1/save", body='{"code":200}'):
    return {"seq": seq, "ts": ts, "kind": "network",
            "payload": {"method": method, "url": url, "status": 200,
                        "reqBody": "{}", "resBody": body}}


def _click(seq, ts, label="保存"):
    payload = {"type": "click"}
    if label is not None:
        payload["target"] = {"label": label, "tag": "button"}
    return {"seq": seq, "ts": ts, "kind": "action", "payload": payload}


def _snap(seq, ts, phase="after"):
    return {"seq": seq, "ts": ts, "kind": "snapshot",
            "payload": {"phase": phase, "forms": [], "labels": [], "tables": []}}


def test_rule_read_only():
    """纯读窗口：GET-only 且响应无状态信号 → read_only。"""
    w = [{"anchor": _click(1, 1000),
          "members": [_net(2, 1200, method="GET", url="/api/list", body='{"data":[]}')]}]
    assert classify_windows(w) == [{"window_seq": 0, "kept": False, "reason": "read_only"}]


def test_rule_read_only_get_with_signal_kept():
    """GET 但带 state_signals（resBody 有 status 字段）→ 保留（状态可见的读）。"""
    w = [{"anchor": _click(1, 1000),
          "members": [_net(2, 1200, method="GET", url="/api/list",
                           body='{"code":200,"status":"SUCCESS"}')]}]
    assert classify_windows(w) == [{"window_seq": 0, "kept": True, "reason": ""}]


def test_rule_orphan_click():
    """孤儿点击：锚点后无 network 也无后续事件 → orphan_click。"""
    w = [{"anchor": _click(1, 1000), "members": []}]
    assert classify_windows(w) == [{"window_seq": 0, "kept": False, "reason": "orphan_click"}]


def test_rule_orphan_click_with_snapshot_kept():
    """锚点后虽无 network 但有后续 snapshot（S8 快照通道）→ 不是孤儿 → 保留。
    既有 test_process_multiple_after_snapshots_takes_last 即此形态（防误杀）。"""
    w = [{"anchor": _click(1, 1000), "members": [],
          "snapshots": [_snap(2, 3000), _snap(3, 5000)]}]
    assert classify_windows(w) == [{"window_seq": 0, "kept": True, "reason": ""}]


def test_rule_overlong():
    """超长窗口：anchor→最后成员时长 > MAX_WINDOW_MS×2 → overlong。"""
    w = [{"anchor": _click(1, 1000), "members": [_net(2, 20000)]}]
    assert classify_windows(w) == [{"window_seq": 0, "kept": False, "reason": "overlong"}]


def test_rule_empty_label():
    """锚点 label 为空串 → empty_label。"""
    w = [{"anchor": _click(1, 1000, label=""), "members": [_net(2, 1200)]}]
    assert classify_windows(w) == [{"window_seq": 0, "kept": False, "reason": "empty_label"}]


def test_rule_empty_label_whitespace_only():
    """label 仅空白字符（strip 后空）→ empty_label。"""
    w = [{"anchor": _click(1, 1000, label="  "), "members": [_net(2, 1200)]}]
    assert classify_windows(w) == [{"window_seq": 0, "kept": False, "reason": "empty_label"}]


def test_normal_write_window_kept():
    """正常写窗口（POST + 状态信号）→ kept=True，reason 为空。"""
    w = [{"anchor": _click(1, 1000),
          "members": [_net(2, 1200, body='{"code":200,"status":"SUCCESS"}')]}]
    assert classify_windows(w) == [{"window_seq": 0, "kept": True, "reason": ""}]


def test_rule_priority_and_seq_kept():
    """多窗混合：每窗独立判定，window_seq 与输入序一致；写窗正常保留。"""
    w = [
        {"anchor": _click(1, 1000, label=""), "members": []},                # empty_label
        {"anchor": _click(2, 5000),
         "members": [_net(3, 5600, body='{"code":200}')]},                   # 正常写窗
        {"anchor": _click(4, 9000),
         "members": [_net(5, 9200, method="GET", url="/a", body='{"rows":[]}')]},  # read_only
    ]
    assert classify_windows(w) == [
        {"window_seq": 0, "kept": False, "reason": "empty_label"},
        {"window_seq": 1, "kept": True, "reason": ""},
        {"window_seq": 2, "kept": False, "reason": "read_only"},
    ]


# ---------- process 集成：挂接 + filtered_window 落库 + 幂等 + 审计端点 ----------

async def _seed_noisy_session(client) -> str:
    """正常写窗 + 三类噪声窗的混合会话。

    窗 0：纯读（GET 无信号）→ read_only
    窗 1：正常写窗（POST + code 信号）→ kept
    窗 2：孤儿点击 → orphan_click
    窗 3：空 label → empty_label
    """
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load"}},
        # 窗 0：read_only（GET 且 resBody 无 status/code/state/result 键）
        {"seq": 1, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "查询", "tag": "button"}}},
        {"seq": 2, "ts": 1400, "kind": "network",
         "payload": {"method": "GET", "url": "/api/rows/list", "status": 200,
                     "resBody": '{"rows":[]}'}},
        # 窗 1：正常写窗
        {"seq": 3, "ts": 5000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存", "tag": "button"}}},
        {"seq": 4, "ts": 5600, "kind": "network",
         "payload": {"method": "POST", "url": "/orders/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200,"status":"SUCCESS"}'}},
        # 窗 2：孤儿点击（其后无事件归属它——下一锚点 6 开新窗）
        {"seq": 5, "ts": 9000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "取消", "tag": "button"}}},
        # 窗 3：空 label + 写方法 → empty_label（规则①优先）
        {"seq": 6, "ts": 15000, "kind": "action",
         "payload": {"type": "click", "target": {"label": "", "tag": "div"}}},
        {"seq": 7, "ts": 15600, "kind": "network",
         "payload": {"method": "POST", "url": "/orders/2/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    return sid


async def test_process_filters_noise_windows(client):
    sid = await _seed_noisy_session(client)
    resp = await client.post(f"/api/v1/sessions/{sid}/process")
    assert resp.status_code == 200
    assert resp.json() == {"windows": 4, "kept": 1}

    # kept=False 的窗不生成 semantic_action：只剩窗 1（保存）
    rows = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert len(rows) == 1
    assert rows[0]["window_seq"] == 1
    assert rows[0]["target"]["label"] == "保存"

    # 过滤决策落库（C3 审计）
    fw = (await client.get(f"/api/v1/sessions/{sid}/filtered-windows")).json()
    assert fw == [{"window_seq": 0, "reason": "read_only"},
                  {"window_seq": 2, "reason": "orphan_click"},
                  {"window_seq": 3, "reason": "empty_label"}]


async def test_process_filter_idempotent(client):
    """同 session 重 process：先删旧 filtered_window 行再插，不重复累积。"""
    sid = await _seed_noisy_session(client)
    await client.post(f"/api/v1/sessions/{sid}/process")
    await client.post(f"/api/v1/sessions/{sid}/process")
    fw = (await client.get(f"/api/v1/sessions/{sid}/filtered-windows")).json()
    assert len(fw) == 3
    rows = (await client.get(f"/api/v1/sessions/{sid}/semantic-actions")).json()
    assert len(rows) == 1


async def test_filtered_windows_404(client):
    resp = await client.get("/api/v1/sessions/nonexistent/filtered-windows")
    assert resp.status_code == 404


async def test_process_clean_session_all_kept(client):
    """既有 fixture 形态（输入+点击保存+POST）：全 kept，零过滤。"""
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load"}},
        {"seq": 1, "ts": 100, "kind": "action",
         "payload": {"type": "input", "name": "订单名", "value": "v"}},
        {"seq": 2, "ts": 200, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存", "tag": "button"}}},
        {"seq": 3, "ts": 260, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    resp = await client.post(f"/api/v1/sessions/{sid}/process")
    assert resp.json() == {"windows": 1, "kept": 1}
    assert (await client.get(f"/api/v1/sessions/{sid}/filtered-windows")).json() == []
