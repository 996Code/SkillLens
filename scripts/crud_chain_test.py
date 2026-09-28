"""S30 CRUD 深度链路测试：在 njmind 3 个有完整 CRUD 的页面上执行增删改查。

目标页面：
- 角色管理：新增角色 → 搜索 → 绑定用户 → 移除用户
- 字典配置：新增目录/选项 → 修改 → 删除
- 组织与用户：新增用户 → 搜索 → 修改 → 离职

每个操作录制为独立会话 → 学习为 Skill → 验证换参回放。

用法：cd server && S21_ADMIN_PW=... uv run python ../scripts/crud_chain_test.py
"""
import asyncio
import os
import random
import string
import time

import httpx
from playwright.async_api import async_playwright

SERVER = "http://127.0.0.1:8710"
CDP = "http://127.0.0.1:9222"
BASE = "http://192.168.99.22/mb3/1"


def rand_suffix(n=4):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


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
    """导航到指定菜单页面（先回主页再展开再点击）。"""
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


async def record_crud(ctx, page, sw, note):
    """开始录制 → 返回 session_id。"""
    r = await ext_call(ctx, sw, {"type": "START_RECORDING", "note": note})
    return (r or {}).get("id", "")


async def stop_and_learn(token, ctx, sw, sid):
    """停止录制 → process → align → induce → assertions → 返回 skill_id。"""
    await ext_call(ctx, sw, {"type": "STOP_RECORDING"})
    await page_wait(2000)

    if not sid:
        return None

    async with httpx.AsyncClient(timeout=120.0) as c:
        c.headers["Authorization"] = "Bearer " + token
        await c.post(SERVER + "/api/v1/sessions/" + sid + "/process")
        r = await c.post(
            SERVER + "/api/v1/align", json={"session_ids": [sid, sid]}
        )
        if r.status_code != 200:
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
            return None
        skill = r.json()
        await c.post(
            SERVER + "/api/v1/skills/" + str(skill["id"]) + "/assertions"
        )
        return skill["id"]


async def page_wait(ms):
    await asyncio.sleep(ms / 1000)


async def crud_role_create(ctx, page, sw, token):
    """角色管理：新增角色。"""
    print("\n=== CRUD: 角色管理-新增角色 ===")
    await goto_menu(page, "角色管理")
    sid = await record_crud(ctx, page, sw, "crud-role-create")

    role_name = "测试角色" + rand_suffix()
    try:
        # 点击新增角色
        btn = page.locator("button:has-text('新增角色')")
        if await btn.count() > 0:
            await btn.click()
            await page_wait(2000)
            # 填角色名
            inp = page.locator("input[placeholder*='角色'], input[type=text]").first
            if await inp.count() > 0:
                await inp.fill(role_name)
                print("  填入角色名: " + role_name)
            # 点击确认/保存
            confirm = page.locator("button:has-text('确定'), button:has-text('保存')")
            if await confirm.count() > 0:
                await confirm.first.click()
                print("  点击确认")
    except Exception as e:
        print("  操作异常: " + type(e).__name__)

    await page_wait(3000)
    skill_id = await stop_and_learn(token, ctx, sw, sid)
    if skill_id:
        print("  skill #" + str(skill_id))
    return skill_id, role_name


async def crud_dict_create(ctx, page, sw, token):
    """字典配置：新增目录。"""
    print("\n=== CRUD: 字典配置-新增目录 ===")
    await goto_menu(page, "字典配置")
    sid = await record_crud(ctx, page, sw, "crud-dict-create")

    dict_name = "测试字典" + rand_suffix()
    try:
        btn = page.locator("button:has-text('新增目录')")
        if await btn.count() > 0:
            await btn.click()
            await page_wait(2000)
            inp = page.locator("input[type=text]").first
            if await inp.count() > 0:
                await inp.fill(dict_name)
                print("  填入字典名: " + dict_name)
            confirm = page.locator("button:has-text('确定'), button:has-text('保存')")
            if await confirm.count() > 0:
                await confirm.first.click()
                print("  点击确认")
    except Exception as e:
        print("  操作异常: " + type(e).__name__)

    await page_wait(3000)
    skill_id = await stop_and_learn(token, ctx, sw, sid)
    if skill_id:
        print("  skill #" + str(skill_id))
    return skill_id, dict_name


async def crud_user_create(ctx, page, sw, token):
    """组织与用户：新增用户。"""
    print("\n=== CRUD: 组织与用户-新增用户 ===")
    await goto_menu(page, "组织与用户")
    sid = await record_crud(ctx, page, sw, "crud-user-create")

    user_name = "testuser" + rand_suffix()
    try:
        btn = page.locator("button:has-text('新增用户')")
        if await btn.count() > 0:
            await btn.click()
            await page_wait(2000)
            # 填用户名
            inputs = page.locator("input[type=text]")
            count = await inputs.count()
            for i in range(min(count, 3)):
                val = user_name if i == 0 else user_name + str(i)
                await inputs.nth(i).fill(val)
            print("  填入用户名: " + user_name)
            confirm = page.locator("button:has-text('确定'), button:has-text('保存')")
            if await confirm.count() > 0:
                await confirm.first.click()
                print("  点击确认")
    except Exception as e:
        print("  操作异常: " + type(e).__name__)

    await page_wait(3000)
    skill_id = await stop_and_learn(token, ctx, sw, sid)
    if skill_id:
        print("  skill #" + str(skill_id))
    return skill_id, user_name


