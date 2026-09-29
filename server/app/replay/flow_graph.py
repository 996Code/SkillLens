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
