"""S25 块 W1：skill → 自包含 Playwright 脚本导出（确定性可审计）。

导出脚本特点：
- 自包含：内联简化语义定位（locate.py 全策略链的 5 策略子集，见脚本内
  注释）；判定逻辑（动态 id 段规则/api_status/state_signal）从
  app/replay/export_shared.py **源码逐字内嵌**——服务端与导出脚本单一
  事实源，不手抄副本（评审#1：手抄副本曾四处漂移）；
- 断言：api_status/state_signal 在脚本内判定；ui_text/field_change/visual 以注释
  标注"工作台侧判定"（导出不伪造能力边界）；
- 变量：OVERRIDES 字典顶部可改（换参回放）；
- 退出码：全过 0（PASS），否则 1（FAIL + 明细）。
"""
import inspect

from sqlalchemy.orm import Session

from app.models import Alignment, OutcomeAssertion, RawEvent, Skill
from app.replay import export_shared
from app.replay.plan import compile_skeleton_plan

_SHARED_SOURCE = inspect.getsource(export_shared)


def _safe_doc_text(s) -> str:
    """评审#2：嵌入生成脚本 docstring 的文本消毒——skill.name/flow.goal 是
    LLM 产物或用户输入，原样内插时 ''' / \"\"\" / 换行可截断 docstring 把
    任意语句注入用户将要执行的脚本（模板注入）。换行折叠为单空格，
    反斜杠与双引号转义后任何三引号序列都无法成形。"""
    return " ".join(str(s or "").split()).replace("\\", "\\\\").replace('"', '\\"')


_SCRIPT_TEMPLATE = '''"""SkillLens 导出脚本：{skill_name}（skill #{skill_id}）

由 SkillLens 工作台生成（{generated_at}）——步骤与断言均来自录制证据，
确定性可审计。依赖：playwright（pip install playwright && playwright install chromium）。
用法：python {fname}   # 修改 OVERRIDES 可换参回放
"""
import asyncio
import sys

from playwright.async_api import async_playwright

# ===== SkillLens 共享判定逻辑（app/replay/export_shared.py 源码逐字内嵌，
# ===== 与工作台判定同源；请勿本地修改，改动须回上游模块） =====
{shared}
# ===== 共享判定逻辑结束 =====

URL = {url!r}
OVERRIDES = {overrides!r}    # 换参回放：改这里的值
STEPS = {steps!r}
API_ASSERTIONS = {assertions!r}
# 注：ui_text/field_change/视觉基线断言在工作台侧判定（需快照采集与基线库），导出脚本不含。

MAX_BODY = 8192


async def locate(page, label: str):
    """语义定位——简化策略链（SkillLens locate.py 全策略链的 5 策略子集：
    role→text→placeholder→label→id）。完整链还含 title/表单组控件/select2/
    menuitem/iframe 遍历/评分兜底等，仅工作台侧回放具备；导出脚本定位
    失败不代表工作台回放失败。"""
    candidates = [
        (page.get_by_role("button", name=label), "role-button"),
        (page.get_by_text(label, exact=True), "text"),
        (page.get_by_placeholder(label), "placeholder"),
        (page.get_by_label(label), "label"),
        (page.locator(f"#{{label}}"), "id"),
    ]
    for locator, strategy in candidates:
        try:
            count = await locator.count()
        except Exception:
            continue
        if count > 0:
            try:
                if await locator.first.is_visible():
                    return locator.first, strategy
            except Exception:
                continue
    raise LookupError(f"semantic locate failed: {{label!r}}")


async def main() -> int:
    observed = []

    def on_response(response):
        async def collect():
            try:
                body = await response.text()
            except Exception:
                body = ""
            observed.append({{"url": response.url, "status": response.status,
                             "method": response.request.method,
                             "body": body[:MAX_BODY]}})
        asyncio.get_running_loop().create_task(collect())

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        page.on("response", on_response)
        await page.goto(URL)
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        for step in STEPS:
            if step["kind"] == "goto":
                await page.goto(step["url"])
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1000)
                continue
            label = step.get("label") or step.get("name")
            value = OVERRIDES.get(label, step.get("value", ""))
            locator, _ = await locate(page, label)
            if step["kind"] == "click":
                await locator.click(timeout=5000)
            elif step["kind"] == "input":
                await locator.fill(value, timeout=5000)

        await page.wait_for_timeout(2000)
        await browser.close()

    failures = []
    for a in API_ASSERTIONS:
        hits = [o for o in observed if path_matches(o["url"], a["template"])]
        if not hits:
            failures.append(f"{{a['template']}}: 未命中任何请求")
            continue
        if a.get("expect_status") is not None and \\
                not judge_api_status(hits, a["expect_status"]):
            failures.append(f"{{a['template']}}: 期望 {{a['expect_status']}}，"
                            f"实际 {{[h['status'] for h in hits]}}")
        if a.get("field") is not None and \\
                not judge_state_signal(hits, a["field"], a.get("expect_value")):
            failures.append(f"{{a['template']}}: 字段 {{a['field']}} 期望 "
                            f"{{a.get('expect_value')}} 未观测到")
    if failures:
        print("FAIL")
        for f in failures:
            print(" -", f)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
'''


