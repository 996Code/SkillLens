"""S13 F1：Agent 运行时（LangGraph 底座）。

夜间回归图 v1（确定性编排，零 LLM）：
  select_skills（变更集 → impact 反查受影响 skill；无变更集 → 全量）
  → replay_batch（run_replay_batch 批量，confirm_side_effect=False——C1 影子模式零例外）
  → aggregate（pass/fail/error/shadow 计数）。

run_graph 全程落 agent_run（C3）：创建即 status=started，节点产物经
astream(stream_mode="updates") 逐段 append 到 node_outputs 并 commit；
成功 status=finished，异常 status=error + error_text（截 500）。
"""
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.learning import impact
from app.models import AgentRun, Skill, utcnow
from app.replay.runner import run_replay_batch


class NightlyState(TypedDict):
    # db 为进程内 Session（无 checkpointer，不序列化，仅供节点取数）
    db: Any
    change_set: dict
    skills: list
    replay_results: list
    aggregate: dict


async def select_skills(state: NightlyState) -> dict:
    db: Session = state["db"]
    change_set = state.get("change_set") or {}
    api_templates = change_set.get("api_templates") or []
    anchor_labels = change_set.get("anchor_labels") or []
    if api_templates or anchor_labels:
        result = impact.analyze_impact(db, api_templates, anchor_labels)
        skills = [s["skill_id"] for s in result.get("affected_skills") or []]
    else:
        # 排除 superseded：全量回归也只回放活跃版本
        skills = [s.id for s in db.query(Skill).filter(
            Skill.status != "superseded").all()]
    return {"skills": skills}


async def replay_batch(state: NightlyState) -> dict:
    db: Session = state["db"]
    # 批回放复用 browser 实例（全 shadow 批零 launch，C1 前置门控）；
    # 单 skill 异常由 batch 落 error run 继续，不中断夜间图
    runs = await run_replay_batch(db, list(state.get("skills") or []),
                                  {}, False)  # C1：夜间批回放默认 shadow
    return {"replay_results": [
        {"skill_id": r.skill_id, "run_id": r.id, "status": r.status} for r in runs]}


async def aggregate_results(state: NightlyState) -> dict:
    results = state.get("replay_results") or []
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    counts["total"] = len(results)
    return {"aggregate": counts}


def build_nightly_graph():
    """三节点夜间回归图（select_skills → replay_batch → aggregate）。"""
    graph = StateGraph(NightlyState)
    graph.add_node("select_skills", select_skills)
    graph.add_node("replay_batch", replay_batch)
    graph.add_node("aggregate", aggregate_results)
    graph.add_edge(START, "select_skills")
    graph.add_edge("select_skills", "replay_batch")
    graph.add_edge("replay_batch", "aggregate")
    graph.add_edge("aggregate", END)
    return graph.compile()


GRAPH_BUILDERS = {"nightly": build_nightly_graph}


async def run_graph(db: Session, graph_name: str, input: dict) -> AgentRun:
    """执行图并全程落 agent_run；任何异常都收敛为 status=error（不向上抛）。"""
    run = AgentRun(graph_name=graph_name, input=input or {}, node_outputs=[],
                   status="started", started_at=utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        builder = GRAPH_BUILDERS.get(graph_name)
        if builder is None:
            raise ValueError(f"unknown graph: {graph_name}")
        graph = builder()
        # 只提升 schema 内的键（LangGraph 状态通道校验），db 运行时注入
        state: NightlyState = {"db": db, "change_set": {}, "skills": [],
                               "replay_results": [], "aggregate": {}}
        for key in ("change_set",):
            if key in (input or {}):
                state[key] = input[key]
        async for update in graph.astream(state, stream_mode="updates"):
            for node, payload in update.items():
                if node.startswith("__"):
                    continue
                run.node_outputs = (run.node_outputs or []) + [
                    {"node": node, "output": payload}]
                db.commit()
        run.status = "finished"
        run.finished_at = utcnow()
        db.commit()
    except Exception as exc:
        # 异常可能源自 flush 失败（事务已坏）——先 rollback 再落 error，
        # 保证 error commit 不二次抛出（不向上抛承诺）
        db.rollback()
        run.status = "error"
        run.error_text = str(exc)[:500]
        run.finished_at = utcnow()
        db.commit()
    db.refresh(run)
    return run
