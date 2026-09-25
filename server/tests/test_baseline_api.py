"""Task 5 演示基线固化：/api/v1/baseline/skills* 字段与通过率计算（C2 对比锚）。"""
import json

from app.db import SessionLocal
from app.models import ReplayRun


async def _seed_skill(client, monkeypatch, llm_name="SaveForm", source=None,
                      values=("旧甲", "旧乙")):
    """参考 test_replay_api._seed_skill：两 session 输入值不同 → 有 input_variables。

    S10 Task5 扩展：source 标记会话来源（None=缺省 demo）；values 相同时
    无 input_variables → confidence 降为 0.6（对比比率的区分度来源）。"""
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": llm_name, "description": "d"}))
    sids = []
    for value in values:
        body = {"source": source} if source else {}
        sid = (await client.post("/api/v1/sessions", json=body)).json()["session_id"]
        events = [
            {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load", "url": "http://t/f"}},
            {"seq": 1, "ts": 100, "kind": "action",
             "payload": {"type": "input", "name": "请输入", "value": value}},
            {"seq": 2, "ts": 200, "kind": "action",
             "payload": {"type": "click", "target": {"label": "保存"}}},
            {"seq": 3, "ts": 260, "kind": "network",
             "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                         "reqBody": "{}", "resBody": '{"code":200}'}},
        ]
        await client.post(f"/api/v1/sessions/{sid}/events", json=events)
        await client.post(f"/api/v1/sessions/{sid}/process")
        sids.append(sid)
    aid = (await client.post("/api/v1/align", json={"session_ids": sids})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    return skill["id"]


def _add_replay_run(skill_id: int, assertion_results) -> int:
    """直接落 replay_run 行（API 层测试不依赖回放浏览器链路）。"""
    db = SessionLocal()
    try:
        run = ReplayRun(skill_id=skill_id, mode="execute", status="execute",
                        plan={"url": "http://t/f", "steps": []}, executed=[],
                        assertion_results=assertion_results)
        db.add(run)
        db.commit()
        db.refresh(run)
        return run.id
    finally:
        db.close()


async def test_baseline_list_fields(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, [{"passed": True}, {"passed": False}, {"passed": True}])

    resp = await client.get("/api/v1/baseline/skills")
    assert resp.status_code == 200
    items = resp.json()
    assert isinstance(items, list) and len(items) == 1
    item = items[0]
    assert item["skill_id"] == skill_id
    assert item["name"] == "SaveForm"
    assert item["status"] == "learned"
    assert item["confidence"] == 1.0            # api 步 0.6 + 有输入变量 0.4
    assert item["evidence_count"] == 2
    n_assertions = len((await client.get(f"/api/v1/skills/{skill_id}/assertions")).json())
    assert n_assertions >= 2                   # 至少 2 条 api_status（每 session 1 条）
    assert item["assertion_count"] == n_assertions
    assert item["assertion_pass_rate"] == round(2 / 3, 4)   # 最近 run：3 断言 2 过
    assert item["input_var_names"] == ["请输入"]
    assert item["window_params"] == {"idle_ms": 2000, "max_window_ms": 8000,
                                     "consistent": True}


async def test_baseline_pass_rate_uses_latest_run(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, [{"passed": True}, {"passed": True}])        # 旧 run 全过
    _add_replay_run(skill_id, [{"passed": False}, {"passed": False}])      # 新 run 全挂
    item = (await client.get("/api/v1/baseline/skills")).json()[0]
    assert item["assertion_pass_rate"] == 0.0


async def test_baseline_no_run_pass_rate_null(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    _add_replay_run(skill_id, None)   # shadow run（assertion_results 为 NULL）不算
    item = (await client.get("/api/v1/baseline/skills")).json()[0]
    assert item["assertion_count"] >= 2
    assert item["assertion_pass_rate"] is None


async def test_baseline_single_skill_and_404(client, monkeypatch):
    skill_id = await _seed_skill(client, monkeypatch)
    resp = await client.get(f"/api/v1/baseline/skills/{skill_id}")
    assert resp.status_code == 200
    item = resp.json()
    assert item["skill_id"] == skill_id
    assert set(item) == {"skill_id", "name", "status", "confidence",
                         "evidence_count", "assertion_count", "assertion_pass_rate",
                         "input_var_names", "window_params", "source"}

    assert (await client.get("/api/v1/baseline/skills/99999")).status_code == 404


async def test_baseline_source_field(client, monkeypatch):
    """S10 Task5：/baseline/skills 每项带 source（取首个 session 的来源，缺省 demo）。"""
    demo_id = await _seed_skill(client, monkeypatch, llm_name="DemoSkill")
    real_id = await _seed_skill(client, monkeypatch, llm_name="RealSkill",
                                source="real_traffic", values=("新甲", "新乙"))
    items = {i["skill_id"]: i for i in
             (await client.get("/api/v1/baseline/skills")).json()}
    assert items[demo_id]["source"] == "demo"
    assert items[real_id]["source"] == "real_traffic"


async def test_baseline_compare(client, monkeypatch):
    """S10 Task5：compare 端点——demo/real_traffic 聚合 + C2 比率。

    demo skill（有输入变量）confidence=1.0；real_traffic skill（同值输入→无变量）
    confidence=0.6 → ratio=0.6 < 0.8 不达标。"""
    demo_id = await _seed_skill(client, monkeypatch, llm_name="DemoSkill")
    real_id = await _seed_skill(client, monkeypatch, llm_name="RealSkill",
                                source="real_traffic", values=("同值", "同值"))
    _add_replay_run(demo_id, [{"passed": True}, {"passed": True}])      # pass_rate 1.0
    _add_replay_run(real_id, [{"passed": True}, {"passed": False}])    # pass_rate 0.5

    body = (await client.get("/api/v1/baseline/compare")).json()
    assert body["demo"] == {"count": 1, "avg_confidence": 1.0, "avg_pass_rate": 1.0}
    assert body["real_traffic"] == {"count": 1, "avg_confidence": 0.6,
                                    "avg_pass_rate": 0.5}
    assert body["vs_baseline"]["confidence_ratio"] == 0.6
    assert body["vs_baseline"]["pass_rate_ratio"] == 0.5
    assert body["vs_baseline"]["meets_c2"] is False


async def test_baseline_compare_no_real_traffic(client, monkeypatch):
    """无 real_traffic skill：比率 null（分母侧缺失，meets_c2=False 语义=不可判达标）。"""
    await _seed_skill(client, monkeypatch, llm_name="DemoSkill")
    body = (await client.get("/api/v1/baseline/compare")).json()
    assert body["demo"]["count"] == 1
    assert body["real_traffic"]["count"] == 0
    assert body["real_traffic"]["avg_confidence"] is None
    assert body["real_traffic"]["avg_pass_rate"] is None
    assert body["vs_baseline"]["confidence_ratio"] is None
    assert body["vs_baseline"]["pass_rate_ratio"] is None
    assert body["vs_baseline"]["meets_c2"] is False


async def test_baseline_compare_empty_db(client):
    """空库：两侧 count=0，全部 null，meets_c2=False。"""
    body = (await client.get("/api/v1/baseline/compare")).json()
    assert body["demo"]["count"] == 0
    assert body["real_traffic"]["count"] == 0
    assert body["vs_baseline"]["confidence_ratio"] is None
    assert body["vs_baseline"]["meets_c2"] is False


async def test_baseline_compare_meets_c2(client, monkeypatch):
    """达标侧：real/demo 置信度比 >= 0.8 → meets_c2=True。"""
    demo_id = await _seed_skill(client, monkeypatch, llm_name="DemoSkill")
    real_id = await _seed_skill(client, monkeypatch, llm_name="RealSkill",
                                source="real_traffic")
    body = (await client.get("/api/v1/baseline/compare")).json()
    assert body["demo"]["avg_confidence"] == 1.0
    assert body["real_traffic"]["avg_confidence"] == 1.0
    assert body["vs_baseline"]["confidence_ratio"] == 1.0
    assert body["vs_baseline"]["pass_rate_ratio"] is None   # 两侧都无有效 run
    assert body["vs_baseline"]["meets_c2"] is True
