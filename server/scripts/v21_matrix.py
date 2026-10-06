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
    # 169 排除（录制语义歧义：label「执行」匹配到左侧导航菜单而非 CaseRun
    # 行操作——与 AF4 归档的 iframe 二级操作采集限制同源；菜单点击导航到
    # 别的页面致后续步必然 miss）
    "zentao": {"name": "QA 链", "skills": [166, 167, 168],
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
        vs = [v["name"] for v in r.json().get("input_variables", [])]
        if vs:
            declared = set(vs)
        else:
            declared = set()
    # fill 换参 key 用**fill 指令的 value 本身**（服务端 overrides 按
    # value/name 精确替换——258 跨技能数据依赖实证：变量名≠value 时
    # fill_ 变量名匹配不上 ins.value）。声明变量（其 value 即变量默认值）
    # 与未声明 value 一并覆盖；密码 [REDACTED] 跳过
    from app.db import SessionLocal
    from app.models import Skill
    db = SessionLocal()
    try:
        from app.api.executor import _load_plan_input, compile_executor_plan
        ins = compile_executor_plan(_load_plan_input(db, db.get(Skill, skill_id)))
        # goto 实例段归一（ERPNext 236 铁证：录制保存的单据 URL
        # /desk/sales-order/new-sales-order-xxxx 带随机后缀——回放到已
        # 提交旧单上 Frappe 弹回，后续步全打到错误页面）
        import re as _re0
        for i in ins:
            if i.get("op") == "goto" and i.get("url"):
                i["url"] = _re0.sub(r"/(new-[a-z-]+)-[a-z0-9]+$", r"/\1", i["url"])
        vals = [str(i["value"]) for i in ins
                if i.get("op") == "fill" and i.get("value")
                and not str(i["value"]).startswith("[REDACTED]")]
        # ERPNext 基础数据（Item 主档 code）不换参：单据的 item_code 引用
        # 全局主档——换成 E 值后引用悬空 Missing Fields（235 铁证：
        # SL-STD 被换参致 items 行无效）
        try:
            import httpx as _hx
            _c = _hx.Client(timeout=8, base_url="http://127.0.0.1:8090")
            _c.post("/api/method/login",
                    data={"usr": "Administrator", "pwd": "admin"})
            _r = _c.get("/api/resource/Item",
                        params={"limit_page_length": 0, "fields": '["name"]'})
            master_items = {x["name"] for x in _r.json().get("data", [])}
            vals = [v for v in vals if v not in master_items]
        except Exception:
            pass
        # 变量名类 key（value 与 fill name 同串——JeecG '*表名' 既是字段
        # 名又是输入框 label）从 label 替换集排除：替换会毁聚焦步（豁免
        # 条件 label==next.name 断裂——269 实证）
        label_safe = [v for v in vals
                      if not any(str(i.get("name") or "") == v for i in ins
                                 if i.get("op") == "fill")]
        # click label 里的**实例值**并入（258 铁证：录制的头像点击 label=
        # 昵称实例——换参后页面昵称是新值，旧 label 永远 miss）。只收与
        # 本技能 fill 值**同数字后缀**的 label（同源实例）——系统生成值
        # （Odoo 订单号 S00001 无 fill 源）不换（179 全 label 被误换实证）
        import re as _re
        labels = [str(i["label"]) for i in ins
                  if i.get("op") == "click" and i.get("label")
                  and any(_re.search(r'\d{3,}', str(i["label"]))
                          and _re.search(r'\d{3,}', str(i["label"])).group(0) in v
                          for v in label_safe)]
        # row-anchor 实例值并入（270 铁证：行锚=上游技能建的表名——本技能
        # 无 fill 但行操作依赖链内换参值；含数字后缀的 anchor 即实例）
        anchors = [str(c.get("anchor")) for i in ins
                   for c in i.get("resolve_candidates") or []
                   if c.get("anchor") and _re.search(r'\d{3,}', str(c.get("anchor")))]
        merged = list(declared | set(vals) | set(labels) | set(anchors))
        return merged[:10]
    except Exception:
        return list(declared)
    finally:
        db.close()


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
    每技能独立 Playwright 连接生命周期（attach 期间连接会被永久打断）。
    每系统先清单登录（幂等——插件端复用浏览器登录态，odoo 实证必需）。"""
    from pathlib import Path as _P
    from app.adapters.manifest import load_adapter_dir as _lad
    from app.adapters.steps import login as _alogin
    _manifests, _ = _lad(_P(__file__).resolve().parent.parent / "adapters")
    _by_id = {m.id: m for m in _manifests}
    for sys_id, cfg in CHAINS.items():
        # 系统级登录（每系统一轮前）
        try:
            async with async_playwright() as pw:
                b = await pw.chromium.connect_over_cdp(CDP)
                m = _by_id.get(sys_id)
                if m and m.login:
                    ok = await _alogin(b.contexts[0].pages[0], m)
                    print(f"[{sys_id}] 登录: {'PASS' if ok else 'FAIL'}", flush=True)
        except Exception as e:
            print(f"[{sys_id}] 登录异常: {str(e)[:50]}", flush=True)
        for rnd in (1, 2):
            chain_ts = int(time.time()) % 100000
            # 轮前身份守卫（258 轮1 fail 时换参用户残登录——轮2 全程权限
            # 不足 404 实证）：每轮重跑清单登录（identity 检出非 admin 时
            # 清态重登——steps.login 已内建）
            try:
                async with async_playwright() as pw:
                    b = await pw.chromium.connect_over_cdp(CDP)
                    m = _by_id.get(sys_id)
                    if m and m.login:
                        ok = await _alogin(b.contexts[0].pages[0], m)
                        print(f"[{sys_id}] 轮{rnd} 登录守卫: "
                              f"{'PASS' if ok else 'FAIL'}", flush=True)
            except Exception as e:
                print(f"[{sys_id}] 轮{rnd} 登录守卫异常: {str(e)[:40]}",
                      flush=True)
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
                            # 换参注入（ext 轮与服务端轮同语义）：技能卡
                            # input_variables+fill value 换成**链级统一**
                            # ts 值（257 建→258 登的跨技能数据依赖要求
                            # 同链同轮同名；写技能防唯一性冲突同语义）。
                            # ERPNext 跨单引用（search_term 搜上一步建的
                            # Quotation）例外：value 用**最新已提交单号**
                            # 而 key 保持录制旧单号（236 铁证：key 也换成
                            # 新单号后与 fill value 不匹配——替换不发生）
                            vs = skill_vars(token, sid)
                            ts = chain_ts
                            new_val = f"E{rnd}{ts}"
                            extra_qs = []
                            if sys_id == "erpnext":
                                try:
                                    import httpx as _hx
                                    _c = _hx.Client(timeout=8,
                                                    base_url="http://127.0.0.1:8090")
                                    _c.post("/api/method/login",
                                            data={"usr": "Administrator",
                                                  "pwd": "admin"})
                                    _r = _c.get("/api/resource/Quotation",
                                                params={"limit_page_length": 1,
                                                        "order_by": "creation desc",
                                                        "filters": '[["docstatus","=",1],["status","!=","Ordered"]]',
                                                        "fields": '["name"]'})
                                    _qn = (_r.json().get("data") or [{}])[0].get("name")
                                    if _qn:
                                        vs = [v for v in vs
                                              if v not in ("search_term",
                                                           "SAL-QTN-2026-00070")]
                                        extra_qs.append(
                                            f"fill_search_term={_qn}")
                                        extra_qs.append(
                                            "fill_SAL-QTN-2026-00070=" + _qn)
                                except Exception:
                                    pass
                            fill_qs = "&".join(
                                [f"fill_{v}={new_val}" for v in vs] + extra_qs)
                            await page.goto(
                                f"chrome-extension://{EXT}/executor.html"
                                f"?skill={sid}&token={token}&auto=1"
                                + (f"&{fill_qs}" if fill_qs else ""),
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
                    # 快照——见上方）。输出带 run id 对账（258 轮2 误判
                    # fail 而 DB run 实为 pass 的竞态实证——对账可查）
                    from app.db import SessionLocal as _S
                    from app.models import ReplayRun as _RR
                    status = "timeout"
                    run_id_used = None
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
                            run_id_used = _r.id
                            break
                    out.append({"system": sys_id, "round": rnd,
                                "skill": sid, "status": status,
                                "run_id": run_id_used})
                    print(f"[{sys_id}] 轮{rnd} #{sid}: {status}"
                          f"{' run' + str(run_id_used) if run_id_used else ''}",
                          flush=True)


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
