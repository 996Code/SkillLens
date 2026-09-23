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
    sigs = [step["signature"] for step in result]
    assert sigs == ["click:打开", "click:保存|POST:/save"]


def test_align_records_window_seqs():
    s1 = [w("click", "打开"), w("click", "保存", [("POST", "/save")])]
    s2 = [w("click", "保存", [("POST", "/save")])]
    result = align_skeletons([("s1", s1), ("s2", s2)])
    save_step = next(s for s in result if s["signature"].startswith("click:保存"))
    assert save_step["session_window_seqs"] == {"s1": 1, "s2": 0}


def test_align_single_session_returns_all():
    s1 = [w("click", "a"), w("click", "b")]
    result = align_skeletons([("s1", s1)])
    assert [s["signature"] for s in result] == ["click:a", "click:b"]
