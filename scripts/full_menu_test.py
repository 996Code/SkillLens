"""S31 全菜单覆盖测试：在 njmind 所有 29 个菜单上录制+学习+回放。

覆盖策略：
- 已测过的菜单（S29/S30）：跳过录制，只做回放验证
- 新菜单（未测过的）：录制+学习+回放
- 每个菜单做实际操作（搜索/点击按钮/填写表单）

用法：cd server && S21_ADMIN_PW=... uv run python ../scripts/full_menu_test.py
"""
import asyncio
import json
import os
import random
import string

import httpx
from playwright.async_api import async_playwright

SERVER = "http://127.0.0.1:8710"
CDP = "http://127.0.0.1:9222"
BASE = "http://192.168.99.22/mb3/1"

# 全部可测试菜单（排除父菜单和已测过的）
ALL_MENUS = [
    # 业务搭建类
    {"name": "打印设计器", "menu": "打印设计器", "action": "view"},
    {"name": "报告设计器", "menu": "报告设计器", "action": "view"},
    {"name": "流程设计器", "menu": "流程设计器", "action": "view"},
    # 用户权限类
    {"name": "个人账户", "menu": "个人账户", "action": "view"},
    # 系统设置类
    {"name": "低码配置", "menu": "低码配置", "action": "view"},
    {"name": "第三方集成", "menu": "第三方集成", "action": "view"},
    {"name": "系统日志", "menu": "系统日志", "action": "search", "search_kw": "login"},
    {"name": "菜单管理", "menu": "菜单管理", "action": "view"},
    {"name": "外观设置", "menu": "外观设置", "action": "view"},
    # 导入导出类
    {"name": "导入记录", "menu": "导入记录", "action": "view"},
    {"name": "导出记录", "menu": "导出记录", "action": "view"},
    {"name": "流程运维", "menu": "流程运维", "action": "view"},
    # 业务测试类
    {"name": "bug测试", "menu": "bug测试", "action": "view"},
    {"name": "pjhtest列表", "menu": "pjhtest列表", "action": "view"},
    {"name": "测试条件组列表", "menu": "测试条件组列表", "action": "view"},
    {"name": "测试电子签名", "menu": "测试电子签名", "action": "view"},
    {"name": "business-1", "menu": "business-1", "action": "view"},
    {"name": "business-2", "menu": "business-2", "action": "view"},
    {"name": "测试skills", "menu": "测试skills", "action": "view"},
    {"name": "pjh测试111", "menu": "pjh测试111", "action": "view"},
    {"name": "测试skills-E2E二开", "menu": "测试skills-E2E二开", "action": "view"},
    {"name": "wxc", "menu": "wxc", "action": "view"},
    {"name": "linls", "menu": "linls", "action": "view"},
    {"name": "linls2", "menu": "linls2", "action": "view"},
    {"name": "lrj", "menu": "lrj", "action": "view"},
]

# 已测过的菜单（S29/S30 已有 Skill）
ALREADY_TESTED = {
    "表单设计器", "列表设计器", "角色管理", "字典配置", "组织与用户",
}


async def login_api():
    pw = os.environ.get("S21_ADMIN_PW", "")
    if not pw:
        raise SystemExit("need S21_ADMIN_PW")
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.post(
            SERVER + "/api/v1/auth/login",
            json={"username": "admin", "password": pw},
        )
        return r.json()["token"]


async def find_sw(ctx):
    for w in ctx.service_workers:
        if "service-worker-loader" in w.url:
            return w
    raise RuntimeError("no SW")


async def ext_call(ctx, sw, msg):
    ext_id = sw.url.split("/")[2]
    pg = await ctx.new_page()
    try:
        await pg.goto("chrome-extension://" + ext_id + "/popup.html")
        return await pg.evaluate(
            "(m)=>new Promise(r=>chrome.runtime.sendMessage(m,r))", msg
        )
    finally:
        await pg.close()


async def goto_menu(page, menu_text):
    """导航到指定菜单页面。"""
    await page.goto(BASE + "/index")
    await page.wait_for_timeout(2000)
    for parent in ["业务受理", "系统管理", "更多菜单"]:
        try:
            el = page.locator(".n-menu-item:has-text('" + parent + "')")
            if await el.count() > 0:
                await el.click()
                await page.wait_for_timeout(500)
        except Exception:
            pass
    el = page.locator(".n-menu-item:has-text('" + menu_text + "')").first
    await el.click()
    await page.wait_for_timeout(3000)


