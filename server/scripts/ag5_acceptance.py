"""AG5 客户端闭环验收：插件端执行 + 双端一致性 + 真实登录态。

验收集（≥3 技能跨 2 系统）：
- 禅道 #272 SaveDocument（AF4 清单录制产物——写技能，真实登录态）
- JeecG #271 OnlineFormDataCreateFlow（链式 Fill）
- Odoo #1 PartnerQuickCreate（写技能）

双端一致：同技能服务端 replay（af5 链路）vs 插件端 executor 页——
status 一致（pass↔pass / fail↔fail 视为一致；pass vs fail 不一致记录）。

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/ag5_acceptance.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from playwright.async_api import async_playwright

from app.adapters.manifest import load_adapter_dir
from app.adapters.steps import login as adapter_login

SERVER = "http://127.0.0.1:8710/api/v1"
CDP = "http://127.0.0.1:9222"
EXT = "iifhfcajmahbdbjljhmfknfnachpcpgl"

TARGETS = [
    {"adapter": "zentao", "skill": 272, "desc": "禅道 SaveDocument（写）"},
    {"adapter": "jeecg", "skill": 271, "desc": "JeecG Fill（链式）"},
    {"adapter": "odoo", "skill": 1, "desc": "Odoo PartnerQuickCreate（写）"},
]


def mint_token() -> str:
    from app.auth import issue_token
    from app.db import SessionLocal
    from app.models import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.username == "admin").first()
        return issue_token(db, u.id)
    finally:
        db.close()


async def run_on_executor(ctx, token: str, skill_id: int) -> str:
    """插件端：executor 页真实点击流程（C1 confirm 自动接受）。"""
    page = await ctx.new_page()
    try:
        # dialog 竞态防护：逐个接受（快速连发时 No dialog 报错吞掉重试）
        def on_dialog(d):
            async def _accept():
                try:
                    await d.accept()
                except Exception:
                    pass
            asyncio.ensure_future(_accept())
        page.on("dialog", on_dialog)
        await page.goto(f"chrome-extension://{EXT}/executor.html"
                        f"?skill={skill_id}&token={token}&auto=1")
        await page.wait_for_timeout(2500)
        await page.locator("#go").click()
        for _ in range(100):
            await asyncio.sleep(3)
            txt = await page.locator("#log").text_content()
            if txt and any(k in txt for k in ("完成：", "失败：", "中断：")):
                break
        # 末行提取 status
        last = (txt or "").strip().splitlines()[-1] if txt else ""
        for st in ("pass", "fail", "aborted", "done"):
            if st in last:
                return st
        return f"unknown({last[:40]})"
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def run_on_server(token: str, skill_id: int) -> str:
    async with httpx.AsyncClient(timeout=600) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        r = await c.post(f"{SERVER}/skills/{skill_id}/replay",
                         json={"overrides": {}, "confirm_side_effect": True})
        if r.status_code != 200:
            return f"http{r.status_code}"
        return r.json().get("status", "?")


async def main():
    print("=== AG5 客户端闭环验收 ===")
    token = mint_token()
    manifests, _ = load_adapter_dir(Path(__file__).resolve().parent.parent / "adapters")
    by_id = {m.id: m for m in manifests}
    results = []
    async with async_playwright() as p:
        b = await p.chromium.connect_over_cdp(CDP)
        ctx = b.contexts[0]
        # 真实登录态：三系统清单登录（幂等——已登录直通）
        for t in TARGETS:
            m = by_id[t["adapter"]]
            ok = await adapter_login(ctx.pages[0], m)
            t["login"] = "PASS" if ok else "FAIL"
            print(f"登录[{t['adapter']}]: {t['login']}")
        for t in TARGETS:
            print(f"\n[{t['desc']}]")
            await ctx.new_page()  # 空白执行目标页签
            ext_status = await run_on_executor(ctx, token, t["skill"])
            srv_status = await run_on_server(token, t["skill"])
            consist = "一致" if ext_status.split("+")[0] == srv_status else "不一致"
            t.update(ext=ext_status, server=srv_status, consist=consist)
            print(f"  插件端: {ext_status} | 服务端: {srv_status} → {consist}")
            results.append(t)

    print("\n=== 验收矩阵 ===")
    n_pass = sum(1 for r in results if "pass" in r.get("ext", ""))
    n_login = sum(1 for r in results if r.get("login") == "PASS")
    print(f"插件端执行 pass: {n_pass}/{len(results)}；真实登录态: {n_login}/{len(results)}")
    for r in results:
        print(f"  {r['desc']}: ext={r.get('ext')} server={r.get('server')} {r.get('consist')}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint-ag5"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ag5-acceptance.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"证据: {out / 'ag5-acceptance.json'}")


if __name__ == "__main__":
    asyncio.run(main())
