from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.url_template import split_url, templatize_path
from app.models import TransactionWindow


def collect_window_params(db: Session, session_ids: list[str]) -> dict | None:
    """从各 session 的 transaction_window 行读切窗参数快照（对账用）。
    一致：{"idle_ms", "max_window_ms", "consistent": true}；
    不一致：{"sessions": {sid: {...}}, "consistent": false, "warn": true}；
    无窗口行（未 process 或空）：None。"""
    per_session: dict[str, dict] = {}
    for sid in session_ids:
        row = db.execute(
            select(TransactionWindow).where(TransactionWindow.session_id == sid)
            .order_by(TransactionWindow.window_seq).limit(1)
        ).scalar_one_or_none()
        if row is None:
            continue
        per_session[sid] = {"idle_ms": row.idle_ms, "max_window_ms": row.max_window_ms}
    if not per_session:
        return None
    unique = {tuple(sorted(p.items())) for p in per_session.values()}
    if len(unique) == 1:
        params = next(iter(per_session.values()))
        return {"idle_ms": params["idle_ms"], "max_window_ms": params["max_window_ms"],
                "consistent": True}
    return {"sessions": per_session, "consistent": False, "warn": True}


def _anchor_key(window: dict) -> str:
    anchor = window.get("anchor") or {}
    payload = anchor.get("payload") or {}
    label = (payload.get("target") or {}).get("label", "")
    return f"{payload.get('type', anchor.get('kind', ''))}:{label}"


def _api_set(window: dict) -> set[str]:
    parts: set[str] = set()
    for m in window.get("members") or []:
        p = m.get("payload") or {}
        if not p.get("url"):
            continue
        path, _ = split_url(p.get("url", ""))
        template, _ = templatize_path(path)
        parts.add(f"{p.get('method', 'GET')}:{template}")
    return parts


def window_signature(window: dict) -> str:
    api_parts = sorted(_api_set(window))
    if not api_parts:
        return _anchor_key(window)
    return f"{_anchor_key(window)}|{','.join(api_parts)}"


def lcs(a: list[str], b: list[str]) -> list[str]:
    return [a[i] for i, _ in _lcs_pairs(a, b)]


def _lcs_pairs(a: list[str], b: list[str]) -> list[tuple[int, int]]:
    """LCS 带下标对（锚点对齐需要窗口位置，不只是值）。"""
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    out: list[tuple[int, int]] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            out.append((i, j))
            i += 1
            j += 1
        elif dp[i + 1][j] >= dp[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


# 分桶阈值：LCS 相似度 >= 0.6 视为同任务的不同路径（宪法 §8：分叉先分桶再桶内对齐）
BUCKET_SIMILARITY_THRESHOLD = 0.6


def _seq_similarity(a: list[str], b: list[str]) -> float:
    """LCS 长度 / 较长序列长度。"""
    if not a or not b:
        return 0.0
    return len(lcs(a, b)) / max(len(a), len(b))


def _bucket_sessions(sig_lists: list[tuple[str, list[str]]]) -> list[list[str]]:
    """按窗口签名序列分桶：完全相同→同桶；与桶内任一成员相似度达标→归并。
    贪心顺序归并（首个入桶者作比较锚，MVP 语义）。"""
    buckets: list[list[str]] = []
    anchors: list[list[str]] = []
    for sid, sigs in sig_lists:
        placed = False
        for bi, anchor in enumerate(anchors):
            if sigs == anchor or _seq_similarity(sigs, anchor) >= BUCKET_SIMILARITY_THRESHOLD:
                buckets[bi].append(sid)
                placed = True
                break
        if not placed:
            buckets.append([sid])
            anchors.append(sigs)
    return buckets


def align_skeletons(windows_per_session: list[tuple[str, list[dict]]]) -> dict:
    """返回 {"skeleton": [...], "buckets": [{"sessions": [...], "skeleton": [...]}]}。

    S34 多目标泛化：锚点（type:label）相同视为同一步，API 段取全会话**交集**
    （话多 SPA 的窗口 API 集带偶发请求——autocomplete/轮询逐轮不同，
    精确串匹配会把整步丢出骨架；交集语义 = 单侧独有 API 不进骨架，
    与"单侧独有的窗口不得进骨架"同源）。buckets 按锚点序列分桶
    （偶发 API 差异不拆桶）。"""
    if not windows_per_session:
        return {"skeleton": [], "buckets": []}
    keyed = [(sid, [(_anchor_key(win), _api_set(win)) for win in windows])
             for sid, windows in windows_per_session]

    skeleton = _align_one(keyed)
    bucket_input = [(sid, [k for k, _ in items]) for sid, items in keyed]
    buckets = _bucket_sessions(bucket_input)
    out_buckets = []
    for members in buckets:
        out_buckets.append({
            "sessions": members,
            "skeleton": _align_one([kv for kv in keyed if kv[0] in members]),
        })
    return {"skeleton": skeleton, "buckets": out_buckets}


def _align_one(keyed: list[tuple[str, list[tuple[str, set[str]]]]]) -> list[dict]:
    """桶内对齐：锚点序列 LCS；每步 API 取出现会话的交集。

    entries: [(anchor, [(sid, window_idx, api_set), ...]), ...]
    """
    if not keyed:
        return []
    sid0, items0 = keyed[0]
    entries: list[tuple[str, list[tuple[str, int, set[str]]]]] = [
        (k, [(sid0, i, apis)]) for i, (k, apis) in enumerate(items0)
    ]
    for sid, items in keyed[1:]:
        pairs = _lcs_pairs([e[0] for e in entries], [k for k, _ in items])
        entries = [
            (entries[ci][0], entries[ci][1] + [(sid, ii, items[ii][1])])
            for ci, ii in pairs
        ]
        if not entries:
            break

    steps: list[dict] = []
    for anchor, occs in entries:
        api_sets = [s for _, _, s in occs]
        inter = set.intersection(*api_sets) if api_sets else set()
        sig = anchor if not inter else f"{anchor}|{','.join(sorted(inter))}"
        seqs = {occ_sid: idx for occ_sid, idx, _ in occs}
        steps.append({"signature": sig, "session_window_seqs": seqs})
    return steps
