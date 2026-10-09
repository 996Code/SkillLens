"""AG1 扩展执行器协议端点（docs/arch/extension-executor-protocol.md v0.1）。

插件=完整执行节点（用户在 popup 选择并点击执行），服务器=计划编译+判定。
- GET  /executor/skills：技能列表含 requires_confirmation（C1 确认卡元数据）；
- POST /executor/skills/{id}/plan：编译计划返回 run_id+首条指令；
- POST /executor/runs/{run_id}/step：证据上报→下一条指令（seq 幂等）；
- POST /executor/runs/{run_id}/finish：终态落库。

指令序列的确定性投影（compile_executor_plan）：
  goto(plan.url) → snapshot(before) → 每计划步[fill|click（带 resolve 前置）]
  → snapshot(after) → detach。
协议内部态（游标/已收证据/介入计数）存 run.plan["executor_state"]——run 即会话。
"""
import time

import copy

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.db import SessionLocal
from app.models import Alignment, OutcomeAssertion, RawEvent, ReplayRun, Skill
from app.replay.plan import compile_skeleton_plan, requires_confirmation
from app.replay.repair import load_repair_map
from app.replay.resolver import compile_resolve_candidates
from app.sanitize import sanitize_error
from app.api.auth import WRITE_GUARD
from sqlalchemy import select

router = APIRouter()

DEFAULT_TIMEOUT_MS = 5000


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _reap_stale_runs(db: Session) -> int:
    """协议 §5 心跳兜底：extension run 卡 running 超 10 分钟（无新步
    上报——矩阵实证 885/888 卡死）→ lost。在 /executor/skills 访问时
    顺带收割（无独立进程）。
    评审 #9 修正：判据=executor_state.last_step_at（每步 step POST 刷新）
    而非 created_at——慢步骤/用户确认停留 >10min 的 run 不再误标 lost。"""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=10)
    rows = db.query(ReplayRun).filter(
        ReplayRun.executor == "extension",
        ReplayRun.status == "running",
        ReplayRun.created_at < cutoff).all()
    n = 0
    for r in rows:
        state = (r.plan or {}).get("executor_state") or {}
        last = state.get("last_step_at") or r.created_at
        if isinstance(last, str):
            try:
                last = datetime.fromisoformat(last)
            except ValueError:
                last = r.created_at
        if last.tzinfo is not None:
            last = last.replace(tzinfo=None)
        if last < cutoff.replace(tzinfo=None):
            r.status = "lost"
            n += 1
    if n:
        db.commit()
    return n


@router.get("/executor/skills")
async def list_executor_skills(db: Session = Depends(get_db)) -> list:
    from app.system import skill_systems
    _reap_stale_runs(db)
    rows = db.query(Skill).filter(Skill.status.notin_(["superseded", "archived"])).all()
    systems = skill_systems(db, [s.id for s in rows])
    items = []
    for s in rows:
        items.append({
            "id": s.id, "name": s.name, "status": s.status,
            "system": systems.get(s.id) or "通用",
            "requires_confirmation": requires_confirmation(s.skeleton or []),
        })
    return items


class ExecutorPlanRequest(BaseModel):
    overrides: dict[str, str] = {}
    confirm_side_effect: bool = False


def _load_plan_input(db: Session, skill: Skill):
    alignment = db.get(Alignment, skill.alignment_id)
    ref_sid = alignment.session_ids[0]
    rows = db.execute(select(RawEvent).where(RawEvent.session_id == ref_sid)
                      .order_by(RawEvent.ts, RawEvent.seq)).scalars().all()
    events = [{"seq": r.seq, "ts": r.ts, "kind": r.kind,
               "payload": r.payload or {}} for r in rows]
    return compile_skeleton_plan(events, skill.skeleton, ref_sid,
                                 {}, skill.input_variables)


