"""S38 统一流程图：Run → 节点+边+执行注记的图（流程图为全系统基座）。

节点类型（业务语义层）：
- page    页面（起始 URL）
- action  操作（input/click，带截图/成败/定位策略）
- state   业务状态（从 API 响应状态字段确定性派生：status/state/code）
- assert  校验（断言结果）

每节点：{id, type, label, status, screenshot?, io?}；
status: ok|fail|skipped|pending（执行注记，前端着色）。
边：顺序连线（action 链）；state/assert 挂在对应动作之后。
"""
import json

from app.ingestion.url_template import split_url, templatize_path


def _tpl(url: str) -> str:
    path, _ = split_url(url or "")
    template, _ = templatize_path(path)
    return template or url or ""


def _body_states(body: str) -> list[dict]:
    """API 响应体的业务状态字段（确定性规则：status/state/code 首个命中）。"""
    try:
        data = json.loads(body) if body else None
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []
    # S38：状态字段规则（确定性）——顶层 status/state/code（njmind 等）；
    # docstatus（Frappe/ERPNext：0=草稿 1=已提交 2=已取消）；
    # 嵌套 data.status（部分网关包一层 data）
    for key in ("status", "state", "code", "docstatus"):
        v = data.get(key)
        if v is not None and not isinstance(v, (dict, list)):
            return [{"field": key, "value": str(v)}]
    # 嵌套：data.status（部分网关）/ message.docstatus（Frappe 全响应包 message）
    for wrapper in ("data", "message"):
        nested = data.get(wrapper)
        if isinstance(nested, dict):
            for key in ("status", "state", "docstatus"):
                v = nested.get(key)
                if v is not None and not isinstance(v, (dict, list)):
                    return [{"field": key, "value": str(v)}]
    return []


def derive_states(observed: list[dict]) -> list[dict]:
    """从观测响应派生业务状态（runner 执行时调用，随 plan 落库持久）。

    确定性规则：响应体 JSON 的 status/state/code 字段（首个命中）；
    去重（同字段同值只记一次）。
    """
    out: list[dict] = []
    seen: set[str] = set()
    for o in observed or []:
        for st in _body_states(o.get("body", "")):
            key = f"{st['field']}={st['value']}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"field": st["field"], "value": st["value"],
                        "source": f"{o.get('method', 'GET')} {_tpl(o.get('url', ''))}"})
    return out


def build_run_flow(run) -> dict:
    """ReplayRun → 统一流程图（只读结构，前端 Vue Flow 渲染）。"""
    plan = run.plan or {}
    executed = run.executed or []
    assertions = run.assertion_results or []
    shots = (plan.get("step_screenshots") or {}).get("files") or []

    nodes: list[dict] = []
    edges: list[dict] = []

    def add(node: dict) -> str:
        nodes.append(node)
        return node["id"]

    # 起始页面
    prev = add({"id": "n0", "type": "page", "label": _tpl(plan.get("url", "")),
                "status": "ok" if run.status != "error" else "fail"})
    if shots and shots[0] == "start.png":
        nodes[0]["screenshot"] = "start.png"

    # 操作链（含每步截图/成败）
    shot_idx = 1
    for i, step in enumerate(executed, start=1):
        kind = str(step.get("kind", ""))
        label = str(step.get("label") or step.get("name") or kind)
        status = "ok" if step.get("ok") else "fail"
        node = {"id": f"a{i}", "type": "action", "label": f"{kind} {label}",
                "status": status,
                "io": {"strategy": step.get("strategy"),
                       "error": step.get("error"),
                       "value": step.get("value")}}
        shot = f"step-{i:02d}.png"
        if shot in shots:
            node["screenshot"] = shot
        cur = add(node)
        edges.append({"from": prev, "to": cur})
        prev = cur
        shot_idx = i + 1

    # 业务状态（执行时派生随 plan 落库：plan.business_states）
    for st in plan.get("business_states") or []:
        cur = add({"id": f"s{len(nodes)}", "type": "state",
                   "label": f"{st.get('field')}={st.get('value')}",
                   "status": "ok",
                   "io": {"source": st.get("source", "")}})
        edges.append({"from": prev, "to": cur})
        prev = cur

    # 校验节点（断言结果，从链尾分叉）
    for i, a in enumerate(assertions, start=1):
        p = a.get("payload") or {}
        kind = str(a.get("kind") or p.get("kind") or "assert")
        label = str(p.get("api_template") or p.get("label") or p.get("field") or kind)
        status = ("skipped" if a.get("skipped")
                  else "ok" if a.get("passed") else "fail")
        cur = add({"id": f"v{i}", "type": "assert", "label": f"{kind} {label}",
                   "status": status,
                   "io": {"expect": p.get("expect_status") or p.get("expect_value")
                          or p.get("after")}})
        edges.append({"from": prev, "to": cur})

    return {"nodes": nodes, "edges": edges,
            "run_status": run.status, "run_id": run.id}


