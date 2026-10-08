"""AI3 服务端链执行：规则解释 + 顺序执行（CI 出口的执行体）。

规则语义与 extension/src/shared/chain-rules.ts 逐字对齐（双端一致性由
两侧测试钉死；漂移=链在两端行为分叉）：
- ${unique:前缀}：时间戳 base36（同轮共享——run_chain_server 单次执行
  一个 ts）
- ${stepN.字段}：从第 N 步（1 起）run 的 plan["observed"] 提取 reqBody
  字段（JSON 串值/数值 + urlencoded；末条优先=终态语义）
"""
import re
import time

from sqlalchemy.orm import Session


def extract_field(req_body: str | None, key: str) -> str | None:
    if not req_body or not key:
        return None
    esc = re.escape(key)
    m = re.search(rf'"{esc}"\s*:\s*"([^"]*)"', req_body)
    if m:
        return m.group(1)
    m = re.search(rf'"{esc}"\s*:\s*([0-9]+|true|false)', req_body)
    if m:
        return m.group(1)
    m = re.search(rf"(?:^|[&;]){esc}=([^&;]*)", req_body)
    if m:
        return m.group(1)
    return None


def _extract_step_value(step_ctx: list, ref: str) -> str | None:
    m = re.match(r"^\$\{step(\d+)\.([^}]+)\}$", ref)
    if not m:
        return None
    n = int(m.group(1))
    key = m.group(2).strip()
    if n < 1 or n > len(step_ctx):
        return None
    writes = step_ctx[n - 1] if isinstance(step_ctx[n - 1], list) else [step_ctx[n - 1]]
    for w in reversed(writes):
        v = extract_field((w or {}).get("reqBody"), key)
        if v is not None:
            return v
    return None


def resolve_value(value: str, step_ctx: list | None = None,
                  now: int | None = None) -> str:
    """规则解释入口：unique/stepN/原文三态。未命中绑定保留原文（执行期
    日志可见——防静默错值，与插件端同语义）。"""
    m = re.match(r"^\$\{unique:([^}]*)\}$", value)
    if m:
        ts = now if now is not None else int(time.time() * 1000)
        # base36（与 TS toString(36) 对齐——双端同值可对账）
        digits = "0123456789abcdefghijklmnopqrstuvwxyz"
        if ts == 0:
            b36 = "0"
        else:
            b36 = ""
            n = ts
            while n:
                b36 = digits[n % 36] + b36
                n //= 36
        return f"{m.group(1)}{b36}"
    sm = re.match(r"^\$\{step(\d+)\.([^}]+)\}$", value)
    if sm and step_ctx:
        v = _extract_step_value(step_ctx, value)
        if v is not None:
            return v
        return value
    return value


def resolve_step_overrides(step: dict, step_ctx: list | None,
                           now: int) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (step.get("overrides") or {}).items():
        out[k] = resolve_value(v, step_ctx, now)
    return out


def expand_steps(steps: list, chains_by_id: dict, depth: int = 0,
                  inherit_setup: bool = False) -> list:
    """链编排 v2：chain_id 步骤展开为子链步骤（递归，深度≤3 防环）。
    setup 标记传染：父步骤标记 setup → 子链全部步骤继承（登录链整体
    是前置——Playwright beforeEach 的声明式等价）。"""
    if depth > 3:
        raise ValueError(f"子链嵌套超过深度 3（疑似环）")
    out: list = []
    for st in steps:
        if st.get("chain_id") is not None:
            sub = chains_by_id.get(st["chain_id"])
            if sub is None:
                continue  # 子链已被删——跳过（不致命）
            out.extend(expand_steps(
                sub, chains_by_id, depth + 1,
                inherit_setup=inherit_setup or bool(st.get("setup"))))
        else:
            s = dict(st)
            if inherit_setup:
                s["setup"] = True
            out.append(s)
    return out


