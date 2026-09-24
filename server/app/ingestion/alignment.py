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


def window_signature(window: dict) -> str:
    anchor = window.get("anchor") or {}
    payload = anchor.get("payload") or {}
    label = (payload.get("target") or {}).get("label", "")
    anchor_part = f"{payload.get('type', anchor.get('kind', ''))}:{label}"
    api_parts = []
    for m in window.get("members") or []:
        p = m.get("payload") or {}
        path, _ = split_url(p.get("url", ""))
        template, _ = templatize_path(path)
        api_parts.append(f"{p.get('method', 'GET')}:{template}")
    if not api_parts:
        return anchor_part
    return f"{anchor_part}|{','.join(sorted(api_parts))}"


def lcs(a: list[str], b: list[str]) -> list[str]:
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            if a[i] == b[j]:
                dp[i][j] = dp[i + 1][j + 1] + 1
            else:
                dp[i][j] = max(dp[i + 1][j], dp[i][j + 1])
    out: list[str] = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            out.append(a[i])
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
    skeleton 保持原跨全 session 的 LCS 语义（Skill 断言证据范围，Sprint 3 fix1：
    单侧独有的窗口不得进骨架）；buckets 是多路径策略记录（每桶桶内对齐）。"""
    if not windows_per_session:
        return {"skeleton": [], "buckets": []}
    sig_lists: list[tuple[str, list[str]]] = []
    for sid, windows in windows_per_session:
        sig_lists.append((sid, [window_signature(w) for w in windows]))

    skeleton = _align_one(sig_lists)
    buckets = _bucket_sessions(sig_lists)
    out_buckets = []
    for members in buckets:
        out_buckets.append({
            "sessions": members,
            "skeleton": _align_one([s for s in sig_lists if s[0] in members]),
        })
    return {"skeleton": skeleton, "buckets": out_buckets}


def _align_one(sig_lists: list[tuple[str, list[str]]]) -> list[dict]:
    """桶内对齐（原 align_skeletons 逻辑，输入已是签名序列）。"""
    ref = sig_lists[0][1]
    common = list(ref)
    for _, sigs in sig_lists[1:]:
        common = lcs(common, sigs)
        if not common:
            break

    steps: list[dict] = []
    for signature in common:
        seqs: dict[str, int] = {}
        for sid, sigs in sig_lists:
            if signature in sigs:
                # index 取首个匹配（重复签名场景取第一次出现，MVP 语义）
                seqs[sid] = sigs.index(signature)
        steps.append({"signature": signature, "session_window_seqs": seqs})
    return steps