def compile_executor_plan(plan: dict) -> list[dict]:
    """计划步 → 微指令序列（确定性纯函数：同 plan 同序列）。"""
    seq = 1
    out: list[dict] = []
    if plan.get("url"):
        out.append({"seq": seq, "op": "goto", "url": plan["url"],
                    "timeout_ms": 15000})
        seq += 1
    out.append({"seq": seq, "op": "snapshot",
                "phase": "before", "scopes": ["labels", "forms", "toasts"],
                "timeout_ms": DEFAULT_TIMEOUT_MS})
    seq += 1
    for step in plan.get("steps", []):
        if step.get("kind") == "goto":
            out.append({"seq": seq, "op": "goto", "url": step["url"],
                        "timeout_ms": 15000})
        elif step.get("kind") == "input":
            out.append({"seq": seq, "op": "fill",
                        "name": step.get("name"), "value": step.get("value"),
                        "labels": step.get("labels") or [],
                        "resolve_candidates": compile_resolve_candidates(
                            step.get("name") or "", step.get("labels")),
                        "timeout_ms": DEFAULT_TIMEOUT_MS})
        elif step.get("kind") == "click":
            # AG5 行锚：labels 里的宿主行文本（>6 字符含 ASCII alnum，
            # ≠label——runner row-trigger 同门）编译进候选尾
            row_texts = [l for l in (step.get("labels") or [])
                         if len(l) > 6 and l != (step.get("label") or "")
                         and any(c.isascii() and c.isalnum() for c in l)]
            row_anchor = row_texts[0] if row_texts else None
            out.append({"seq": seq, "op": "click",
                        "label": step.get("label"),
                        "labels": step.get("labels") or [],
                        "tag": step.get("tag"),
                        "resolve_candidates": compile_resolve_candidates(
                            step.get("label") or "", step.get("labels"),
                            tag=step.get("tag"), row_anchor=row_anchor),
                        "timeout_ms": DEFAULT_TIMEOUT_MS})
        seq += 1
    out.append({"seq": seq, "op": "snapshot",
                "phase": "after", "scopes": ["labels", "forms", "toasts"],
                "timeout_ms": DEFAULT_TIMEOUT_MS})
    seq += 1
    out.append({"seq": seq, "op": "detach", "timeout_ms": DEFAULT_TIMEOUT_MS})
    return out


