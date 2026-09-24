from sqlalchemy.orm import Session

from app.models import ExpectedDelta, ObservedDelta, ReplayRun, Skill
from app.replay.runner import run_replay


def extract_observed(run: ReplayRun) -> list[dict]:
    """纯确定性提取：executed 的 ok 步 + assertion_results 的 api 模板。
    shadow run 的 executed/assertion_results 为 None，天然提取为空列表。"""
    items: list[dict] = []
    for step in (run.executed or []):
        if not step.get("ok"):
            continue
        if step.get("kind") == "click":
            items.append({"type": "ui_action", "value": f"点击 {step.get('label', '')}"})
        elif step.get("kind") == "input":
            items.append({"type": "ui_action",
                          "value": f"输入 {step.get('name', '')}={step.get('value', '')}"})
    seen_api: set[str] = set()
    for a in (run.assertion_results or []):
        tpl = (a.get("payload") or {}).get("api_template", "")
        if not tpl or tpl in seen_api:
            continue
        seen_api.add(tpl)
        items.append({"type": "api_add", "value": tpl})
        # api_status 条目只对配了 expect_status 的断言生成（state_signal 类无此键）
        if (a.get("observed_status") is not None
                and (a.get("payload") or {}).get("expect_status") is not None):
            items.append({"type": "api_status",
                          "value": f"{tpl} -> {a['observed_status']}"})
    return items


async def run_observe(db: Session, expected_delta_id: int, skill_id: int,
                      overrides: dict[str, str], confirm_side_effect: bool) -> ObservedDelta:
    delta = db.get(ExpectedDelta, expected_delta_id)
    if not delta or delta.status != "confirmed":
        raise ValueError("expected delta 未确认，不能观测")
    if not db.get(Skill, skill_id):
        raise LookupError("skill not found")
    run = await run_replay(db, skill_id, overrides or {}, confirm_side_effect)
    if run.mode == "shadow":
        raise PermissionError("shadow run 未执行，无观测")
    items = extract_observed(run)
    # MVP：duration_ms 存 0（run 内首尾时间差不可得），真实时序 Drift 留给 Task 4 断言耗时
    row = ObservedDelta(expected_delta_id=expected_delta_id, skill_id=skill_id,
                        replay_run_id=run.id, items=items, duration_ms=0)
    db.add(row); db.commit(); db.refresh(row)
    return row
