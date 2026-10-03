"""AF3 真机收口：7 系统清单登录验证（9222 常驻浏览器，全程可见）。

按凭据可用性分两批：
- 批 1（清单 password_literal 本地演示凭据）：ruoyi/jeecg/snipe/erpnext/dolibarr
- 批 2（env 凭据缺席，跳过并如实报告）：zentao(ZENTAO_PW)/odoo(ODOO_PW)

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/af3_login_check.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright

from app.adapters.manifest import load_adapter_dir
from app.adapters.steps import login as adapter_login

CDP = "http://127.0.0.1:9222"
BATCH1 = ["ruoyi", "jeecg", "snipe", "erpnext", "dolibarr"]
SKIP = ["zentao", "odoo"]


async def main() -> None:
    manifests, lints = load_adapter_dir(Path("adapters"))
    by_id = {m.id: m for m in manifests}
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(CDP)
        ctx = browser.contexts[0]
        for aid in BATCH1:
            m = by_id.get(aid)
            if not m or not m.login:
                results[aid] = "no-login"
                continue
            # 复用既有 page（宿主 persistent_context 场景 new_page 有驱动
            # 冲突——直连 CDP 目标页最稳）
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            try:
                ok = await adapter_login(page, m)
                results[aid] = "PASS" if ok else f"FAIL(url={page.url[:60]})"
            except Exception as e:
                results[aid] = f"ERROR({type(e).__name__}: {str(e)[:60]})"
            # 不 close（复用页）
    print("=== AF3 系统清单登录验证 ===")
    for k, v in results.items():
        print(f"  {k:10s} {v}")
    for k in SKIP:
        print(f"  {k:10s} SKIP(env 凭据缺席——ZENTAO_PW/ODOO_PW 未注入)")


asyncio.run(main())
