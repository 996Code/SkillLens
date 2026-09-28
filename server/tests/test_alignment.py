from app.ingestion.alignment import align_skeletons, lcs, window_signature


def w(anchor_type, label, apis=()):
    return {
        "anchor": {"seq": 0, "ts": 0, "kind": "action",
                   "payload": {"type": anchor_type, "target": {"label": label}}},
        "members": [
            {"seq": 1, "ts": 1, "kind": "network",
             "payload": {"method": m, "url": u}} for m, u in apis
        ],
        "end_ts": 0,
    }


def test_window_signature():
    sig = window_signature(w("click", "保存", [("POST", "/a/1/save"), ("GET", "/a/1")]))
    assert sig == "click:保存|GET:/a/{id},POST:/a/{id}/save"  # 模板化+排序


def test_lcs_basic():
    assert lcs(["a", "b", "c", "d"], ["b", "d", "e"]) == ["b", "d"]


def test_align_finds_common_skeleton():
    s1 = [w("click", "打开"), w("click", "保存", [("POST", "/save")]), w("click", "关闭")]
    s2 = [w("click", "打开"), w("click", "保存", [("POST", "/save")])]
    result = align_skeletons([("s1", s1), ("s2", s2)])
    sigs = [step["signature"] for step in result["skeleton"]]
    assert sigs == ["click:打开", "click:保存|POST:/save"]


def test_align_records_window_seqs():
    s1 = [w("click", "打开"), w("click", "保存", [("POST", "/save")])]
    s2 = [w("click", "保存", [("POST", "/save")])]
    result = align_skeletons([("s1", s1), ("s2", s2)])
    # skeleton 保持跨全 session LCS 语义（s2 的保存步也进骨架）；
    # 两序列相似度 0.5 < 0.6 → buckets 分两桶（策略记录层面）
    assert len(result["buckets"]) == 2
    save_step = next(s for s in result["skeleton"] if s["signature"].startswith("click:保存"))
    assert save_step["session_window_seqs"] == {"s1": 1, "s2": 0}


def test_align_single_session_returns_all():
    s1 = [w("click", "a"), w("click", "b")]
    result = align_skeletons([("s1", s1)])
    assert [s["signature"] for s in result["skeleton"]] == ["click:a", "click:b"]
    assert len(result["buckets"]) == 1 and result["buckets"][0]["sessions"] == ["s1"]


def test_align_tolerates_incidental_api_noise():
    """S34 多目标泛化：话多 SPA（Odoo 等）窗口 API 集带偶发请求
    （autocomplete/mail 轮询），逐轮不同。锚点相同即同一步；骨架 API
    取全会话交集（单侧独有 API 不进骨架——既有语义延伸到 API 级）。"""
    s1 = [w("click", "New", [("POST", "/onchange")]),
          w("click", "Save", [("POST", "/onchange"), ("POST", "/save"),
                              ("POST", "/autocomplete")])]
    s2 = [w("click", "New", [("POST", "/onchange")]),
          w("click", "Save", [("POST", "/onchange"), ("POST", "/save")])]
    result = align_skeletons([("s1", s1), ("s2", s2)])
    sigs = [step["signature"] for step in result["skeleton"]]
    assert sigs == ["click:New|POST:/onchange",
                    "click:Save|POST:/onchange,POST:/save"]
    # 偶发 API 差异不拆桶（同路径）
    assert len(result["buckets"]) == 1


def test_align_anchor_same_but_disjoint_apis_keeps_anchor_only():
    """锚点相同但 API 完全不相交：步进骨架（锚点证据），API 段为空。"""
    s1 = [w("click", "Save", [("POST", "/a")])]
    s2 = [w("click", "Save", [("POST", "/b")])]
    result = align_skeletons([("s1", s1), ("s2", s2)])
    assert [s["signature"] for s in result["skeleton"]] == ["click:Save"]


def _sess(sid, labels):
    """造 (sid, 窗口签名序列) 的最小替身——分桶只消费签名序列。"""
    return (sid, labels)


def test_seq_similarity_lcs_ratio():
    from app.ingestion.alignment import _seq_similarity
    a = ["click:输入", "click:保存"]
    b = ["click:选型", "click:输入", "click:保存"]
    assert abs(_seq_similarity(a, b) - 2 / 3) < 1e-9
    assert _seq_similarity(a, a) == 1.0
    assert _seq_similarity(a, ["click:查询", "click:导出"]) == 0.0


def test_bucket_same_signature_single_bucket():
    from app.ingestion.alignment import _bucket_sessions
    sigs = [("s1", ["click:保存"]), ("s2", ["click:保存"]), ("s3", ["click:保存"])]
    buckets = _bucket_sessions(sigs)
    assert len(buckets) == 1
    assert sorted(buckets[0]) == ["s1", "s2", "s3"]


def test_bucket_similar_paths_merged():
    from app.ingestion.alignment import _bucket_sessions
    a = ["click:输入", "click:保存"]
    b = ["click:选型", "click:输入", "click:保存"]  # LCS 2/3 >= 0.6
    buckets = _bucket_sessions([("s1", a), ("s2", b)])
    assert len(buckets) == 1 and set(buckets[0]) == {"s1", "s2"}


def test_bucket_disjoint_paths_separate():
    from app.ingestion.alignment import _bucket_sessions
    a = ["click:输入", "click:保存"]
    c = ["click:查询", "click:导出"]
    buckets = _bucket_sessions([("s1", a), ("s2", c)])
    assert len(buckets) == 2
    assert buckets[0] == ["s1"] and buckets[1] == ["s2"]
