"""S19 T2：生成流程执行器——复用回放通道（runner 的浏览器入口 + locate 语义）。

C1 门控（flow_requires_confirmation）：步骤中 click 锚点所在 skill 骨架签名
的 API 段含写方法（POST/PUT/PATCH/DELETE）→ 执行需 confirm_side_effect，
未确认 409 不启浏览器（与回放 shadow 门控同纪律）。
执行：goto → input/click 逐步（locate 定位），每步 wait 800ms；全部完成
status=executed，任一步异常 status=failed + execution_log 记错误步（后续步
not attempted，失败收敛）。全程落 execution_log（C3）。
自学习（v3 §27）：执行成功不自动 induce（v1——插件录制协同是 T4 真机环节），
notes 记提示。
"""
from sqlalchemy.orm import Session

from app.models import Skill, SynthFlow
from app.replay.locate import locate
from app.replay.runner import (
    _cdp_url,
    _close_ctx_quietly,
    _launch,
    _open_browser,
    _open_context,
)

WRITE_METHODS = ("POST:", "PUT:", "PATCH:", "DELETE:")


def flow_requires_confirmation(db: Session, steps: list) -> bool:
    """C1：任一 click 锚点关联的 API 模板含写方法 → 需确认。
    判定：锚点所在 skill（非 superseded）骨架签名的 API 段含写方法
    （锚点与签名 action 段 click:label 子串互配，与 verify_steps 同宽）。"""
    for step in steps or []:
        if not isinstance(step, dict) or step.get("kind") != "click":
            continue
        target = str(step.get("target") or "")
        if not target:
            continue
        for skill in db.query(Skill).filter(Skill.status != "superseded").all():
            for sk_step in skill.skeleton or []:
                signature = sk_step.get("signature", "")
                action, _, api_part = signature.partition("|")
                if not action.startswith("click:"):
                    continue
                label = action[len("click:"):]
                if target in label or label in target:
                    if any(m in api_part for m in WRITE_METHODS):
                        return True
    return False


async def execute_flow(db: Session, flow: SynthFlow,
                       timeout_ms: int = 5000) -> SynthFlow:
    """执行生成流程并落库结果（executed|failed + execution_log）。
    浏览器入口直接复用 runner 的 _launch/_open_browser/_open_context
    （CDP 常驻/无头/前台由同一环境变量族控制），步骤执行用 locate+fill/click
    简单循环（v1 生成流程步骤少，不复用水合确认重循环）。"""
    log: list[dict] = []
    failed = False
    try:
        # 执行必须整体在 _launch() 上下文内（连接生命周期，同 run_replay）
        async with _launch() as p:
            browser = await _open_browser(p)
            # CDP 常驻 context 由 _open_context 复用返回，收尾时不能关
            shared_ctx = bool(_cdp_url() and getattr(browser, "contexts", None))
            ctx = None
            try:
                ctx = await _open_context(browser)
                page = await ctx.new_page()
                for i, step in enumerate(flow.steps or []):
                    if not isinstance(step, dict):
                        step = {}
                    entry = {"step": i + 1, "kind": step.get("kind"),
                             "target": step.get("target"), "ok": False}
                    if failed:
                        entry["error"] = "not attempted"
                        log.append(entry)
                        continue
                    try:
                        if step.get("kind") == "goto":
                            await page.goto(step["target"])
                        elif step.get("kind") == "input":
                            locator, _ = await locate(page, step["target"])
                            await locator.fill(step.get("value") or "",
                                               timeout=timeout_ms)
                        elif step.get("kind") == "click":
                            locator, _ = await locate(page, step["target"])
                            await locator.click(timeout=timeout_ms)
                        else:
                            raise ValueError(
                                f"unknown kind {step.get('kind')!r}")
                        entry["ok"] = True
                    except Exception as exc:
                        entry["error"] = str(exc)[:200]
                        failed = True
                    log.append(entry)
                    try:
                        await page.wait_for_timeout(800)
                    except Exception:
                        pass
            finally:
                if ctx is not None and not shared_ctx:
                    await _close_ctx_quietly(ctx)
                try:
                    await browser.close()
                except Exception:
                    pass
    except Exception as exc:
        # 启动阶段异常也必须落库（C3：执行审计不可缺）
        log.append({"step": 0, "kind": None, "target": None, "ok": False,
                    "error": str(exc)[:200]})
        failed = True
    flow.execution_log = log
    if failed:
        flow.status = "failed"
    else:
        flow.status = "executed"
        # v3 §27 自学习提示：v1 不自动 induce（插件录制协同是 T4 真机环节）
        flow.notes = "执行成功，可经插件录制后 induce 学习"
    db.commit()
    db.refresh(flow)
    return flow
