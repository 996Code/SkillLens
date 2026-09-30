"""S42：若依技能回放验证——学习到的 CRUD 技能在真实系统上换参重放。

对 s42_ruoyi_record.py 学到的技能逐个回放（换数据），验证：
- 定位泛化（Element Plus 组件在回放引擎下可定位）
- 换参回放（input_variables 注入新值）
- 断言判定（api_status/ui_text）
- 副作用流程的 C1 门控（DeletePost 默认 shadow）

用法：cd server && uv run python ../scripts/s42_ruoyi_replay.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import httpx

SERVER = "http://127.0.0.1:8710"
SKILL_IDS = [58, 59, 60]  # 状态机链：建 Bug → 解决 → 关闭


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


async def main() -> None:
    token = mint_token()
    results = []
    async with httpx.AsyncClient(timeout=300.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        for skill_id in SKILL_IDS:
            card = (await c.get(f"{SERVER}/api/v1/skills/{skill_id}/card")).json()
            vars_ = [v["name"] for v in card.get("input_variables", [])]
            # 换参：按字段类型生成合法新值（与录制值不同）——
            # 非法值（如中文手机号）会被表单校验/查重拦截
            ts = int(time.time()) % 100000
            def _gen(v: str) -> str:
                low = v.lower()
                if "phone" in low or "手机" in v:
                    return f"138{ts:08d}"
                if "username" in low or "账号" in v or "user" in low:
                    return f"sl{skill_id}u{ts}"
                if "email" in low or "邮箱" in v:
                    return f"sl{ts}@test.com"
                return f"回放{skill_id}-{ts}-{v[:6]}"
            overrides = {v: _gen(v) for v in vars_}
            print(f"#{skill_id} {card['name']} vars={vars_} -> ", end="", flush=True)
            r = await c.post(f"{SERVER}/api/v1/skills/{skill_id}/replay",
                             json={"overrides": overrides, "confirm_side_effect": True})
            if r.status_code == 200:
                d = r.json()
                print(f"{d['status']} ({d['mode']})")
                results.append({"skill_id": skill_id, "name": card["name"],
                                "status": d["status"], "mode": d["mode"],
                                "attribution": d.get("attribution")})
            else:
                print(f"http {r.status_code}: {r.text[:120]}")
                results.append({"skill_id": skill_id, "name": card["name"],
                                "status": f"http{r.status_code}", "mode": "-",
                                "attribution": r.text[:200]})

    print("\n=== 若依回放结果 ===")
    for r in results:
        print(f"  #{r['skill_id']} {r['name']}: {r['status']} ({r['mode']})")
    out = Path(__file__).resolve().parent.parent / "demo" / "sprint42"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ruoyi-replay.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("结果已存 demo/sprint42/ruoyi-replay.json")


asyncio.run(main())
