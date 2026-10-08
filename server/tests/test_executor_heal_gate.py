"""三轮评审：LLM 定位提案的确定性成员校验（宪法 C1「LLM 只做归因，判定全确定性」）。

旧实现只挡配额/限流错误串（"您的Token额度已用完"实证）——LLM 幻觉出一个页面上
根本不存在的 label 会被照单采纳：
① 插件按该 label 找按钮必然 miss，白烧一次介入额度（总额度仅 2，烧完即判 fail）；
② 幻觉 label 以 status=proposed 落进 locate_proposal，污染人工复核队列，
   后续 verify/promote 链把它当真实候选晋升进骨架。

采纳规则改为确定性：提案必须逐字出现在本轮证据（page_texts + form_labels）里；
不在页面上 → 提案仍留痕（status=rejected, strategy=not_on_page）但不 heal。
"""
from app.db import SessionLocal
from app.models import LocateProposal, ReplayRun


async def _mk_run(label: str = "保存") -> int:
    """手工造首步带 label 的 run（真实 plan 首步是 goto，测不到介入链）。"""
    db = SessionLocal()
    try:
        run = ReplayRun(
            skill_id=1, mode="execute", status="running",
            plan={"steps": [], "url": "http://t/",
                  "executor_instructions": [
                      {"seq": 1, "op": "click", "label": label, "labels": [],
                       "timeout_ms": 5},
                      {"seq": 2, "op": "detach", "timeout_ms": 5}],
                  "executor_state": {"cursor": 0, "received": [],
                                     "interventions": 0, "overrides": {}}},
            executor="extension")
        db.add(run)
        db.commit()
        return run.id
    finally:
        db.close()


def _proposals() -> list[tuple[str, str, str]]:
    db = SessionLocal()
    try:
        return [(p.proposed_label, p.status, p.strategy)
                for p in db.query(LocateProposal).all()]
    finally:
        db.close()


async def _miss(client, run_id: int, page_texts: list[str],
                form_labels: list[str] | None = None) -> dict:
    evidence: dict = {"page_texts": page_texts}
    if form_labels is not None:
        evidence["form_labels"] = form_labels
    resp = await client.post(f"/api/v1/executor/runs/{run_id}/step",
                             json={"seq": 1, "result": "miss", "evidence": evidence})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_proposal_from_page_texts_is_adopted(client, monkeypatch):
    """正例：提案在 page_texts 里 → heal 照旧（S24 自愈链不回退）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "提交")
    run_id = await _mk_run()
    body = await _miss(client, run_id, ["提交", "取消"])
    ins = body["instruction"]
    assert ins.get("healed") is True
    assert ins["label"] == "提交"
    assert ("提交", "proposed", "") in _proposals()


async def test_proposal_from_form_labels_is_adopted(client, monkeypatch):
    """证据池含 form_labels（fill 步 miss 的常见形态）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "*表名")
    run_id = await _mk_run(label="表名")
    body = await _miss(client, run_id, ["新建"], form_labels=["*表名", "备注"])
    assert body["instruction"].get("healed") is True


async def test_hallucinated_proposal_not_adopted(client, monkeypatch):
    """反例：提案不在页面上 → 不 heal，提案以 rejected 留痕（不静默丢弃）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "确认删除全部数据")
    run_id = await _mk_run()
    body = await _miss(client, run_id, ["提交", "取消"])
    ins = body["instruction"]
    assert not ins.get("healed")
    assert ins.get("label") != "确认删除全部数据"
    rows = _proposals()
    assert rows, "幻觉提案应留痕供人工复核"
    assert all(status == "rejected" for _, status, _ in rows), rows
    assert rows[0][2] == "not_on_page"


async def test_infra_error_text_still_rejected(client, monkeypatch):
    """配额/限流错误串（既有防线）不回退：不落提案、不 heal。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "您的Token额度已用完，请充值")
    run_id = await _mk_run()
    body = await _miss(client, run_id, ["您的Token额度已用完，请充值", "提交"])
    assert not body["instruction"].get("healed")
    assert _proposals() == []


async def test_rejected_proposal_still_counts_intervention(client, monkeypatch):
    """介入额度按「尝试」计数（既有语义不回退）：幻觉提案不采纳也占额度；
    且不 heal 时 cursor 正常推进（响应给下一步，不再重发当前步）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE", "不存在的按钮")
    run_id = await _mk_run()
    body = await _miss(client, run_id, ["提交"])
    assert not body["instruction"].get("healed")
    assert body["instruction"]["seq"] == 2, "提案被拒后应推进到下一步"

    db = SessionLocal()
    try:
        state = (db.get(ReplayRun, run_id).plan or {})["executor_state"]
    finally:
        db.close()
    assert state["interventions"] == 1, "被拒提案未计入介入额度"
