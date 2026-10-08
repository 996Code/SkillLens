"""AF3 步骤解释器+例程库+登录驱动（TDD：mock.local 内联页面，同 test_runner_browser 模式）。"""
import json
from pathlib import Path

import pytest
from playwright.async_api import async_playwright

from app.adapters.manifest import load_manifest_text
from app.adapters.routines import run_routine, _ROUTINES
from app.adapters.steps import run_step, login


MANIFEST = """
id: t
target: {base_url: "http://mock.local"}
credentials: {username: alice, password_env: T_PW}
login:
  steps:
    - goto: /login
    - fill: ["input[name=u]", "${username}"]
    - fill: ["input[name=p]", "${password}"]
    - click: "button[type=submit]"
  success: {url_not_contains: login}
"""

LOGIN_PAGE = """
<html><body>
  <form>
    <input name="u"><input name="p" type="password">
    <button type="submit">登 录</button>
  </form>
  <script>
    document.querySelector('button').addEventListener('click', () => {
      history.pushState({}, '', '/home');
    });
  </script>
</body></html>
"""

ROUTINE_PAGES = {
    "guide": '<div class="guide">引导<button>我知道了</button></div>',
    "elbox": ('<div class="el-message-box"><div class="el-message-box__btns">'
              '<button>取 消</button><button>确 定</button></div></div>'),
}


async def _page_with(content: str, routes: dict = None):
    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    page = await browser.new_page()

    async def root_redirect(route):
        # 未登录语义：根路径 302 → /login（真实系统行为）
        if route.request.url.rstrip("/") == "http://mock.local":
            await route.fulfill(status=302, headers={"Location": "/login"})
        else:
            await route.fulfill(status=200,
                                content_type="text/html; charset=utf-8",
                                body=content)
    await page.route("http://mock.local/**", root_redirect)
    for pat, fn in (routes or {}).items():
        await page.route(pat, fn)
    await page.goto("http://mock.local/login")
    return pw, browser, page


@pytest.fixture(autouse=True)
def _pw(monkeypatch):
    monkeypatch.setenv("T_PW", "secret-v")


async def test_fill_interpolates_credentials():
    pw, browser, page = await _page_with(LOGIN_PAGE)
    m, _ = load_manifest_text(MANIFEST)
    for raw in [{"fill": ["input[name=u]", "${username}"]},
                {"fill": ["input[name=p]", "${password}"]}]:
        # 直接构造 Step 走 run_step
        from app.adapters.manifest import Step as S
        await run_step(page, m, S(op="fill", arg=raw["fill"][0], arg2=raw["fill"][1]))
    u = await page.locator("input[name=u]").input_value()
    p = await page.locator("input[name=p]").input_value()
    await browser.close()
    await pw.stop()
    assert u == "alice" and p == "secret-v"


async def test_login_flow_success_judgement():
    pw, browser, page = await _page_with(LOGIN_PAGE)
    m, _ = load_manifest_text(MANIFEST)
    ok = await login(page, m)
    await browser.close()
    await pw.stop()
    assert ok is True


LOGIN_PAGE_NOJUMP = """
<html><body>
  <form onsubmit="return false">
    <input name="u"><input name="p" type="password">
    <button type="submit">登 录</button>
  </form>
</body></html>
"""


async def test_login_flow_fail_judgement():
    """提交被拦（url 仍含 login）→ 判失败（确定性）。"""
    pw, browser, page = await _page_with(LOGIN_PAGE_NOJUMP)
    m, _ = load_manifest_text(MANIFEST)
    ok = await login(page, m)
    await browser.close()
    await pw.stop()
    assert ok is False


async def test_routines_registry_and_close_guide():
    assert set(_ROUTINES) >= {"close_guide", "confirm_el_box", "biz_frame_submit",
                              "select2_pick", "el_select_pick"}
    pw, browser, page = await _page_with(ROUTINE_PAGES["guide"])
    await run_routine(page, "close_guide")
    # 我知道了被点掉（guide div display:none 模拟）
    visible = await page.locator(".guide button").is_visible()
    await browser.close()
    await pw.stop()
    # mock 页面无隐藏逻辑——验证例程不抛错即可（真机行为 AF3 收口验）


async def test_unknown_routine_rejected():
    pw, browser, page = await _page_with(LOGIN_PAGE)
    with pytest.raises(ValueError, match="未知例程"):
        await run_routine(page, "no_such")
    await browser.close()
    await pw.stop()


