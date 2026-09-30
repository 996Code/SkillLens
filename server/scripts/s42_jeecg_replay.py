"""S42-12：JeecgBoot 字典闭环回放验证（按序：建字典→字典数据→查询）。"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import httpx

SERVER = "http://127.0.0.1:8710"
SKILL_IDS = [135, 136, 137]  # S42-12 跨标签页流量过滤后的最终采集


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
            ts = int(time.time()) % 100000
            def _gen(v: str) -> str:
                # 字典编码等 code 类字段须 ASCII（Jeecg 编码校验拒绝中文）
                if "code" in v.lower():
                    return f"rp{skill_id}x{ts}"
                return f"回放{skill_id}u{ts}"
            overrides = {v: _gen(v) for v in vars_}
            print(f"#{skill_id} {card['name']} vars={vars_} -> ", end="", flush=True)
            r = await c.post(f"{SERVER}/api/v1/skills/{skill_id}/replay",
                             json={"overrides": overrides, "confirm_side_effect": True})
            if r.status_code == 200:
                d = r.json()
                print(f"{d['status']} ({d['mode']})")
                results.append({"skill_id": skill_id, "name": card["name"], "status": d["status"]})
            else:
                print(f"http {r.status_code}: {r.text[:120]}")
                results.append({"skill_id": skill_id, "name": card["name"],
                                "status": f"http{r.status_code}"})
    print("\n=== Jeecg 字典回放结果 ===")
    for r in results:
        print(f"  #{r['skill_id']} {r['name']}: {r['status']}")


asyncio.run(main())
