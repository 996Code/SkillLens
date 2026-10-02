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


def _normalize_dynamic_keys(
        keyed: list[tuple[str, list[tuple[str, set[str]]]]],
        windows_per_session: list[tuple[str, list[dict]]],
        ) -> list[tuple[str, list[tuple[str, set[str]]]]]:
    """S43-4：动态值 label 归一——每轮录制点击的"当轮实体名"（角色名/
    单据号）跨会话必然不同，精确键 LCS 丢步（若依角色选项实测）。
    判据（确定性）：click label 命中本会话某 input 值（== 或含，值
    ≥3 字符）→ 该步是"选择刚输入/刚建的实体"；两会话同位置（±2）
    都判动态 → 双侧改占位键 click:⟨dyn⟩（LCS 才能对上）。稳定 UI
    词不命中 input 值，不受影响。"""
    if len(keyed) < 2:
        return keyed

    def _split(k: str) -> tuple[str, str]:
        typ, _, label = k.partition(":")
        return typ, label

    input_values: dict[str, set[str]] = {}
    for (sid, windows) in windows_per_session:
        vals: set[str] = set()
        for win in windows:
            p = (win.get("anchor") or {}).get("payload") or {}
            if p.get("type") == "input":
                v = str(p.get("value", ""))
                if len(v) >= 3:
                    vals.add(v)
        input_values[sid] = vals

    def _is_dynamic(sid: str, label: str) -> bool:
        for v in input_values.get(sid, ()):
            if label == v or (len(v) >= 3 and v in label):
                return True
        return False

    # 每会话的动态 click 位置集（按原始键判定）
    dyn_flags: list[list[bool]] = []
    for sid, items in keyed:
        flags = []
        for k, _ in items:
            typ, label = _split(k)
            flags.append(typ == "click" and bool(label)
                         and _is_dynamic(sid, label))
        dyn_flags.append(flags)

    def _pair_dyn(a_idx: int, b_idx: int) -> bool:
        """两会话 a/b 在位置 a_idx/b_idx（±2 内可对位）双侧均动态。"""
        for j in range(max(0, b_idx - 2), min(len(keyed[a_idx][1]), b_idx + 3)):
            if dyn_flags[a_idx][j]:
                return True
        return False

    out: list[tuple[str, list[tuple[str, set[str]]]]] = []
    for s_idx, (sid, items) in enumerate(keyed):
        new_items = []
        for i, (k, apis) in enumerate(items):
            if not dyn_flags[s_idx][i]:
                new_items.append((k, apis))
                continue
            # 其他任一会话近位也有动态 click → 归一
            dyn = False
            for o_idx in range(len(keyed)):
                if o_idx == s_idx:
                    continue
                if _pair_dyn(o_idx, i):
                    dyn = True
                    break
            new_items.append(("click:⟨dyn⟩" if dyn else k, apis))
        out.append((sid, new_items))
    return out


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
    keyed = _normalize_dynamic_keys(keyed, windows_per_session)

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
    """桶内对齐：锚点序列 LCS + 孤立动态对缝合；每步 API 取出现会话交集。"""
    if not keyed:
        return []
    sid0, items0 = keyed[0]
    entries: list[tuple[str, list[tuple[str, int, set[str]]]]] = [
        (k, [(sid0, i, apis)]) for i, (k, apis) in enumerate(items0)
    ]
    for sid, items in keyed[1:]:
        # S42-9：LCS 只按锚点键比对（click:解决方案）——API 部分是窗口
        # 证据非步身份：两轮录制同一操作，一轮窗口恰好挂了 GET（模态
        # 加载）、一轮没有（缓存），全签名比对必丢步（禅道流转链实测）
        pairs = _lcs_pairs([e[0].split("|")[0] for e in entries],
                           [k.split("|")[0] for k, _ in items])
        matched_e = {ci for ci, _ in pairs}
        matched_n = {ii for _, ii in pairs}
        new_entries: list[tuple[str, list[tuple[str, int, set[str]]]]] = []
        ei, ni = 0, 0
        while ei < len(entries) or ni < len(items):
            if ei < len(entries) and ni < len(items)                     and (ei, ni) in {(a, b) for a, b in pairs}:
                # LCS 配对步：合并会话 occ
                new_entries.append((entries[ei][0],
                                    entries[ei][1] + [(sid, ni, items[ni][1])]))
                ei += 1
                ni += 1
                continue
            # S43-4：孤立动态对缝合——基准侧 ei 落单 click + 新侧 ni 落单
            # click（都不在 matched）→ 判同一步（两轮点击"当轮实体名"，
            # 键取基准侧保录制语义；Healenium 位置+类型相似思想）。
            # 动态特征门（防稳定词误缝：测试"国内/国际"这类 2 字词不缝）
            # ——label 须 ≥4 字符且含 ASCII 字母/数字（实体名特征：
            # 角色名/单据号都带轮次标记或英文名）
            def _dynish(k: str) -> bool:
                lbl = k.partition(":")[2]
                return len(lbl) >= 4 and any(c.isascii() and c.isalnum() for c in lbl)
            if (ei < len(entries) and ei not in matched_e
                    and _dynish(entries[ei][0])
                    and ni < len(items) and ni not in matched_n
                    and _dynish(items[ni][0])):
                new_entries.append((entries[ei][0],
                                    entries[ei][1] + [(sid, ni, items[ni][1])]))
                ei += 1
                ni += 1
                continue
            # 其余：未配对步丢弃（原 LCS 语义——单侧独有不进骨架）；
            # 仅推进指针
            if ei < len(entries) and (ni >= len(items) or ei not in matched_e):
                ei += 1
            elif ni < len(items):
                ni += 1
            else:
                ei += 1
        entries = new_entries
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