def export_playwright(db: Session, skill_id: int) -> str:
    skill = db.get(Skill, skill_id)
    alignment = db.get(Alignment, skill.alignment_id)
    ref_sid = alignment.session_ids[0]
    rows = db.execute(
        __import__("sqlalchemy").select(RawEvent).where(RawEvent.session_id == ref_sid)
        .order_by(RawEvent.ts, RawEvent.seq)).scalars().all()
    events = [{"seq": r.seq, "ts": r.ts, "kind": r.kind,
               "payload": r.payload or {}} for r in rows]
    plan = compile_skeleton_plan(events, skill.skeleton, ref_sid, {},
                                 skill.input_variables)
    steps = [{"kind": s["kind"],
              **({"label": s["label"]} if s.get("label") else {}),
              **({"name": s["name"]} if s.get("name") else {}),
              **({"value": s["value"]} if s.get("value") is not None else {}),
              **({"url": s["url"]} if s.get("url") else {})}
             for s in plan.get("steps", [])]
    assertions = []
    for a in db.query(OutcomeAssertion).filter(
            OutcomeAssertion.skill_id == skill_id).all():
        p = a.payload or {}
        if a.kind in ("api_status", "state_signal") and p.get("api_template"):
            assertions.append({
                "template": p["api_template"],
                **({"expect_status": p["expect_status"]}
                   if p.get("expect_status") is not None else {}),
                **({"field": p["field"], "expect_value": p.get("expect_value")}
                   if p.get("field") is not None else {}),
            })
    overrides = {v["name"]: next(iter(v["values"].values()), "")
                 for v in skill.input_variables or []}
    from datetime import datetime, timezone
    return _SCRIPT_TEMPLATE.format(
        skill_name=_safe_doc_text(skill.name), skill_id=skill.id,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        fname=f"skill_{skill.id}_replay.py",
        shared=_SHARED_SOURCE,
        url=plan["url"], overrides=overrides, steps=steps, assertions=assertions)


_FLOW_SCRIPT_TEMPLATE = '''"""SkillLens 导出脚本：流程 {flow_id}（{goal}）

由 SkillLens 工作台生成（{generated_at}）——步骤来自证据回查的流程合成。
依赖：playwright。用法：python flow_{flow_id}.py
"""
import asyncio
import sys

from playwright.async_api import async_playwright

STEPS = {steps!r}


async def locate(page, label: str):
    """语义定位——简化策略链（SkillLens locate.py 全策略链的 5 策略子集，
    完整链仅工作台侧回放具备）。"""
    candidates = [
        (page.get_by_role("button", name=label), "role-button"),
        (page.get_by_text(label, exact=True), "text"),
        (page.get_by_placeholder(label), "placeholder"),
        (page.get_by_label(label), "label"),
        (page.locator(f"#{{label}}"), "id"),
    ]
    for locator, strategy in candidates:
        try:
            count = await locator.count()
        except Exception:
            continue
        if count > 0:
            try:
                if await locator.first.is_visible():
                    return locator.first
            except Exception:
                continue
    raise LookupError(f"semantic locate failed: {{label!r}}")


async def main() -> int:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        for step in STEPS:
            if step["kind"] == "goto":
                await page.goto(step["target"])
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            elif step["kind"] == "input":
                locator = await locate(page, step["target"])
                await locator.fill(step.get("value", ""), timeout=5000)
            elif step["kind"] == "click":
                locator = await locate(page, step["target"])
                await locator.click(timeout=5000)
            await page.wait_for_timeout(800)
        await browser.close()
    print("PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except Exception as exc:
        print("FAIL")
        print(" -", str(exc)[:200])
        sys.exit(1)
'''


def export_flow_playwright(db, flow_id: int) -> str:
    from datetime import datetime, timezone
    from app.models import SynthFlow
    flow = db.get(SynthFlow, flow_id)
    steps = [dict(s) for s in (flow.steps or []) if isinstance(s, dict)]
    return _FLOW_SCRIPT_TEMPLATE.format(
        flow_id=flow.id, goal=_safe_doc_text(flow.goal),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        steps=steps)