def build_state_machine(db, skill_id: int) -> dict:
    """S43-2 状态机归纳：Skill 多轮录制的状态信号序列 → 状态转移图。

    证据范围与断言同源：骨架各步 session_window_seqs 指向的
    semantic_action.state_signals（field/value），按窗口序聚转移边并计数。
    初始态=无入边状态；终态=无出边状态。节点 id=状态值（如 active）。
    """
    from sqlalchemy import select

    from app.models import Alignment, SemanticAction, Skill
    skill = db.get(Skill, skill_id)
    if skill is None:
        return {"nodes": [], "edges": [], "initial": [], "final": []}
    alignment = db.get(Alignment, skill.alignment_id)

    # 收集每轮会话的有序状态序列（field 相同的状态流；多 field 并行流）
    streams: dict[str, dict[str, list[str]]] = {}  # sid -> field -> [values]
    for step in alignment.skeleton or []:
        for sid, window_seq in (step.get("session_window_seqs") or {}).items():
            action = db.execute(
                select(SemanticAction).where(
                    SemanticAction.session_id == sid,
                    SemanticAction.window_seq == window_seq,
                )
            ).scalar_one_or_none()
            if action is None:
                continue
            by_field = streams.setdefault(sid, {})
            for sig in action.state_signals or []:
                field = str(sig.get("field") or "")
                value = str(sig.get("value"))
                if not field:
                    continue
                by_field.setdefault(field, []).append(value)

    # 聚合：节点=去重 field=value（id 用 value，label 用 field=value）；
    # 边=同 field 流内的顺序转移，跨轮去重计数
    node_label: dict[str, str] = {}
    edge_count: dict[tuple[str, str], int] = {}
    for sid, by_field in streams.items():
        for field, values in by_field.items():
            seq = []
            for v in values:
                if v not in node_label:
                    node_label[v] = f"{field}={v}"
                if v not in seq:
                    seq.append(v)
            for a, b in zip(seq, seq[1:]):
                edge_count[(a, b)] = edge_count.get((a, b), 0) + 1

    has_in = {b for (_, b) in edge_count}
    has_out = {a for (a, _) in edge_count}
    nodes = [{"id": v, "type": "state", "label": node_label[v], "status": "ok"}
             for v in node_label]
    edges = [{"from": a, "to": b, "count": n} for (a, b), n in edge_count.items()]
    return {"nodes": nodes, "edges": edges,
            "initial": sorted(v for v in node_label if v not in has_in),
            "final": sorted(v for v in node_label if v not in has_out)}


def build_learning_graph(db, limit_sessions: int = 30) -> dict:
    """S43-2 学习图（审计 trace 图化）：归纳管道五层。

    session → window（各会话窗数）→ semantic（锚点动作）→ align（对齐组）
    → skill（归纳产物）。节点带计数摘要；边按所属链路连接。
    """
    from sqlalchemy import func, select

    from app.models import (Alignment, RecordingSession, SemanticAction, Skill,
                            TransactionWindow)
    nodes: list[dict] = []
    edges: list[dict] = []

    sessions = db.execute(
        select(RecordingSession).order_by(RecordingSession.started_at.desc())
        .limit(limit_sessions)).scalars().all()
    sid_set = {s.id for s in sessions}
    if not sid_set:
        return {"nodes": [], "edges": []}

    win_counts = dict(db.execute(
        select(TransactionWindow.session_id, func.count())
        .where(TransactionWindow.session_id.in_(sid_set))
        .group_by(TransactionWindow.session_id)).all())
    sems = db.execute(
        select(SemanticAction).where(SemanticAction.session_id.in_(sid_set))
        .order_by(SemanticAction.session_id, SemanticAction.window_seq)).scalars().all()
    sem_by_sid: dict[str, list[SemanticAction]] = {}
    for a in sems:
        sem_by_sid.setdefault(a.session_id, []).append(a)

    aligns = db.query(Alignment).all()
    align_sids = {sid: al for al in aligns for sid in (al.session_ids or [])}
    skills = db.query(Skill).filter(Skill.status != "superseded").all()
    skill_by_align: dict[int, list[Skill]] = {}
    for s in skills:
        skill_by_align.setdefault(s.alignment_id, []).append(s)

    def nid(kind: str, key: str) -> str:
        return f"{kind}:{key}"

    for s in sessions:
        sn = nid("s", s.id[:8])
        nodes.append({"id": sn, "type": "session",
                      "label": f"会话 {s.id[:8]}", "status": "ok",
                      "io": {"note": (s.note or "")[:60], "events": None}})
        wn = nid("w", s.id[:8])
        nodes.append({"id": wn, "type": "window",
                      "label": f"窗口 ×{win_counts.get(s.id, 0)}", "status": "ok"})
        edges.append({"from": sn, "to": wn})
        for a in sem_by_sid.get(s.id, []):
            an = nid(f"sem:{s.id[:8]}", str(a.window_seq))
            label = ((a.target or {}).get("label")
                     or (a.anchor_type or "action"))
            nodes.append({"id": an, "type": "semantic",
                          "label": str(label)[:40], "status": "ok"})
            edges.append({"from": wn, "to": an})
        al = align_sids.get(s.id)
        if al is not None:
            aln = nid("al", str(al.id))
            if not any(n["id"] == aln for n in nodes):
                nodes.append({"id": aln, "type": "align",
                              "label": f"对齐 #{al.id}", "status": "ok",
                              "io": {"sessions": len(al.session_ids or [])}})
            edges.append({"from": nid("w", s.id[:8]), "to": aln})
            for sk in skill_by_align.get(al.id, []):
                skn = nid("sk", str(sk.id))
                if not any(n["id"] == skn for n in nodes):
                    nodes.append({"id": skn, "type": "skill",
                                  "label": f"#{sk.id} {sk.name}", "status": "ok"})
                edges.append({"from": aln, "to": skn})

    return {"nodes": nodes, "edges": edges}


