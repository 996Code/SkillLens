"""S14 H2：编排画布——DAG 校验 + 动态 LangGraph 编译执行。

节点类型（v1 白名单）：
  change_source  产出 change_set（api_templates/anchor_labels）
  impact_select  调 analyze_impact 反查受影响 skill → skills
  replay_batch   调 run_replay_batch（confirm_side_effect 从节点 params 读，
                 默认 False——C1 影子模式零例外，运行时不可临时改）
  aggregate      回放结果计数
  review_output  生成 markdown 摘要字符串

执行通道：独立 run_canvas_graph（复制 S13 run_graph 的落库骨架，图构建不同
——按画布 DAG 动态 add_node/add_edge），不动已验证的 run_graph。
"""
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.learning import impact
from app.models import AgentRun, CanvasDag, utcnow
from app.replay.runner import run_replay_batch

NODE_TYPES = {"change_source", "impact_select", "replay_batch",
              "aggregate", "review_output"}

MAX_OUT_DEGREE = 1   # v1：每节点出度 ≤1（线性链，无分叉并行）
MAX_IN_DEGREE = 2    # v1：允许链尾汇聚（如两条链汇入同一 aggregate）

# S14 H4 预置"定向回归流水线"（等价 S13 夜间图 + review 节点）：
# change_source（保存表单配置模板）→ impact → shadow 批回放 → 聚合 → 摘要
PRESET_NAME = "定向回归流水线"
PRESET_DAG = {
    "nodes": [
        {"id": "n1", "type": "change_source",
         "params": {"api_templates": ["/codeBack/formConfig/saveFormConfig"]},
         "x": 0, "y": 0},
        {"id": "n2", "type": "impact_select", "params": {}, "x": 200, "y": 0},
        {"id": "n3", "type": "replay_batch",
         "params": {"confirm_side_effect": False}, "x": 400, "y": 0},
        {"id": "n4", "type": "aggregate", "params": {}, "x": 600, "y": 0},
        {"id": "n5", "type": "review_output", "params": {}, "x": 800, "y": 0},
    ],
    "edges": [
        {"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3"},
        {"from": "n3", "to": "n4"}, {"from": "n4", "to": "n5"},
    ],
}


def ensure_preset(db: Session):
    """canvas_dag 为空时插入预置"定向回归流水线"；非空则返回最新一行（不重复播种）。"""
    row = db.query(CanvasDag).order_by(CanvasDag.id.desc()).first()
    if row is not None:
        return row
    preset = CanvasDag(name=PRESET_NAME, dag=PRESET_DAG)
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


class CanvasState(TypedDict):
    # db 为进程内 Session（无 checkpointer，不序列化，仅供节点取数）
    db: Any
    change_set: dict
    skills: list
    replay_results: list
    aggregate: dict
    review: str


def validate_dag(dag) -> tuple[bool, list[str]]:
    """画布 DAG 校验（纯函数）：类型白名单/id 唯一/边引用存在/无环（DFS）/
    v1 度约束（出度 ≤1、入度 ≤2，超出报"v1 仅支持线性链"）/必填参数。"""
    if not isinstance(dag, dict):
        return False, ["dag 必须是对象"]
    nodes = dag.get("nodes")
    edges = dag.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        return False, ["dag.nodes 必须是非空数组"]
    if not isinstance(edges, list):
        return False, ["dag.edges 必须是数组"]

    errors: list[str] = []
    ids: list[str] = []
    for n in nodes:
        if not isinstance(n, dict):
            errors.append("节点必须是对象")
            continue
        nid = n.get("id")
        if not nid or not isinstance(nid, str):
            errors.append("节点缺少字符串 id")
        elif nid in ids:
            errors.append(f"节点 id 重复: {nid}")
        else:
            ids.append(nid)
        ntype = n.get("type")
        if ntype not in NODE_TYPES:
            errors.append(f"未知节点类型: {ntype}")
        params = n.get("params") if isinstance(n.get("params"), dict) else {}
        if n.get("params") is not None and not isinstance(n.get("params"), dict):
            errors.append(f"节点 {n.get('id')} params 必须是对象")
        if ntype == "change_source":
            if not (params.get("api_templates") or params.get("anchor_labels")):
                errors.append("change_source 需要非空 api_templates 或 anchor_labels")
        if ntype == "replay_batch":
            if not isinstance(params.get("confirm_side_effect", False), bool):
                errors.append("replay_batch 的 confirm_side_effect 必须是布尔")

    id_set = set(ids)
    out_deg: dict[str, int] = {}
    in_deg: dict[str, int] = {}
    adj: dict[str, list[str]] = {}
    for e in edges:
        if not isinstance(e, dict):
            errors.append("边必须是对象")
            continue
        src, dst = e.get("from"), e.get("to")
        if src not in id_set or dst not in id_set:
            errors.append(f"边引用不存在的节点: {src} → {dst}")
            continue
        out_deg[src] = out_deg.get(src, 0) + 1
        in_deg[dst] = in_deg.get(dst, 0) + 1
        adj.setdefault(src, []).append(dst)

    for nid, d in out_deg.items():
        if d > MAX_OUT_DEGREE:
            errors.append(f"v1 仅支持线性链：节点 {nid} 出度 {d} > {MAX_OUT_DEGREE}")
    for nid, d in in_deg.items():
        if d > MAX_IN_DEGREE:
            errors.append(f"v1 仅支持线性链：节点 {nid} 入度 {d} > {MAX_IN_DEGREE}")

    # 无环检测（DFS 三色标记）
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in ids}

    def has_cycle(nid: str) -> bool:
        color[nid] = GRAY
        for nxt in adj.get(nid, []):
            if color[nxt] == GRAY:
                return True
            if color[nxt] == WHITE and has_cycle(nxt):
                return True
        color[nid] = BLACK
        return False

    if any(color[nid] == WHITE and has_cycle(nid) for nid in ids):
        errors.append("DAG 存在环")

    # 连通性：v1 不做多链并行——多节点画布必须是单个（弱）连通分量
    if len(ids) > 1:
        seen = {ids[0]}
        stack = [ids[0]]
        undirected: dict[str, list[str]] = {}
        for src, dsts in adj.items():
            for dst in dsts:
                undirected.setdefault(src, []).append(dst)
                undirected.setdefault(dst, []).append(src)
        while stack:
            cur = stack.pop()
            for nxt in undirected.get(cur, []):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        if seen != set(ids):
            errors.append("v1 仅支持线性链：DAG 未连通")

    return (not errors), errors