# 垃圾 run 洪泛防线（131 run/13s 实证）：同 skill 上一个 extension run
# 5s 内创建且以相同错误快速失败（attach 冲突类）→ 拒绝再创建——重试
# 风暴的形态就是"秒败秒建"，此闸把洪泛压成 1 个；正常串行（前一个
# 跑完数秒后再跑）不受影响
# AK6 批次1（attach 风暴复盘缺口②③）：①收割进 plan 入口——僵尸
# running 不再依赖 /executor/skills 顺带清理；②不变量守卫：同 skill
# 存在未收敛 running run → 409（5s 窗口与 error 前驱盲区一起堵——
# 118 条僵尸 running 实证：running 前驱 error 为空，旧节流放行）
@router.post("/executor/skills/{skill_id}/plan", dependencies=WRITE_GUARD)
async def executor_plan(skill_id: int, body: ExecutorPlanRequest,
                        db: Session = Depends(get_db)) -> dict:
    _reap_stale_runs(db)
    from datetime import datetime, timedelta
    from app.models import ReplayRun
    live = db.query(ReplayRun).filter(
        ReplayRun.skill_id == skill_id,
        ReplayRun.executor == "extension",
        ReplayRun.status == "running").count()
    if live:
        raise HTTPException(
            409, "该技能已有执行进行中（未结束）——请先等它完成或停止，"
                 "不要重复发起（防重试风暴）")
    last = db.query(ReplayRun).filter(
        ReplayRun.skill_id == skill_id,
        ReplayRun.executor == "extension",
    ).order_by(ReplayRun.id.desc()).first()
    if last is not None and last.created_at > datetime.utcnow() - timedelta(seconds=5):
        err = ((last.plan or {}).get("executor_summary") or {}).get("error") or ""
        if err:
            raise HTTPException(
                409, f"节流：该技能 5s 内已有快速失败的执行（{str(err)[:40]}）"
                     "——客户端重试风暴防线，稍候再试")
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(404, "skill not found")
    if skill.status == "superseded":
        raise HTTPException(409, "该 Skill 版本已被取代")
    if requires_confirmation(skill.skeleton or []) and not body.confirm_side_effect:
        raise HTTPException(409, "含写操作，需 C1 确认（confirm_side_effect=true）")

    plan = _load_plan_input(db, skill)
    instructions = compile_executor_plan(plan)
    # goto 实例段归一（ERPNext 236 铁证：录制保存的单据 URL
    # /desk/sales-order/new-sales-order-xxxx 带随机后缀——回放到已提交
    # 旧单上 Frappe 弹回旧页，后续步全打到错误页面）
    import re as _re_nav
    for ins in instructions:
        if ins.get("op") == "goto" and ins.get("url"):
            ins["url"] = _re_nav.sub(
                r"/(new-[a-z-]+)-[a-z0-9]+$", r"/\1", ins["url"])
    # 换参注入（服务端 replay 的 compile_replay_plan 语义等效）：fill 步
    # 的 value 按 overrides 替换（回放写场景防唯一性冲突——JeecG 269 铁证：
    # 旧表名已存在致 duplicate/check 拒绝、addAll 永不发）。此前 overrides
    # 只存 state 不应用，插件端换参形同虚设。click 步 label 内联旧值时
    # 同步替换（258 铁证：换参后登录昵称变新值，录制 label=旧用户名的
    # 头像点击步 miss——label 与 fill 值同源）。
    # label 替换只允许**实例值类 key**：与某 fill 步 value 同串且 name≠value
    # ——字段名类 key（JeecG '*表名' 既是变量名又是输入框 label）替换会毁
    # 聚焦步（豁免条件 label==next.name 断裂——269 双轮 fail 实证）
    instance_keys = {old for old in body.overrides
                     if any(i.get("op") == "fill" and i.get("value") == old
                            and (i.get("name") or "") != old
                            for i in instructions)}
    for ins in instructions:
        if ins.get("op") == "fill" and ins.get("value") is not None:
            for old, new in body.overrides.items():
                if ins.get("value") == old or (ins.get("name") or "") == old:
                    ins["value"] = new
        elif ins.get("op") == "click" and ins.get("label"):
            for old in instance_keys:
                if old and old in (ins.get("label") or ""):
                    ins["label"] = (ins.get("label") or "").replace(
                        old, body.overrides[old])
        # row-anchor 换参（S43-5 服务端 override 注入行过滤同款语义）：
        # 行操作候选的 anchor 含旧实例值时替换（270 铁证：行锚=
        # 上游技能建的表名——换参后列表行是新值，旧锚行匹配空→
        # 更多菜单开不了→同步链全 miss）
        for cand in ins.get("resolve_candidates") or []:
            if cand.get("anchor"):
                for old, new in body.overrides.items():
                    if old and old in str(cand.get("anchor")):
                        cand["anchor"] = str(cand.get("anchor")).replace(
                            old, new)
    # P2：自愈数据链插件端等效——活跃提案（verified/promoted）的
    # proposed_label 编译进对应 click 步候选首位（服务端 runner 的
    # repair_map 语义）
    # repair_map 注入只取 promoted（人工确认/多次验证晋升）——verified
    # 可能是错配（269 实证：'保存'→'请输入表名' verified 但验证命中的是
    # 搜索框——注入后保存步永久改错）
    from app.models import LocateProposal
    promoted_map = {r.step_label: {"label": r.proposed_label, "id": r.id}
                    for r in db.query(LocateProposal).filter(
                        LocateProposal.skill_id == skill_id,
                        LocateProposal.status == "promoted").all()}
    if promoted_map:
        for ins in instructions:
            if ins.get("op") == "click" and ins.get("label") in promoted_map:
                rep = promoted_map[ins["label"]]
                from app.replay.resolver import compile_resolve_candidates
                healed = compile_resolve_candidates(rep["label"], ins.get("labels"))
                ins["resolve_candidates"] = healed
                ins["label"] = rep["label"]
                ins["healed"] = True
    state = {"cursor": 0, "received": [], "interventions": 0,
             "overrides": body.overrides}
    run = ReplayRun(skill_id=skill_id, mode="execute", status="running",
                    plan={"steps": plan.get("steps", []),
                          "url": plan.get("url", ""),
                          "executor_instructions": instructions,
                          "executor_state": state},
                    executor="extension")
    db.add(run)
    db.commit()
    db.refresh(run)
    # P1 交互画像随 plan 下发（执行器解释——系统交互差异声明式适配）；
    # 同时落 run.plan（复现/诊断可查）。
    # P2.5 定位方式：goto URL → url_matches 通配符自动配对（油猴 @match
    # 语义——新系统接入零改代码）；URL 未命中回退技能所属系统映射
    ip_dump = None
    try:
        from app.adapters.manifest import load_adapter_dir as _lad
        from app.adapters.urlmatch import match_adapter as _ma
        from app.system import SYSTEM_ADAPTER, skill_systems
        from pathlib import Path as _P
        _mans, _ = _lad(_P(__file__).resolve().parents[2] / "adapters")
        _goto_url = next((i.get("url") for i in instructions
                          if i.get("op") == "goto"), "")
        _m = _ma(_goto_url, _mans) if _goto_url else None
        if _m is None:
            _label = skill_systems(db, [skill.id]).get(skill.id, "")
            _sys = SYSTEM_ADAPTER.get(_label)
            _m = next((x for x in _mans if x.id == _sys), None) if _sys else None
        if _m and _m.interaction_profile:
            ip_dump = _m.interaction_profile.model_dump()
    except Exception:
        pass
    if ip_dump:
        run.plan = {**run.plan, "interaction_profile": ip_dump}
        db.commit()
        db.refresh(run)
    return {"run_id": run.id, "instruction": instructions[0],
            "total_instructions": len(instructions),
            "interaction_profile": ip_dump}


