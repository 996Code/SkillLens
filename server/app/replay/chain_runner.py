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
    steps = chain.steps or []
    if not steps:
        return {"status": "error", "error": "empty chain", "steps": []}

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
        if results[-1]["status"] != "pass":
            break  # fail 即停（与插件端链模式同语义）
    npass = sum(1 for r in results if r["status"] == "pass")
    overall = "pass" if npass == len(steps) else (
        "shadow" if results and results[-1]["status"] == "shadow" else "fail")
    return {"status": overall, "steps": results,
            "pass_count": npass, "total": len(steps)}
