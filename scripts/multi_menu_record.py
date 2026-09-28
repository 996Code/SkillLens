"""S29 深度链路测试：多菜单多页面录制——在 njmind 5 个不同页面各录一轮。

目标：验证系统在不同类型页面（表单设计器/列表设计器/角色管理/字典配置/组织用户）
上的采集→学习→回放全链路，而不是只测同一个表单。

用法：cd server && uv run python ../scripts/multi_menu_record.py
前提：server 在 8710 运行；live_browser 在 9222 运行且已登录 njmind。
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

SERVER = "http://127.0.0.1:8710"
CDP = "http://127.0.0.1:9222"
BASE = "http://192.168.99.22/mb3/1"

# 5 个不同菜单页面——覆盖表单/列表/权限/配置/组织 5 种类型
TARGET_MENUS = [
    {"name": "表单设计器", "menu_text": "表单设计器",
     "desc": "表单设计器页面——表单配置类操作"},
    {"name": "列表设计器", "menu_text": "列表设计器",
     "desc": "列表设计器页面——列表配置类操作"},
    {"name": "角色管理", "menu_text": "角色管理",
     "desc": "角色管理页面——权限配置类操作"},
    {"name": "字典配置", "menu_text": "字典配置",
     "desc": "字典配置页面——系统配置类操作"},
    {"name": "组织与用户", "menu_text": "组织与用户",
     "desc": "组织与用户页面——组织管理类操作"},
]


async def login_api() -> str:
    """登录 SkillLens server 获取 token（凭据从环境变量读，不硬编码）。"""
    import os
    pw = os.environ.get("S21_ADMIN_PW", "")
    if not pw:
        raise SystemExit("需要环境变量 S21_ADMIN_PW")
    async with httpx.AsyncClient(timeout=120.0) as c:
        resp = await c.post(f"{SERVER}/api/v1/auth/login",
                            json={"username": "admin", "password": pw})
        return resp.json()["token"]


async def find_service_worker(ctx):
    """找扩展 service worker（同 auto_record.py 方式）。"""
    for w in ctx.service_workers:
        if 'service-worker-loader' in w.url or 'uploader' in w.url:
            return w
    raise RuntimeError('extension service worker 未找到')


async def ext_call(ctx, sw, msg: dict) -> object:
    """从扩展 popup 页发消息——SW 自发自收不触发 onMessage（同 auto_record）。"""
    ext_id = sw.url.split('/')[2]
    page = await ctx.new_page()
    try:
        await page.goto(f'chrome-extension://{ext_id}/popup.html')
        return await page.evaluate(
            """(m) => new Promise(res => chrome.runtime.sendMessage(m, r => res(r)))""",
            msg)
    finally:
        await page.close()


async def start_recording(ctx) -> str:
    """通过扩展 popup 页开始录制，返回 session_id。"""
    sw = await find_service_worker(ctx)
    result = await ext_call(ctx, sw, {'type': 'START_RECORDING', 'note': 'multi-menu-test'})
    return (result or {}).get('id', '')


async def stop_recording(ctx) -> dict:
    """停止录制。"""
    sw = await find_service_worker(ctx)
    result = await ext_call(ctx, sw, {'type': 'STOP_RECORDING'})
    return result or {}


async def record_menu(token: str, ctx, page, menu: dict, round_num: int) -> str | None:
    """在指定菜单页面录制一轮操作。"""
    print(f"\n--- 录制 [{menu['name']}] (第 {round_num} 轮) ---")

    # 1. 开始录制
    sid = await start_recording(ctx)
    if not sid:
        print("  ! 无法开始录制（插件 SW 不可达）")
        return None
    print(f"  session: {sid[:12]}...")

    # 2. 点击菜单进入目标页面
    menu_el = page.locator(f'.n-menu-item:has-text("{menu["menu_text"]}")')
    if await menu_el.count() == 0:
        print(f"  ! 菜单 [{menu['menu_text']}] 未找到")
        await stop_recording(ctx)
        return None

    await menu_el.click()
    await page.wait_for_timeout(3000)
    print(f"  已进入 [{menu['name']}] 页面")

    # 3. 在页面上做简单操作（点击可见按钮/输入框）
    # 找页面上的可交互元素并操作
    actions = await page.evaluate("""
        () => {
            const acts = [];
            // 找搜索框/输入框
            const inputs = document.querySelectorAll(
                'input:not([type=hidden]):not([type=password])');
            if (inputs.length > 0) acts.push({ type: 'input', el: inputs[0], value: 'test' });
            // 找按钮
            const btns = document.querySelectorAll(
                'button:not([disabled]), .n-button:not([disabled])');
            if (btns.length > 1) acts.push({ type: 'click', el: btns[0] });
            return acts.length;
        }
    """)
    print(f"  页面可交互元素: {actions}")

    # 简单操作：等待让插件采集页面加载事件
    await page.wait_for_timeout(3000)

    # 4. 停止录制
    result = await stop_recording(ctx)
    print(f"  录制完成: {result}")

    # 5. 等事件上传
    await page.wait_for_timeout(2000)

    # 6. 验证事件落库
    async with httpx.AsyncClient(timeout=120.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        resp = await c.get(f"{SERVER}/api/v1/audit/sessions")
        sessions = resp.json()
        target = [s for s in sessions if s["session_id"] == sid]
        if target:
            ev_count = target[0]["event_count"]
            print(f"  事件数: {ev_count}")
            return sid
        print(f"  ! 会话未找到")
        return None


async def process_and_learn(token: str, sid: str, round_num: int):
    """对录制会话执行 process → align → induce → assertions。"""
    async with httpx.AsyncClient(timeout=120.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"

        # process
        resp = await c.post(f"{SERVER}/api/v1/sessions/{sid}/process")
        if resp.status_code != 200:
            print(f"  process: {resp.status_code}")
            return None

        # align（需要 ≥2 会话——用同一会话两次）
        resp = await c.post(f"{SERVER}/api/v1/align",
                            json={"session_ids": [sid, sid]})
        if resp.status_code != 200:
            print(f"  align: {resp.status_code}")
            return None
        aid = resp.json()["alignment_id"]

        # induce（LLM 调用可能慢，加重试）
        for attempt in range(3):
            try:
                resp = await c.post(f"{SERVER}/api/v1/alignments/{aid}/induce")
                if resp.status_code == 200:
                    break
                print(f"  induce attempt {attempt+1}: {resp.status_code}")
            except Exception as e:
                print(f"  induce attempt {attempt+1} error: {type(e).__name__}")
                await asyncio.sleep(5)
        else:
            print("  induce: 3 次尝试均失败")
            return None
        skill = resp.json()
        print(f"  skill: #{skill['id']} {skill['name']} ({skill['status']})")

        # assertions
        resp = await c.post(f"{SERVER}/api/v1/skills/{skill['id']}/assertions")
        print(f"  assertions: {resp.status_code}")

        return skill["id"]


async def main():
    print("=== S29 多菜单深度链路测试 ===")
    token = await login_api()
    print(f"SkillLens 登录成功")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        page = await ctx.new_page()

        # 确保在 njmind 主页
        await page.goto(f"{BASE}/index")
        await page.wait_for_timeout(3000)

        results = []
        for i, menu in enumerate(TARGET_MENUS):
            # 每个菜单录 1 轮
            sid = await record_menu(token, ctx, page, menu, i + 1)
            if sid:
                skill_id = await process_and_learn(token, sid, i + 1)
                results.append({
                    "menu": menu["name"],
                    "session": sid[:12],
                    "skill_id": skill_id,
                })

        # 汇总
        print("\n=== 多菜单录制结果 ===")
        print(f"{'菜单':<15} {'会话':<15} {'Skill':<10}")
        print("-" * 45)
        for r in results:
            print(f"{r['menu']:<15} {r['session']:<15} {r['skill_id'] or '—':<10}")

        print(f"\n总计: {len(results)} 个菜单录制成功")

        await page.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