def build_canvas_flow(dag: dict) -> dict:
    """S43-2 画布/流水线图：replay_batch 节点展开 skill_source 的子技能。

    子图节点（sub_of=batch）为 skill 引用节点，边连回 batch——图内下钻
    取代"跳套件页"。skill_source 的 config.skill_ids 是子技能清单。
    """
    nodes: list[dict] = []
    edges: list[dict] = [dict(e) for e in (dag.get("edges") or [])]
    skill_ids: list[int] = []
    for nd in dag.get("nodes") or []:
        node = dict(nd)
        nodes.append(node)
        if node.get("type") == "skill_source":
            # 套件生成画布用 params.skill_ids（_suite_dag）；编辑器保存用 config
            cfg = node.get("params") or node.get("config") or {}
            try:
                skill_ids.extend(int(x) for x in cfg.get("skill_ids") or [])
            except (TypeError, ValueError):
                continue
    for bid, nd in enumerate([n for n in nodes if n.get("type") == "replay_batch"]):
        batch_id = nd.get("id") or f"batch{bid}"
        nd.setdefault("id", batch_id)
        for i, sid in enumerate(skill_ids, start=1):
            sub_id = f"{batch_id}_skill{i}"
            nodes.append({"id": sub_id, "type": "skill", "sub_of": batch_id,
                          "label": f"技能 #{sid}", "status": "ok",
                          "io": {"skill_id": sid}})
            edges.append({"from": sub_id, "to": batch_id})
    return {"nodes": nodes, "edges": edges}


def build_skill_flow(skill) -> dict:
    """S39 操作流程图：Skill 骨架 → 节点+边（流程图基座）。

    节点：page（参考会话起始页）→ action×N（骨架步骤，签名拆解为
    kind+label）→ assert×N（断言清单）。分支（buckets 多路径）后续扩展。
    """
    nodes: list[dict] = []
    edges: list[dict] = []

    def add(node: dict) -> str:
        nodes.append(node)
        return node["id"]

    prev = add({"id": "n0", "type": "page", "label": "起始页",
                "status": "pending",
                "io": {"skeleton_steps": len(skill.skeleton or [])}})

    for i, step in enumerate(skill.skeleton or [], start=1):
        sig = str(step.get("signature", ""))
        # 签名格式：click:label|APIs / input:name —— 拆出操作语义
        action_part = sig.split("|")[0]
        kind, _, label = action_part.partition(":")
        apis = sig.split("|", 1)[1] if "|" in sig else ""
        node = {"id": f"a{i}", "type": "action",
                "label": f"{kind or 'step'} {label or '?'}",
                "status": "pending",
                "io": {"signature": sig[:120]}}
        if apis:
            node["io"]["apis"] = apis[:200]
        cur = add(node)
        edges.append({"from": prev, "to": cur})
        prev = cur

    # 断言节点（从关联断言清单；此处从 skill 的断言数概要呈现）
    from app.db import SessionLocal
    from app.models import OutcomeAssertion
    db = SessionLocal()
    try:
        asserts = db.query(OutcomeAssertion).filter(
            OutcomeAssertion.skill_id == skill.id).all()
    finally:
        db.close()
    for i, a in enumerate(asserts, start=1):
        p = a.payload or {}
        kind = a.kind
        label = str(p.get("api_template") or p.get("label") or p.get("field") or kind)
        cur = add({"id": f"v{i}", "type": "assert", "label": f"{kind} {label}",
                   "status": "pending",
                   "io": {"expect": p.get("expect_status") or p.get("expect_value")
                          or p.get("after")}})
        edges.append({"from": prev, "to": cur})

    return {"nodes": nodes, "edges": edges, "skill_id": skill.id}