async def run_chain_server(db: Session, chain_id: int,
                           confirm_side_effect: bool) -> dict:
    """服务端链执行（CI 出口执行体）：顺序 run_replay，fail 即停。

    C1 语义：链内含写技能且 confirm=False 时，第一步 run_replay 自身
    shadow 短路（不启浏览器）——整链结果 shadow，与单技能语义一致。
    observed 从每步 run.plan["observed"] 取（runner 旁挂）供跨步绑定。
    """
    from app.models import Chain
    from app.replay.runner import run_replay

    chain = db.get(Chain, chain_id)
    if not chain:
        return {"status": "error", "error": "chain not found", "steps": []}
    raw_steps = chain.steps or []
    if not raw_steps:
        return {"status": "error", "error": "empty chain", "steps": []}

    # v2：子链展开（chain_id → 子链步骤，setup 传染，深度守卫）
    all_chains = {c.id: (c.steps or []) for c in db.query(Chain).all()}
    try:
        steps = expand_steps(raw_steps, all_chains)
    except ValueError as e:
        return {"status": "error", "error": str(e), "steps": []}

    # v2：适配器自动登录（幂等——已登录直过；根治 CI 多系统登录态）
    warnings: list[str] = []
    from app.system import SYSTEM_ADAPTER
    aid = SYSTEM_ADAPTER.get(chain.system or "")
    if aid:
        try:
            ok = await _adapter_login(aid)
            if not ok:
                warnings.append(f"适配器登录未确认（{aid}）——继续执行")
        except Exception as e:
            warnings.append(f"适配器登录异常（{aid}）：{str(e)[:80]}")

    run_ts = int(time.time() * 1000)
    step_ctx: list = []
    results: list[dict] = []
    for i, st in enumerate(steps):
        ovr = resolve_step_overrides(st, step_ctx, run_ts)
        try:
            run = await run_replay(db, st["skill_id"], ovr, confirm_side_effect)
            step_ctx.append((run.plan or {}).get("observed") or [])
            results.append({"step": i + 1, "status": run.status, "run_id": run.id,
                            "skill_id": st["skill_id"]})
        except Exception as e:  # 执行异常：收敛为该步 error（C3 落库在 run_replay 内）
            step_ctx.append([])
            results.append({"step": i + 1, "status": "error", "error": str(e)[:200],
                            "skill_id": st["skill_id"]})
        # v2 setup 语义：前置步骤 fail 不判链失败（登录已有效时登录链
        # 自然 fail——storageState 复用的等价物）只记 warning
        if results[-1]["status"] != "pass":
            if st.get("setup"):
                warnings.append(
                    f"前置步骤 #{results[-1]['step']} 未通过（{results[-1]['status']}）——已跳过继续")
            else:
                # AJ1 blocked 语义（TestRail）：业务步骤 fail 即停，后续步骤
                # 标 blocked（没跑≠失败）——统计分母只含执行了的步骤；
                # 占位结果不落 ReplayRun（防污染执行列表），只进链结果
                for j in range(i + 1, len(steps)):
                    results.append({"step": j + 1, "status": "blocked",
                                    "skill_id": steps[j].get("skill_id")})
                break
    # AJ1：分母排除 setup 步骤与 blocked 占位（没跑≠失败——TestRail 语义）
    biz = [r for r, st in zip(results, steps)
           if not st.get("setup") and r["status"] != "blocked"]
    biz_pass = sum(1 for r in biz if r["status"] == "pass")
    overall = "pass" if biz and biz_pass == len(biz) else (
        "shadow" if results and results[-1]["status"] == "shadow" else "fail")
    # AI5 teardown：无论成败都清理（测试数据不残留——fail 时更需要清）
    cleaned = []
    for st in steps:
        cl = st.get("cleanup") or {}
        d = cl.get("docker")
        if not d:
            continue
        try:
            import subprocess
            r = subprocess.run(
                ["docker", "exec", d["container"], "sh", "-c", d["shell"]],
                capture_output=True, text=True, timeout=30)
            cleaned.append({"skill_id": st.get("skill_id"),
                            "ok": r.returncode == 0,
                            "err": (r.stderr or "")[:100]})
        except Exception as e:
            cleaned.append({"skill_id": st.get("skill_id"), "ok": False,
                            "err": str(e)[:100]})
    return {"status": overall, "steps": results,
            "pass_count": biz_pass, "total": len(biz) or len(results),
            "warnings": warnings, "teardown": cleaned}


async def _adapter_login(adapter_id: str) -> bool:
    """v2：目标系统适配器登录例程（幂等）——AF3 例程库的服务端入口。
    独立上下文跑登录并把状态存为该系统的独立 state 文件（多系统并存，
    按适配器 id 分文件；runner 按系统选择注入属 P2 接线）。"""
    from pathlib import Path
    from app.adapters.manifest import load_adapter_dir
    from app.adapters.steps import login as adapter_login
    from playwright.async_api import async_playwright
    ms, _ = load_adapter_dir(Path("adapters"))
    m = next((x for x in ms if x.id == adapter_id), None)
    if m is None or m.login is None:
        return True  # 无登录声明的系统视为通过
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        try:
            ctx = await browser.new_context()
            page = await ctx.new_page()
            ok = await adapter_login(page, m)
            if ok:
                state_dir = Path("artifacts") / "states"
                state_dir.mkdir(parents=True, exist_ok=True)
                await ctx.storage_state(path=str(state_dir / f"{adapter_id}.json"))
            return ok
        finally:
            await browser.close()


# ---- AI5 数据卫生 ----

_UNIQUE_VALUE_RE = re.compile(r"^(?:[a-z]+_)?(?:sl_|test_|t\d|SAL-|[0-9]{6,})",
                              re.IGNORECASE)


def recommend_unique_overrides(fills: list[dict]) -> dict[str, str]:
    """唯一字段推荐：原值疑似唯一键（sl_ 前缀/长数字/单号形态）的字段
    推荐 ${unique:前缀}——组链 UI 的防撞名建议（用户一键采纳）。"""
    out: dict[str, str] = {}
    for f in fills:
        name = str(f.get("name") or "")
        value = str(f.get("value") or "")
        if not name or not value:
            continue
        if _UNIQUE_VALUE_RE.search(value):
            # 前缀=去掉尾部的数字段（sl_form_a26513 → sl_form_a？不——
            # 语义前缀是 sl_form_：剥到"最后一个字母后紧跟数字"的边界）
            # sl_form_a26513 → sl_form_（剥尾部"字母段+数字段"——
            # a26513 是一轮实例后缀；12345678 → ""（纯数字无语义前缀））
            prefix = re.sub(r"[a-zA-Z]?[0-9]+$", "", value)
            out[name] = f"${{unique:{prefix}}}"
    return out