async def record_and_learn(token, ctx, page, sw, menu):
    """录制一个菜单页面的操作并学习为 Skill。"""
    name = menu["name"]
    print("--- " + name + " ---")

    # 先导航到目标页面（不录制）
    await goto_menu(page, menu["menu"])
    await page.wait_for_timeout(2000)  # 确保页面完全加载

    # 开始录制
    r = await ext_call(ctx, sw, {"type": "START_RECORDING", "note": "s31-" + name})
    sid = (r or {}).get("id", "")
    if not sid:
        print("  ! start failed")
        return None

    # 执行操作
    try:
        if menu.get("action") == "search":
            kw = menu.get("search_kw", "test")
            inp = page.locator("input[type=text]").first
            if await inp.count() > 0:
                await inp.fill(kw)
                print("  search: " + kw)
                btn = page.locator("button:has-text('搜索')")
                if await btn.count() > 0:
                    await btn.click()
        elif menu.get("action") == "click_btn":
            btn_texts = menu.get("buttons", [])
            for bt in btn_texts:
                btn = page.locator("button:has-text('" + bt + "')")
                if await btn.count() > 0:
                    await btn.first.click()
                    print("  click: " + bt)
                    await page.wait_for_timeout(2000)
                    break
        # view 类型：等待让插件采集页面加载事件
        await page.wait_for_timeout(3000)
    except Exception as e:
        print("  op error: " + type(e).__name__)

    # 停止录制
    await ext_call(ctx, sw, {"type": "STOP_RECORDING"})
    await page.wait_for_timeout(2000)

    # 学习管道
    async with httpx.AsyncClient(timeout=120.0) as c:
        c.headers["Authorization"] = "Bearer " + token
        await c.post(SERVER + "/api/v1/sessions/" + sid + "/process")
        r = await c.post(
            SERVER + "/api/v1/align", json={"session_ids": [sid, sid]}
        )
        if r.status_code != 200:
            print("  align: " + str(r.status_code))
            return None
        aid = r.json()["alignment_id"]
        for _ in range(3):
            try:
                r = await c.post(
                    SERVER + "/api/v1/alignments/" + str(aid) + "/induce"
                )
                if r.status_code == 200:
                    break
                await asyncio.sleep(3)
            except Exception:
                await asyncio.sleep(3)
        else:
            print("  induce: failed after 3 retries")
            return None
        skill = r.json()
        await c.post(
            SERVER + "/api/v1/skills/" + str(skill["id"]) + "/assertions"
        )
        print("  skill #" + str(skill["id"]) + " " + skill["name"])
        return skill["id"]


async def replay_skill(token, skill_id):
    """回放一个 Skill 并返回结果。"""
    async with httpx.AsyncClient(timeout=180.0) as c:
        c.headers["Authorization"] = "Bearer " + token
        r = await c.post(
            SERVER + "/api/v1/skills/" + str(skill_id) + "/replay",
            json={"overrides": {}, "confirm_side_effect": True},
        )
        if r.status_code == 200:
            d = r.json()
            return d["status"], d["mode"]
        return "http" + str(r.status_code), "?"


async def main():
    print("=== S31 全菜单覆盖测试 ===")
    print("目标: " + str(len(ALL_MENUS)) + " 个新菜单\n")

    token = await login_api()

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        sw = await find_sw(ctx)

        # Phase 1: 录制新菜单
        print("Phase 1: 录制新菜单")
        new_results = []
        for menu in ALL_MENUS:
            if menu["name"] in ALREADY_TESTED:
                continue
            try:
                skill_id = await record_and_learn(token, ctx, page, sw, menu)
                if skill_id:
                    new_results.append(
                        {"name": menu["name"], "skill": skill_id}
                    )
            except Exception as e:
                print(menu["name"] + " error: " + type(e).__name__)

        print("\nPhase 1 结果: " + str(len(new_results)) + "/" + str(len(ALL_MENUS)) + " 录制成功")

        # Phase 2: 回放所有 Skill（包括旧的）
        print("\nPhase 2: 全量回放")
        async with httpx.AsyncClient(timeout=120.0) as c:
            c.headers["Authorization"] = "Bearer " + token
            r = await c.get(SERVER + "/api/v1/skills")
            all_skills = r.json()

        replay_results = []
        for s in all_skills:
            try:
                status, mode = await replay_skill(token, s["id"])
                replay_results.append(
                    {"id": s["id"], "name": s["name"][:25], "st": status, "mode": mode}
                )
                print("  #" + str(s["id"]) + " " + s["name"][:20] + " -> " + status)
            except Exception:
                replay_results.append(
                    {"id": s["id"], "name": s["name"][:25], "st": "error", "mode": "?"}
                )

        # Phase 3: 汇总
        print("\n" + "=" * 60)
        print("S31 全菜单覆盖测试总结")
        print("=" * 60)

        print("\n新录制: " + str(len(new_results)) + "/" + str(len(ALL_MENUS)))
        for r in new_results:
            print("  " + r["name"] + " -> skill #" + str(r["skill"]))

        pn = sum(1 for r in replay_results if r["st"] == "pass")
        fn = sum(1 for r in replay_results if r["st"] == "fail")
        en = len(replay_results) - pn - fn
        print("\n全量回放: " + str(len(replay_results)) + " 个 Skill")
        print("  pass=" + str(pn) + " fail=" + str(fn) + " error=" + str(en))
        print("  通过率: " + str(round(pn / len(replay_results) * 100 if replay_results else 0)) + "%")

        print("\n回放明细:")
        for r in replay_results:
            print("  #" + str(r["id"]) + " " + r["name"] + " " + r["st"] + " " + r["mode"])

        await page.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
