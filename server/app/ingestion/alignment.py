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


def align_skeletons(windows_per_session: list[tuple[str, list[dict]]]) -> list[dict]:
    if not windows_per_session:
        return []
    sig_lists: list[tuple[str, list[str]]] = []
    for sid, windows in windows_per_session:
        sig_lists.append((sid, [window_signature(w) for w in windows]))

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