class ExecutorStepReport(BaseModel):
    seq: int
    result: str
    evidence: dict = {}


@router.post("/executor/runs/{run_id}/step", dependencies=WRITE_GUARD)
async def executor_step(run_id: int, body: ExecutorStepReport,
                        db: Session = Depends(get_db)) -> dict:
    run = db.get(ReplayRun, run_id)
    if not run or run.executor != "extension":
        raise HTTPException(404, "executor run not found")
    if run.status not in ("running",):
        raise HTTPException(409, f"run 已终态（{run.status}）")

    plan = run.plan or {}
    instructions = plan.get("executor_instructions") or []
    state = plan.get("executor_state") or {}
    cursor: int = state.get("cursor", 0)

    # 幂等：重复 seq（断连重放）丢弃，返回缓存指令不推进
    expected = instructions[cursor]["seq"] if cursor < len(instructions) else None
    if body.seq != expected:
        cached = instructions[cursor] if cursor < len(instructions) \
            else {"seq": None, "op": "detach"}
        return {"instruction": cached, "duplicate": True}

    # 证据归档（C3）。state 深拷贝后变异——直接变异 plan 内嵌 dict 会让
    # SQLAlchemy 的新旧值相等（别名同对象），UPDATE 不发（AG3 实证）
    state = copy.deepcopy(state)
    state.setdefault("received", []).append(
        {"seq": body.seq, "result": body.result,
         "evidence": {k: v for k, v in body.evidence.items()
                      if k != "screenshot"}})
    state["cursor"] = cursor + 1
    # 心跳时间戳（评审 #9）：stale 收割判据从 created_at 改为最后步时间
    from datetime import datetime, timezone
    state["last_step_at"] = datetime.now(timezone.utc).isoformat()
    nxt = instructions[cursor + 1] if cursor + 1 < len(instructions) \
        else instructions[-1] if instructions else None

    # 证据链对齐服务端（S33）：截图落盘 artifacts/<run>-<seq>.png +
    # plan 记 step_screenshots（工作台出图白名单同源）；快照进
    # before/after_snapshot（对齐服务端 run.plan 形态）
    ev = body.evidence or {}
    cur_ins2 = instructions[cursor] if cursor < len(instructions) else {}
    if ev.get("screenshot"):
        try:
            import base64
            import os
            from pathlib import Path as _P
            from app.config import REPLAY_ARTIFACT_DIR
            art = REPLAY_ARTIFACT_DIR
            d = _P(art) / f"ext-run-{run_id}"
            os.makedirs(d, exist_ok=True)
            fname = f"step-{body.seq}.png"
            (d / fname).write_bytes(base64.b64decode(ev["screenshot"]))
            meta = plan.get("step_screenshots") or {"dir": str(d), "files": []}
            if fname not in meta["files"]:
                meta["files"] = list(meta["files"]) + [fname]
            plan = {**plan, "step_screenshots": meta}
            run.artifact_path = str(d / fname)
        except Exception:
            pass  # 截图落盘失败不破坏步循环（C3 主体已留痕）
    if ev.get("page") and cur_ins2.get("op") == "snapshot":
        phase = cur_ins2.get("phase")
        if phase in ("before", "after"):
            plan = {**plan, f"{phase}_snapshot": ev["page"]}

    # 协议 §4 当轮 LLM 介入：miss 的是**当前步**（instructions[cursor]，
    # cursor 已推进故当前步=state.cursor-1）——heal/超限都作用当前步
    cur_idx = cursor  # = state["cursor"] - 1（推进前的当前步）
    cur_ins = instructions[cur_idx] if cur_idx < len(instructions) else None

    # 聚焦步豁免：click miss 且**下一步是同 label 的 fill**（录制时用户
    # 点输入框聚焦——fill 直通 JS 设值已不需要前置点击；JeecG 269 实证
    # 聚焦步反复 miss 耗尽介入额度，保存步没执行到就超限终止）
    next_ins = instructions[cur_idx + 1] if cur_idx + 1 < len(instructions) else None
    if (body.result == "miss" and cur_ins is not None
            and cur_ins.get("op") == "click" and next_ins is not None
            and next_ins.get("op") == "fill"
            and (cur_ins.get("label") or "") == (next_ins.get("name") or "")):
        # 豁免也要持久化推进（received/cursor+1）——只在响应里跳过不发
        # seq：不落库则下一条 fill 上报被幂等判 duplicate、领回聚焦步，
        # 形成豁免死循环（JeecG 941 铁证：fill ok→duplicate→seq4 再来）
        run.plan = {**plan, "executor_state": state}
        db.commit()
        return {"instruction": nxt, "duplicate": False,
                "focus_step_skipped": True}

    if (body.result == "miss" and cur_ins is not None
            and state.get("interventions", 0) < 2
            and cur_ins.get("label")):
        # 计数先行：介入是"尝试"——LLM 不可达/提案为空也占额度（超限
        # 判 fail 语义不依赖网关可用性）
        state["interventions"] = state.get("interventions", 0) + 1
        try:
            from app.models import LocateProposal
            from app.llm.gateway import acomplete
            import json as _json
            texts = [str(t) for t in (body.evidence.get("page_texts") or [])]
            forms = [str(f) for f in (body.evidence.get("form_labels") or [])]
            label = cur_ins["label"]
            prompt = (
                f"自动化回放中按钮定位失败。原标签：{label}\n"
                f"当前页面可见文本元素：{_json.dumps(texts + forms, ensure_ascii=False)}\n"
                "从上述元素中选出最可能对应同一操作的新标签，"
                "只输出标签文本本身，不要任何解释。")
            result = await acomplete(db, "locate_repair", prompt)
            proposed = (result.text or "").strip().strip('"').splitlines()[0].strip()[:100]
            # 网关故障防线：LLM 配额页/错误串会以 HTTP 200 的 content 形态
            # 返回（"您的Token额度已用完"实证）——把基础设施错误文本当
            # label 提案会让插件去找该"按钮"必然 miss 耗尽介入。错误串
            # 不采纳=介入失败（fail-open，额度已计数）
            _infra_error = ("Token额度" in proposed or "token 额度" in proposed
                            or "Rate limit" in proposed or "rate_limit" in proposed
                            or "quota" in proposed.lower())
            # 宪法 C1「判定全确定性」：提案必须逐字出现在本轮证据里。幻觉
            # label 照单采纳 = 白烧一次介入额度（总额度 2）+ 污染提案库
            # （verify/promote 链会把不存在的 label 晋升进骨架）。
            # 不采纳也留痕（status=rejected / strategy=not_on_page）供人工复核。
            if not proposed or proposed == label or _infra_error:
                pass  # 空提案/原样/基础设施错误串：不采纳（额度已计数）
            else:
                on_page = proposed in {t.strip() for t in texts + forms if t.strip()}
                db.add(LocateProposal(
                    skill_id=run.skill_id, step_label=label, proposed_label=proposed,
                    status="proposed" if on_page else "rejected",
                    strategy="" if on_page else "not_on_page"))
                db.commit()
                if on_page:
                    from app.replay.resolver import compile_resolve_candidates
                    healed = compile_resolve_candidates(proposed, cur_ins.get("labels"))
                    # heal 只影响当轮响应（healed 指令随响应下发重试）——
                    # **不写回 plan.executor_instructions**（跨轮污染实证：
                    # 上轮 heal 改写被持久化，后续轮直接执行错误指令）
                    state["cursor"] = cursor
                    nxt = {**cur_ins, "label": proposed,
                           "resolve_candidates": healed, "healed": True}
        except Exception:
            pass  # 介入失败不破坏步循环（fail-open；C3 已留痕 received）

    # 协议 §4 超限语义：介入已用满再 miss → 判 fail 留下轮（跨 run 自愈）
    if (body.result == "miss"
            and state.get("interventions", 0) >= 2
            and cur_ins is not None and cur_ins.get("label")):
        run.plan = {**plan, "executor_state": state}
        run.status = "fail"
        from app.change.failure_class import classify_run
        run.failure_class = classify_run({
            "status": "fail", "executed": state.get("received") or []})
        db.commit()
        db.refresh(run)
        return {"instruction": {"seq": None, "op": "detach"},
                "intervention_exhausted": True}

    # 目标站不可达（UX 评审致命 2）：goto error → run 判 fail（不再让
    # 后续步骤在错误页上假执行）
    if (body.result == "error" and cur_ins is not None
            and cur_ins.get("op") == "goto"):
        run.plan = {**plan, "executor_state": state}
        run.status = "fail"
        run.attribution = sanitize_error(str(body.evidence.get("error", "")))[:500]
        from app.change.failure_class import classify_run
        run.failure_class = classify_run({
            "status": "fail",
            "executed": [{"kind": "goto", "ok": False,
                          "error": str(body.evidence.get("error", ""))}]})
        db.commit()
        db.refresh(run)
        return {"instruction": {"seq": None, "op": "detach"},
                "navigation_failed": True}

    run.plan = {**plan, "executor_state": state}
    db.commit()
    return {"instruction": nxt, "duplicate": False}


