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


async def _locate_any_frame(page, selector: str):
    """主 frame 优先，miss 后逐子 frame（禅道类 iframe 架构——s43 的
    biz_frame 语义泛化到所有原语）。"""
    frames = [page.main_frame, *[f for f in page.frames if f is not page.main_frame]]
    for fr in frames:
        loc = fr.locator(selector).first
        try:
            if await loc.count():
                return loc
        except Exception:
            continue
    return None


async def run_step(page: Page, manifest: Manifest, step: Step) -> None:
    if step.op == "goto":
        url = interpolate(step.arg, manifest)
        if not url.startswith("http"):
            url = manifest.target.base_url.rstrip("/") + url
        await page.goto(url, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
    elif step.op == "fill":
        loc = await _locate_any_frame(page, step.arg)
        if loc is None:
            raise LookupError(f"fill 定位失败: {step.arg}")
        await loc.fill(interpolate(step.arg2 or "", manifest),
                       timeout=8000)
        await page.wait_for_timeout(300)
    elif step.op == "click":
        loc = await _locate_any_frame(page, step.arg)
        if loc is None:
            raise LookupError(f"click 定位失败: {step.arg}")
        await loc.click(timeout=8000)
        # 2500ms 余量：锚点后的 network/snapshot 须落进窗口（800ms 时
        # 禅道 CaseRun 实测窗口 api_count=0 被 read_only 滤除）
        await page.wait_for_timeout(2500)
    elif step.op == "select":
        loc = await _locate_any_frame(page, step.arg)
        if loc is None:
            raise LookupError(f"select 定位失败: {step.arg}")
        await loc.select_option(interpolate(step.arg2 or "", manifest))
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


async def _logged_in(page: Page, manifest: Manifest) -> bool:
    """登录态判定（确定性，双通道）：URL 探针（url_not_contains 在 URL
    中=未登录）+ 特征文本（text_contains 可见=已登录）。

    经典表单系统（Dolibarr 实证）：登录页在根路径、URL 无 login 字样
    ——URL 探针失效，text_contains 是唯一证据。"""
    succ = manifest.login.success
    if succ.url_not_contains and succ.url_not_contains in page.url:
        return False
    if succ.text_contains:
        try:
            return await page.get_by_text(succ.text_contains).first.is_visible()
        except Exception:
            return False
    return True


async def login(page: Page, manifest: Manifest) -> bool:
    """按清单登录（幂等）：已登录（URL 探针+特征文本双通道判定）直接通过；
    未登录执行 login.steps → post_login 例程 → success 判定（确定性）。
    已登录但**身份不符**（nickname≠期望账号的昵称——矩阵轮间上个技能换参
    登录了新用户，权限不足 404——若依 258 实证）不算通过，先强制退出。"""
    if manifest.login is None:
        return True
    try:
        await page.goto(manifest.target.base_url, wait_until="domcontentloaded",
                        timeout=20000)
        await page.wait_for_timeout(2500)
        if await _logged_in(page, manifest):
            if manifest.login.admin_nickname:
                nick = await page.evaluate(
                    "(() => (document.querySelector("
                    "'.user-nickname')||{textContent:''})"
                    ".textContent.trim())()")
                if nick and nick != manifest.login.admin_nickname:
                    ok = await _force_logout(page)
                    if not ok:
                        return False
            else:
                # 通用身份校验：发现非期望账号痕迹（昵称为换参风格的
                # E数字/SL 开头）则强制退出——写链矩阵的登录必须回 admin
                nick = await page.evaluate(
                    "(() => (document.querySelector("
                    "'.user-nickname')||{textContent:''})"
                    ".textContent.trim())()")
                if nick and _looks_like_swapped_user(nick):
                    ok = await _force_logout(page)
                    if not ok:
                        return False
            return await _recheck_or_login(page, manifest)
    except Exception:
        pass
    await run_steps(page, manifest, manifest.login.steps)
    for name in manifest.login.post_login:
        from app.adapters.routines import run_routine
        await run_routine(page, name)
    await page.wait_for_timeout(1500)
    return await _logged_in(page, manifest)


def _looks_like_swapped_user(nick: str) -> bool:
    """昵称呈换参产物特征（E+数字/SL/M+大写标记开头）——非演示管理员。
    形态实证：v21_matrix `E{rnd}{ts}` 与 `M{A|B|C}{ts}x{n}`、zentao 清单
    `SL回放${ts}`——旧正则 ^[ES][L0-9] 漏 M+大写标记形态（注释对、正则错，
    评审三轮 #4 收口）。"""
    import re
    return bool(re.match(r"^(?:[ES][L0-9]|M[A-Z])", nick))


async def _force_logout(page: Page) -> bool:
    """强制退出当前账号：清 cookie+storage 直达登录页（UI 退出链的
    el-dropdown hover 时序不稳——清态等效且确定性；Redis 会话随 token
    cookie 消失自然失效）。"""
    try:
        await page.evaluate(
            "(() => { localStorage.clear(); sessionStorage.clear();"
            " document.cookie.split(';').forEach(c => {"
            " const n = c.split('=')[0].trim();"
            " document.cookie = n + '=;expires=Thu, 01 Jan 1970"
            " 00:00:00 GMT;path=/'; }); })()")
        await page.goto(page.url.split("?")[0], wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        return True
    except Exception:
        return False


async def _recheck_or_login(page: Page, manifest: Manifest) -> bool:
    """退出/清态后复核：未登录则走正常登录步。"""
    try:
        await page.goto(manifest.target.base_url, wait_until="domcontentloaded",
                        timeout=20000)
        await page.wait_for_timeout(2000)
        if await _logged_in(page, manifest):
            return True
    except Exception:
        pass
    await run_steps(page, manifest, manifest.login.steps)
    for name in manifest.login.post_login:
        from app.adapters.routines import run_routine
        await run_routine(page, name)
    await page.wait_for_timeout(1500)
    return await _logged_in(page, manifest)