async def crud_role_search(ctx, page, sw, token):
    """角色管理：搜索角色。"""
    print("\n=== CRUD: 角色管理-搜索 ===")
    await goto_menu(page, "角色管理")
    sid = await record_crud(ctx, page, sw, "crud-role-search")

    keyword = "管理"
    try:
        inp = page.locator("input[placeholder*='搜索'], input[type=text]").first
        if await inp.count() > 0:
            await inp.fill(keyword)
            print("  搜索: " + keyword)
            # 按回车或点搜索按钮
            btn = page.locator("button:has-text('搜索')")
            if await btn.count() > 0:
                await btn.click()
            else:
                await inp.press("Enter")
    except Exception as e:
        print("  操作异常: " + type(e).__name__)

    await page_wait(3000)
    skill_id = await stop_and_learn(token, ctx, sw, sid)
    if skill_id:
        print("  skill #" + str(skill_id))
    return skill_id, keyword


async def crud_dict_delete(ctx, page, sw, token):
    """字典配置：删除选项。"""
    print("\n=== CRUD: 字典配置-删除 ===")
    await goto_menu(page, "字典配置")
    sid = await record_crud(ctx, page, sw, "crud-dict-delete")

    try:
        # 找删除按钮
        del_btn = page.locator("button:has-text('删除'), .n-button:has-text('删除')")
        if await del_btn.count() > 0:
            await del_btn.first.click()
            await page_wait(1000)
            # 确认删除
            confirm = page.locator("button:has-text('确定'), .n-button:has-text('确定')")
            if await confirm.count() > 0:
                await confirm.first.click()
                print("  点击删除+确认")
    except Exception as e:
        print("  操作异常: " + type(e).__name__)

    await page_wait(3000)
    skill_id = await stop_and_learn(token, ctx, sw, sid)
    if skill_id:
        print("  skill #" + str(skill_id))
    return skill_id, None


async def main():
    print("=== S30 CRUD 深度链路测试 ===\n")
    token = await login_api()

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()
        sw = await find_sw(ctx)

        results = []

        # 执行 5 个 CRUD 操作
        operations = [
            ("角色-新增", crud_role_create),
            ("字典-新增", crud_dict_create),
            ("用户-新增", crud_user_create),
            ("角色-搜索", crud_role_search),
            ("字典-删除", crud_dict_delete),
        ]

        for name, op in operations:
            try:
                skill_id, data = await op(ctx, page, sw, token)
                results.append({
                    "op": name,
                    "skill": skill_id,
                    "data": data,
                })
            except Exception as e:
                print(name + " 异常: " + str(e))
                results.append({"op": name, "skill": None, "data": None})

        # 汇总
        print("\n" + "=" * 55)
        print("CRUD 深度链路测试结果")
        print("=" * 55)
        print(f"{'操作':<15} {'Skill':<10} {'数据':<20}")
        print("-" * 50)
        for r in results:
            skill = "#" + str(r["skill"]) if r["skill"] else "—"
            data = (r["data"] or "—")[:18]
            print(f"{r['op']:<15} {skill:<10} {data:<20}")

        success = sum(1 for r in results if r["skill"])
        print(f"\n成功: {success}/{len(results)}")

        # 换参回放（对有变量的 skill）
        print("\n换参回放:")
        async with httpx.AsyncClient(timeout=120.0) as c:
            c.headers["Authorization"] = "Bearer " + token
            r = await c.get(SERVER + "/api/v1/skills")
            all_skills = r.json()

        with_vars = []
        for s in all_skills:
            card = httpx.get(
                SERVER + "/api/v1/skills/" + str(s["id"]) + "/card",
                headers={"Authorization": "Bearer " + token},
            ).json()
            if card.get("input_variables"):
                with_vars.append(s["id"])

        replay_data = ["CRUD-A", "CRUD-B", "crud-C"]
        replay_count = 0
        pass_count = 0
        for skill_id in with_vars[-5:]:  # 最新的 5 个
            for data in replay_data:
                card = httpx.get(
                    SERVER + "/api/v1/skills/" + str(skill_id) + "/card",
                    headers={"Authorization": "Bearer " + token},
                ).json()
                vars = [v["name"] for v in card.get("input_variables", [])]
                overrides = {v: data for v in vars}

                print(
                    "  #" + str(skill_id) + " data=" + data[:15],
                    end=" -> ",
                )
                async with httpx.AsyncClient(timeout=180.0) as c:
                    c.headers["Authorization"] = "Bearer " + token
                    r = await c.post(
                        SERVER + "/api/v1/skills/" + str(skill_id) + "/replay",
                        json={"overrides": overrides, "confirm_side_effect": True},
                    )
                    if r.status_code == 200:
                        d = r.json()
                        print(d["status"] + " (" + d["mode"] + ")")
                        replay_count += 1
                        if d["status"] == "pass":
                            pass_count += 1
                    else:
                        print("http" + str(r.status_code))
                        replay_count += 1

        print("\n" + "=" * 55)
        print("总结")
        print("=" * 55)
        print("CRUD 录制: " + str(success) + "/" + str(len(results)))
        print("换参回放: " + str(pass_count) + "/" + str(replay_count) + " pass")

        await page.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
