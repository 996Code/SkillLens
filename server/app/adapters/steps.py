"""AF3 步骤解释器：manifest 六原语 → Playwright 动作（login 与 flows 共用）。

原语语义：
- goto：相对路径自动拼 manifest.target.base_url；
- fill：[selector, value]——值经 interpolate（${username}/${password} 插值）；
- click：selector（Playwright 选择器语法原样，含 :has-text）；
- select：[selector, value]；
- wait：毫秒；
- routine：例程库按名调用（routines.py——怪癖收编地）。
"""
import asyncio

from playwright.async_api import Page

from app.adapters.manifest import Manifest, Step
from app.adapters.probes import interpolate


async def run_step(page: Page, manifest: Manifest, step: Step) -> None:
    if step.op == "goto":
        url = interpolate(step.arg, manifest)
        if not url.startswith("http"):
            url = manifest.target.base_url.rstrip("/") + url
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
    elif step.op == "fill":
        await page.locator(step.arg).first.fill(interpolate(step.arg2 or "", manifest))
        await page.wait_for_timeout(300)
    elif step.op == "click":
        await page.locator(step.arg).first.click(timeout=8000)
        await page.wait_for_timeout(800)
    elif step.op == "select":
        await page.locator(step.arg).first.select_option(interpolate(step.arg2 or "", manifest))
    elif step.op == "wait":
        await page.wait_for_timeout(int(step.arg))
    elif step.op == "routine":
        from app.adapters.routines import run_routine
        await run_routine(page, step.arg)
    else:
        raise ValueError(f"未知原语: {step.op}")


async def run_steps(page: Page, manifest: Manifest, steps: list[Step]) -> None:
    for s in steps or []:
        await run_step(page, manifest, s)


async def login(page: Page, manifest: Manifest) -> bool:
    """按清单登录（幂等）：已登录（访问 base_url 不落 login 路径）直接通过；
    未登录执行 login.steps → post_login 例程 → success 判定（确定性）。"""
    if manifest.login is None:
        return True
    try:
        await page.goto(manifest.target.base_url, wait_until="domcontentloaded",
                        timeout=20000)
        await page.wait_for_timeout(2500)
        probe = manifest.login.success.url_not_contains
        if probe and probe not in page.url:
            return True  # 已登录
    except Exception:
        pass
    await run_steps(page, manifest, manifest.login.steps)
    for name in manifest.login.post_login:
        from app.adapters.routines import run_routine
        await run_routine(page, name)
    await page.wait_for_timeout(1500)
    succ = manifest.login.success
    if succ.url_not_contains and succ.url_not_contains in page.url:
        return False
    if succ.text_contains:
        try:
            return await page.get_by_text(succ.text_contains).first.is_visible()
        except Exception:
            return False
    return True