class ExecutorFinishRequest(BaseModel):
    status: str
    summary: dict = {}


@router.post("/executor/runs/{run_id}/finish", dependencies=WRITE_GUARD)
async def executor_finish(run_id: int, body: ExecutorFinishRequest,
                          db: Session = Depends(get_db)) -> dict:
    run = db.get(ReplayRun, run_id)
    if not run or run.executor != "extension":
        raise HTTPException(404, "executor run not found")
    if body.status not in ("done", "fail", "aborted", "lost"):
        raise HTTPException(422, "status 须为 done|fail|aborted|lost")
    # AK6 批次1（复盘缺口④b）：终态不可再写——SW 重启重复消费旧请求
    # （lessons #53）时二次 finish 会把 fail 翻写成 pass，判定完整性被
    # 重放篡改。与 step 端点的终态拒收同语义。
    if run.status != "running":
        raise HTTPException(409, f"run 已终态（{run.status}）——重放的 finish 拒收")
    plan = run.plan or {}
    state = copy.deepcopy(plan.get("executor_state") or {})
    run.status = body.status
    run.executed = body.summary.get("executed")
    run.duration_ms = body.summary.get("duration_ms")

    # AG4：done 时服务端确定性断言——插件证据（observed/executed）喂
    # evaluate_assertions（原封不动），判定语义=执行+断言；status 重判
    assertion_results = None
    if body.status == "done":
        from app.models import OutcomeAssertion
        from app.replay.assert_eval import evaluate_assertions
        assertions = [{"kind": a.kind, "payload": a.payload} for a in
                      db.query(OutcomeAssertion).filter(
                          OutcomeAssertion.skill_id == run.skill_id).all()]
        observed = [{"url": o.get("url", ""), "status": o.get("status"),
                     "method": o.get("method", "GET"),
                     "body": str(o.get("body", ""))}
                    for o in body.summary.get("observed", [])]
        assertion_results = evaluate_assertions(
            assertions, observed,
            executed_steps=body.summary.get("executed") or [])
        run.assertion_results = assertion_results
        if all(a.get("passed") for a in assertion_results):
            run.status = "pass"
        else:
            run.status = "fail"

    run.plan = {**plan, "executor_state": state,
                "executor_summary": body.summary}
    if body.status in ("fail", "aborted", "lost"):
        run.attribution = sanitize_error(str(body.summary.get("error", "")))[:500]
    # AJ1 补线：extension 主通道分类（占 fail/error 的 54%——此前只有
    # server 路径写 failure_class，主通道零产出，抽查实锤）
    if run.status in ("fail", "error"):
        from app.change.failure_class import classify_run
        run.failure_class = classify_run({
            "status": run.status,
            "executed": run.executed or [],
            "assertions": run.assertion_results or []})
    db.commit()
    db.refresh(run)
    return {"id": run.id, "status": run.status, "executor": run.executor,
            "assertion_results": assertion_results}
