"""v2.1 七系统核心链矩阵测试（多轮多角度——用户要求升级 S43-4 标准）。

三维矩阵：
- 服务端 3 轮换参（每轮独立 ts，核心链全技能按序）；
- 插件端抽样（每系统 1 代表技能×executor.html 真实路径）；
- 异常角度：重复执行（同 id 二连跑，验证幂等/如实 fail）。

证据：demo/sprint-v21-matrix/matrix.json（全轮结果）。
用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/v21_matrix.py [server|ext]
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from playwright.async_api import async_playwright

SERVER = "http://127.0.0.1:8710/api/v1"
CDP = "http://127.0.0.1:9222"
EXT = "iifhfcajmahbdbjljhmfknfnachpcpgl"

# S43-4 验证过的七系统核心链（demo/sprint43/*-chain.json + 报告）
CHAINS = {
    "odoo": {"name": "销售链", "skills": [178, 179, 180],
             "ext_pick": 1},
    "dolibarr": {"name": "订单链", "skills": [188, 189, 190, 191],
                 "ext_pick": 188},
    "zentao": {"name": "QA 链", "skills": [166, 167, 168, 169],
               "ext_pick": 166},
    "erpnext": {"name": "CRM 链", "skills": [234, 235, 236],
                "ext_pick": 234},
    "snipe": {"name": "资产链", "skills": [154, 155, 156],
              "ext_pick": 154},
    "ruoyi": {"name": "权限链", "skills": [256, 257, 258],
              "ext_pick": 256},
    "jeecg": {"name": "表单链", "skills": [269, 270, 271],
              "ext_pick": 271},
}


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


async def replay(token, skill_id, overrides):
    async with httpx.AsyncClient(timeout=600) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        r = await c.post(f"{SERVER}/skills/{skill_id}/replay",
                         json={"overrides": overrides,
                               "confirm_side_effect": True})
        if r.status_code != 200:
            return f"http{r.status_code}"
        return r.json().get("status", "?")


def skill_vars(token, skill_id):
    with httpx.Client(timeout=30) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        r = c.get(f"{SERVER}/skills/{skill_id}/card")
        return [v["name"] for v in r.json().get("input_variables", [])]


async def server_rounds(token, out):
    """服务端 3 轮换参（A/B/C 独立 ts）+异常角度（同 id 重复执行）。"""
    for sys_id, cfg in CHAINS.items():
        for rnd, mark in enumerate("ABC"):
            ts = int(time.time()) % 100000
            row = {"system": sys_id, "round": rnd, "results": {}}
            for sid in cfg["skills"]:
                vs = skill_vars(token, sid)
                overrides = {v: f"M{mark}{ts}x{sid % 100}" for v in vs}
                row["results"][sid] = await replay(token, sid, overrides)
                await asyncio.sleep(1)
            out.append(row)
            flat = list(row["results"].values())
            ok = all(s in ("pass", "flaky-pass") for s in flat)
            print(f"[{sys_id}/{cfg['name']}] 轮{mark}: "
                  f"{'ALL PASS' if ok else 'FAIL'} {row['results']}")
        # 异常角度：首轮技能再执行一次（无换参——重复数据/幂等观察）
        sid0 = cfg["skills"][0]
        dup = await replay(token, sid0, {})
        out.append({"system": sys_id, "round": "dup-angle", "results": {sid0: dup}})
        print(f"[{sys_id}] 重复执行角度: {sid0} -> {dup}")


async def ext_rounds(token, out):
    """插件端主矩阵（v2.1 定位：插件=执行节点）：七系统核心链**全技能**
    ×2 轮，executor.html 真实路径（轮 2=重复执行角度，幂等观察）。
    每技能独立 Playwright 连接生命周期（attach 期间连接会被永久打断）。"""
    for sys_id, cfg in CHAINS.items():
        for rnd in (1, 2):
            for sid in cfg["skills"]:
                    # attach 期间宿主 Playwright 连接会被永久打断（AG5 矩阵
                    # 实证）——每技能独立连接生命周期：连→开页→点 go→断开→
                    # 纯 DB 轮询终态
                    async with async_playwright() as pw:
                        b = await pw.chromium.connect_over_cdp(CDP)
                        ctx = b.contexts[0]
                        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

                        def on_dialog(d):
                            async def _acc():
                                try:
                                    await d.accept()
                                except Exception:
                                    pass
                            asyncio.ensure_future(_acc())
                        page.on("dialog", on_dialog)
                        launched = False
                        try:
                            await page.goto(
                                f"chrome-extension://{EXT}/executor.html"
                                f"?skill={sid}&token={token}&auto=1",
                                timeout=15000)
                            await page.wait_for_timeout(2000)
                            # 点击前快照全局最新 extension run id（点击后
                            # 取会被本轮前面 run 推高——判定失真实证）
                            from app.db import SessionLocal as _S0
                            from app.models import ReplayRun as _RR0
                            _db0 = _S0()
                            _p0 = (_db0.query(_RR0)
                                   .filter(_RR0.executor == "extension")
                                   .order_by(_RR0.id.desc()).first())
                            _prev_id = _p0.id if _p0 else 0
                            _db0.close()
                            await page.locator("#go").click()
                            launched = True
                        except Exception as e:
                            out.append({"system": sys_id, "round": rnd,
                                        "skill": sid,
                                        "status": f"error:{str(e)[:40]}"})
                            print(f"[{sys_id}] 轮{rnd} #{sid}: error {str(e)[:60]}",
                                  flush=True)
                        finally:
                            try:
                                page.remove_listener("dialog", on_dialog)
                            except Exception:
                                pass
                        if not launched:
                            continue
                    # 连接已断——纯 DB 轮询 run 终态（_prev_id 已在点击前
                    # 快照——见上方）
                    status = "timeout"
                    for _ in range(90):
                        await asyncio.sleep(3)
                        _db = _S()
                        _r = (_db.query(_RR)
                              .filter(_RR.executor == "extension",
                                      _RR.id > _prev_id,
                                      _RR.skill_id == sid)
                              .order_by(_RR.id.desc()).first())
                        _db.close()
                        if _r and _r.status not in ("running",):
                            status = _r.status
                            break
                    out.append({"system": sys_id, "round": rnd,
                                "skill": sid, "status": status})
                    print(f"[{sys_id}] 轮{rnd} #{sid}: {status}", flush=True)


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "server"
    only = sys.argv[2] if len(sys.argv) > 2 else None  # 限单系统（短连接）
    if only:
        global CHAINS
        CHAINS = {only: CHAINS[only]}
    print(f"=== v2.1 七系统核心链矩阵（{mode}{'/' + only if only else ''}）===",
          flush=True)
    token = mint_token()
    out: list = []
    if mode == "server":
        await server_rounds(token, out)
    else:
        await ext_rounds(token, out)
    dest = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint-v21-matrix"
    dest.mkdir(parents=True, exist_ok=True)
    f = dest / f"matrix-{mode}{'-' + only if only else ''}.json"
    # 逐系统模式追加写（多调用合并证据）
    existing = []
    if only and f.exists():
        try:
            loaded = json.loads(f.read_text(encoding="utf-8"))
            loaded = [r for r in loaded if r.get("system") != only]
            existing = loaded
        except Exception:
            pass
    f.write_text(json.dumps(existing + out, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    n_pass = sum(1 for r in out
                 if all(s in ("pass", "flaky-pass")
                        for s in (r.get("results") or {"x": r.get("status", "fail")}).values()))
    print(f"\n结论: {n_pass}/{len(out)} 组通过；证据 {f}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
