"""S25 块 W1：skill → 自包含 Playwright 脚本导出（确定性可审计）。

导出脚本特点：
- 自包含：内联语义定位函数（与 locate.py 同策略链）与模板匹配（static 段规则）；
- 断言：api_status/state_signal 在脚本内判定；ui_text/field_change/visual 以注释
  标注"工作台侧判定"（导出不伪造能力边界）；
- 变量：OVERRIDES 字典顶部可改（换参回放）；
- 退出码：全过 0（PASS），否则 1（FAIL + 明细）。
"""
from sqlalchemy.orm import Session

from app.models import Alignment, OutcomeAssertion, RawEvent, Skill
from app.replay.plan import compile_skeleton_plan

_SCRIPT_TEMPLATE = '''"""SkillLens 导出脚本：{skill_name}（skill #{skill_id}）

由 SkillLens 工作台生成（{generated_at}）——步骤与断言均来自录制证据，
确定性可审计。依赖：playwright（pip install playwright && playwright install chromium）。
用法：python {fname}   # 修改 OVERRIDES 可换参回放
"""
import asyncio
import json
import re
import sys
from datetime import datetime, timezone

from playwright.async_api import async_playwright

URL = {url!r}
OVERRIDES = {overrides!r}    # 换参回放：改这里的值
STEPS = {steps!r}
API_ASSERTIONS = {assertions!r}
# 注：ui_text/field_change/视觉基线断言在工作台侧判定（需快照采集与基线库），导出脚本不含。

MAX_BODY = 8192


_ID_SEGMENT = re.compile(r"^(?:\\d+|[0-9a-fA-F-]{{36}})$")


def static_segments(path: str) -> list[str]:
    """与 SkillLens assert_eval 同规则：剔除 {{id}} 模板段/纯数字段/UUID 段。"""
    return [s for s in path.split("/")
            if s and s != "{{id}}" and not _ID_SEGMENT.match(s)]


def path_matches(url: str, template: str) -> bool:
    from urllib.parse import urlsplit
    return static_segments(urlsplit(url).path) == static_segments(template)


async def locate(page, label: str):
    """语义定位——与 SkillLens locate.py 同策略链（role→text→placeholder→label→id）。"""
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
                all(h["status"] != a["expect_status"] for h in hits):
            failures.append(f"{{a['template']}}: 期望 {{a['expect_status']}}，"
                            f"实际 {{[h['status'] for h in hits]}}")
        if a.get("field") is not None:
            ok = False
            for h in hits:
                try:
                    if json.loads(h["body"]).get(a["field"]) == a["expect_value"]:
                        ok = True
                        break
                except Exception:
                    continue
            if not ok:
                failures.append(f"{{a['template']}}: 字段 {{a['field']}} 期望 "
                                f"{{a['expect_value']}} 未观测到")
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
              **({"value": s["value"]} if s.get("value") is not None else {})}
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
                **({"field": p["field"], "expect_value": p["expect_value"]}
                   if p.get("field") is not None else {}),
            })
    overrides = {v["name"]: next(iter(v["values"].values()), "")
                 for v in skill.input_variables or []}
    from datetime import datetime, timezone
    return _SCRIPT_TEMPLATE.format(
        skill_name=skill.name, skill_id=skill.id,
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        fname=f"skill_{skill.id}_replay.py",
        url=plan["url"], overrides=overrides, steps=steps, assertions=assertions)
