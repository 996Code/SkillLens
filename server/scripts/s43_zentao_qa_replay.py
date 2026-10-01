"""S43-4：禅道 QA 链回放验证（按序：需求→用例→测试单→执行）。"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import httpx

SERVER = "http://127.0.0.1:8710"
SKILL_IDS = [157, 158, 159, 170]


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
            overrides = {v: f"回放{skill_id}u{ts}" for v in vars_}
            print(f"#{skill_id} {card['name']} vars={vars_} -> ", end="", flush=True)
            r = await c.post(f"{SERVER}/api/v1/skills/{skill_id}/replay",
                             json={"overrides": overrides, "confirm_side_effect": True})
            if r.status_code == 200:
                d = r.json()
                print(f"{d['status']} ({d['mode']})")
                results.append((skill_id, card["name"], d["status"]))
            else:
                print(f"http {r.status_code}: {r.text[:100]}")
                results.append((skill_id, card["name"], f"http{r.status_code}"))
    print("\n=== 禅道 QA 链回放结果 ===")
    for sid, name, st in results:
        print(f"  #{sid} {name}: {st}")


asyncio.run(main())