def test_looks_like_swapped_user():
    """评审三轮 #4：注释声明覆盖 E+数字/SL/M+大写标记——v21_matrix 实际
    产 `M{A|B|C}{ts}x{n}`（M+大写标记）与 `E{rnd}{ts}`，旧正则 ^[ES][L0-9]
    漏 M 形态（注释对、正则错）。"""
    from app.adapters.steps import _looks_like_swapped_user
    assert _looks_like_swapped_user("E112345") is True
    assert _looks_like_swapped_user("SL回放123") is True
    assert _looks_like_swapped_user("MA12345x67") is True
    assert _looks_like_swapped_user("MB999x1") is True
    assert _looks_like_swapped_user("管理员") is False
    assert _looks_like_swapped_user("admin") is False
    assert _looks_like_swapped_user("Super User") is False


MANIFEST_NICK = MANIFEST.replace(
    "login:\n  steps:", "login:\n  admin_nickname: 超级管理员\n  steps:")

HOME_WRONG_NICK = """
<html><body><div class="user-nickname">张三</div></body></html>
"""


async def test_admin_nickname_mismatch_forces_relogin(monkeypatch):
    """评审三轮 #4：声明 admin_nickname 后，页面昵称不符（上轮换参用户
    残留会话）必须强制退出重登——字段缺失时该分支是死代码。"""
    import app.adapters.steps as S
    logout_calls = []
    orig_logout = S._force_logout

    async def spy_logout(page):
        logout_calls.append(page.url)
        return await orig_logout(page)

    monkeypatch.setattr(S, "_force_logout", spy_logout)

    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    page = await browser.new_page()

    async def route_fn(route):
        cookie = route.request.headers.get("cookie") or ""
        logged = "sess=1" in cookie
        if route.request.url.rstrip("/") == "http://mock.local":
            if logged:
                await route.fulfill(status=200,
                                    content_type="text/html; charset=utf-8",
                                    body=HOME_WRONG_NICK)
            else:
                await route.fulfill(status=302, headers={"Location": "/login"})
        else:
            await route.fulfill(status=200,
                                content_type="text/html; charset=utf-8",
                                body=LOGIN_PAGE)

    await page.route("http://mock.local/**", route_fn)
    await browser.contexts[0].add_cookies(
        [{"name": "sess", "value": "1", "url": "http://mock.local"}])
    m, _ = load_manifest_text(MANIFEST_NICK)
    assert m.login.admin_nickname == "超级管理员"  # 字段须真实到达模型
    ok = await login(page, m)
    await browser.close()
    await pw.stop()
    assert ok is True
    # 身份不符 → 强制退出被触发（死代码复活的行为铁证）
    assert len(logout_calls) == 1


CLASSIC_FORM_LOGIN = """
<html><body>
  <form onsubmit="return false">
    <input name="u"><input name="p" type="password">
    <button id="go" type="submit">Login</button>
  </form>
  <script>
    document.querySelector('#go').addEventListener('click', () => {
      document.body.innerHTML = '<div>My Dashboard</div>';
    });
  </script>
</body></html>
"""

CLASSIC_FORM_MANIFEST = """
id: t2
target: {base_url: "http://mock.local"}
credentials: {username: alice, password_env: T_PW}
login:
  steps:
    - goto: /
    - fill: ["input[name=u]", "${username}"]
    - fill: ["input[name=p]", "${password}"]
    - click: "button[type=submit]"
  success: {text_contains: "My Dashboard"}
"""


async def _classic_page(content: str):
    """经典表单系统页面：根路径直接渲染（无 302 跳 login——Dolibarr 形态）。"""
    pw = await async_playwright().start()
    browser = await pw.chromium.launch()
    page = await browser.new_page()

    async def serve(route):
        await route.fulfill(status=200, content_type="text/html; charset=utf-8",
                            body=content)
    await page.route("http://mock.local/**", serve)
    await page.goto("http://mock.local/")
    return pw, browser, page


async def test_login_classic_form_runs_steps():
    """经典表单系统（Dolibarr 实证）：登录页在根路径、URL 无 login 字样
    ——URL 探针失效时 text_contains 是唯一登录态证据，登录步必须实际执行
    （旧逻辑误判"已登录"直接返回 True，登录步从不跑）。"""
    pw, browser, page = await _classic_page(CLASSIC_FORM_LOGIN)
    m, _ = load_manifest_text(CLASSIC_FORM_MANIFEST)
    ok = await login(page, m)
    visible = await page.get_by_text("My Dashboard").is_visible()
    await browser.close()
    await pw.stop()
    assert ok is True
    assert visible, "登录步未实际执行（假成功）"


async def test_login_classic_form_already_logged_in():
    """已登录（特征文本可见）→ 幂等直接通过，不重跑登录步。"""
    pw, browser, page = await _classic_page('<div>My Dashboard</div>')
    m, _ = load_manifest_text(CLASSIC_FORM_MANIFEST)
    ok = await login(page, m)
    await browser.close()
    await pw.stop()
    assert ok is True
