from app.ingestion.url_template import split_url, templatize_path


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
