"""S12 Task 1（N1 新功能增量发现）：process 发现步 + discovered_feature 落库 + 列表端点。

发现语义（全局累加资产，同 evidence_edge）：
- 新 API 模板 / 新锚点 label → discovered_feature 行 status=new；
- 同模板跨会话出现 → observed_count 累加；同会话重 process → 不重复计数（幂等）；
- evidence_edge.dst 已知者（induce 造边）→ 不产生新行。
"""


async def _seed(client, url="/codeBack/formConfig/saveFormConfig", label="保存"):
    """单锚点会话：click(label) + POST(url)——含写方法，窗口必 kept。"""
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load"}},
        {"seq": 1, "ts": 1000, "kind": "action",
         "payload": {"type": "click", "target": {"label": label, "tag": "button"}}},
        {"seq": 2, "ts": 1600, "kind": "network",
         "payload": {"method": "POST", "url": url, "status": 200, "duration": 74,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    assert (await client.post(f"/api/v1/sessions/{sid}/events", json=events)).status_code == 200
    return sid


async def _discoveries(client, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/v1/discoveries{('?' + qs) if qs else ''}"
    return (await client.get(url)).json()


async def test_new_api_template_discovered(client):
    sid = await _seed(client)
    resp = await client.post(f"/api/v1/sessions/{sid}/process")
    assert resp.status_code == 200
    rows = await _discoveries(client)
    api_rows = [r for r in rows if r["api_template"] == "/codeBack/formConfig/saveFormConfig"]
    assert len(api_rows) == 1
    row = api_rows[0]
    assert row["status"] == "new"
    assert row["observed_count"] == 1
    assert row["session_id"] == sid
    assert row["linked_delta_id"] is None
    # 锚点 label 同步发现（纯 UI 行：api_template 为空）
    label_rows = [r for r in rows if r["anchor_label"] == "保存"]
    assert len(label_rows) == 1
    assert label_rows[0]["api_template"] is None
    assert label_rows[0]["observed_count"] == 1


async def test_second_session_accumulates_count(client):
    sid1 = await _seed(client)
    sid2 = await _seed(client)
    await client.post(f"/api/v1/sessions/{sid1}/process")
    await client.post(f"/api/v1/sessions/{sid2}/process")
    rows = await _discoveries(client)
    api_row = next(r for r in rows if r["api_template"] == "/codeBack/formConfig/saveFormConfig")
    assert api_row["observed_count"] == 2
    label_row = next(r for r in rows if r["anchor_label"] == "保存")
    assert label_row["observed_count"] == 2


async def test_reprocess_same_session_idempotent(client):
    sid1 = await _seed(client)
    sid2 = await _seed(client)
    await client.post(f"/api/v1/sessions/{sid1}/process")
    await client.post(f"/api/v1/sessions/{sid2}/process")
    await client.post(f"/api/v1/sessions/{sid2}/process")  # 同会话重跑：不重复累加
    rows = await _discoveries(client)
    api_row = next(r for r in rows if r["api_template"] == "/codeBack/formConfig/saveFormConfig")
    assert api_row["observed_count"] == 2


async def test_known_templates_create_no_rows(client):
    # 两会话同模板 → align → induce 造 evidence_edge（dst 含 click:保存 与 POST:/orders/{id}/save）
    sids = [await _seed(client, url=f"/orders/{oid}/save") for oid in (111, 222)]
    for sid in sids:
        await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
    assert (await client.post(f"/api/v1/alignments/{aid}/induce")).status_code == 200
    # 第三会话同模板：全部已知 → 无新行、既有计数不变
    sid3 = await _seed(client, url="/orders/333/save")
    await client.post(f"/api/v1/sessions/{sid3}/process")
    rows = await _discoveries(client)
    assert len(rows) == 2  # induce 前两会话已发现的 api 行 + label 行，第三会话零贡献
    api_row = next(r for r in rows if r["api_template"] == "/orders/{id}/save")
    label_row = next(r for r in rows if r["anchor_label"] == "保存")
    assert api_row["observed_count"] == 2
    assert label_row["observed_count"] == 2


async def test_discoveries_status_filter_and_order(client):
    sid1 = await _seed(client, url="/feat/a")
    sid2 = await _seed(client, url="/feat/a")
    sid3 = await _seed(client, url="/feat/b", label="其他")
    for sid in (sid1, sid2, sid3):
        await client.post(f"/api/v1/sessions/{sid}/process")
    rows = await _discoveries(client, status="new")
    assert rows and all(r["status"] == "new" for r in rows)
    assert rows[0]["observed_count"] >= rows[-1]["observed_count"]  # observed_count 倒序
    assert await _discoveries(client, status="linked") == []


# ---------- S12 Task 2（N2 Requirement 先验对齐） ----------

async def _confirmed_delta(client, monkeypatch, changes) -> dict:
    """造一个 confirmed 的 expected delta（LLM 垃圾输出 → draft，confirm 时修订 changes）。"""
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "垃圾输出非 JSON")
    body = (await client.post("/api/v1/expected-deltas",
                              json={"requirement_id": "req-d", "requirement_text": "需求"})).json()
    rc = await client.post(f"/api/v1/expected-deltas/{body['id']}/confirm",
                           json={"reviewed_by": "t", "changes": changes})
    assert rc.status_code == 200
    return rc.json()


async def test_confirm_links_matching_discoveries(client, monkeypatch):
    # 造 discovery：新 API 模板 + 新锚点 label
    sid = await _seed(client, url="/codeBack/newFeature/create", label="新建功能")
    await client.post(f"/api/v1/sessions/{sid}/process")

    # confirm：api_add 精确匹配 + ui_action 子串匹配（anchor_label ⊂ value）
    resp = await _confirmed_delta(client, monkeypatch, [
        {"type": "api_add", "value": "/codeBack/newFeature/create"},
        {"type": "ui_action", "value": "新增「新建功能」按钮"},
    ])
    assert resp["status"] == "confirmed"
    assert resp["linked_discoveries"] == 2

    rows = await _discoveries(client, status="linked", linked_delta_id=resp["id"])
    assert len(rows) == 2
    assert all(r["linked_delta_id"] == resp["id"] for r in rows)
    assert {r["api_template"] for r in rows} == {"/codeBack/newFeature/create", None}
    # linked 过滤与 new 互斥：无残留 new 行
    assert await _discoveries(client, status="new") == []


async def test_confirm_without_match_keeps_new(client, monkeypatch):
    sid = await _seed(client, url="/x/y")
    await client.post(f"/api/v1/sessions/{sid}/process")

    resp = await _confirmed_delta(client, monkeypatch, [
        {"type": "api_add", "value": "/完全/不同的路径"},
        {"type": "ui_action", "value": "毫不相干的界面改动"},
    ])
    assert resp["status"] == "confirmed"
    assert resp["linked_discoveries"] == 0
    rows = await _discoveries(client, status="new")
    assert rows and all(r["status"] == "new" and r["linked_delta_id"] is None for r in rows)
    assert await _discoveries(client, status="linked") == []