def _make_step(db: Session, node: dict):
    """节点类型 → 执行步骤（闭包持有 db 与节点 params；confirm 在编译期定格）。"""
    ntype = node["type"]
    params = node.get("params") or {}

    if ntype == "change_source":
        async def step(state: CanvasState) -> dict:
            return {"change_set": {
                "api_templates": list(params.get("api_templates") or []),
                "anchor_labels": list(params.get("anchor_labels") or [])}}
    elif ntype == "impact_select":
        async def step(state: CanvasState) -> dict:
            cs = state.get("change_set") or {}
            result = impact.analyze_impact(db, cs.get("api_templates") or [],
                                           cs.get("anchor_labels") or [])
            return {"skills": [s["skill_id"] for s in
                               result.get("affected_skills") or []]}
    elif ntype == "replay_batch":
        # C1：confirm_side_effect 从节点 params 读（编译期定格，默认 False），
        # 运行时不可临时改
        confirm = bool(params.get("confirm_side_effect", False))

        async def step(state: CanvasState) -> dict:
            runs = await run_replay_batch(db, list(state.get("skills") or []),
                                          {}, confirm)
            return {"replay_results": [
                {"skill_id": r.skill_id, "run_id": r.id, "status": r.status}
                for r in runs]}
    elif ntype == "aggregate":
        async def step(state: CanvasState) -> dict:
            results = state.get("replay_results") or []
            counts: dict[str, int] = {}
            for r in results:
                counts[r["status"]] = counts.get(r["status"], 0) + 1
            counts["total"] = len(results)
            return {"aggregate": counts}
    elif ntype == "review_output":
        async def step(state: CanvasState) -> dict:
            cs = state.get("change_set") or {}
            skills = state.get("skills") or []
            agg = state.get("aggregate") or {}
            lines = [
                "# 画布运行摘要",
                f"- 变更集：api_templates={cs.get('api_templates') or []}，"
                f"anchor_labels={cs.get('anchor_labels') or []}",
                f"- 受影响 skill：{len(skills)} 个（{', '.join(str(s) for s in skills)}）",
                f"- 回放结果：total={agg.get('total', 0)}，"
                f"pass={agg.get('pass', 0)}，fail={agg.get('fail', 0)}，"
                f"error={agg.get('error', 0)}，shadow={agg.get('shadow', 0)}",
            ]
            return {"review": "\n".join(lines)}
    else:  # 白名单外（validate 已拦截，防御兜底）
        async def step(state: CanvasState) -> dict:
            raise ValueError(f"未知节点类型: {ntype}")
    return step


def build_canvas_graph(db: Session, dag: dict):
    """按画布 DAG 动态建图：节点 id 作图节点名，边照搬，度约束由 validate 保证。"""
    nodes = dag["nodes"]
    edges = dag.get("edges") or []
    graph = StateGraph(CanvasState)
    for node in nodes:
        graph.add_node(node["id"], _make_step(db, node))
    out_ids = {e["from"] for e in edges}
    in_ids = {e["to"] for e in edges}
    for node in nodes:
        if node["id"] not in in_ids:
            graph.add_edge(START, node["id"])
    for e in edges:
        graph.add_edge(e["from"], e["to"])
    for node in nodes:
        if node["id"] not in out_ids:
            graph.add_edge(node["id"], END)
    return graph.compile()


async def compile_and_run(db: Session, canvas_row) -> AgentRun:
    """编译画布 DAG 并执行，全程落 agent_run（复制 run_graph 落库骨架）。

    graph_name=canvas:{id}，input 记 canvas_id；任何异常收敛为 status=error
    （不向上抛），节点产物经 astream(updates) 逐段 append 落库。
    """
    canvas_id = canvas_row.id
    run = AgentRun(graph_name=f"canvas:{canvas_id}",
                   input={"canvas_id": canvas_id}, node_outputs=[],
                   status="started", started_at=utcnow())
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        ok, errors = validate_dag(canvas_row.dag)
        if not ok:
            raise ValueError("invalid dag: " + "; ".join(errors))
        graph = build_canvas_graph(db, canvas_row.dag)
        state: CanvasState = {"db": db, "change_set": {}, "skills": [],
                              "replay_results": [], "aggregate": {}, "review": ""}
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
        # 保证 error commit 不二次抛出（不向上抛承诺，同 run_graph）
        db.rollback()
        run.status = "error"
        run.error_text = str(exc)[:500]
        run.finished_at = utcnow()
        db.commit()
    db.refresh(run)
    return run
