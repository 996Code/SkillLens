"""S43-4：JeecG 在线表单链回放验证（换参）。

三技能：#260 OnlineFormCreate / #261 OnlineFormSync / #262
OnlineFormFill。entity 级验证查 onl_cgform_head + 物理表（SHOW TABLES）
+ 功能测试数据行（POST 写证据由 run 断言覆盖）。

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/s43_jeecg_replay2.py
"""
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import httpx

SERVER = "http://127.0.0.1:8710"
SKILLS = {"create": 269, "sync": 270, "fill": 271}


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


async def replay_skill(token: str, skill_id: int, overrides: dict) -> dict:
    async with httpx.AsyncClient(timeout=600.0) as c:
        c.headers["Authorization"] = f"Bearer {token}"
        resp = await c.post(f"{SERVER}/api/v1/skills/{skill_id}/replay",
                            json={"overrides": overrides,
                                  "confirm_side_effect": True})
        body = None
        try:
            body = resp.json()
        except Exception:
            body = resp.text[:200]
        return {"status": resp.status_code, "body": body}


def db_query(sql: str) -> list[tuple]:
    sql = sql.replace("'", '"')
    full = 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e ' + "'" + sql + "'"
    out = subprocess.run(
        ["docker", "exec", "jeecg-boot-mysql", "sh", "-c", full],
        capture_output=True, text=True, timeout=60).stdout.strip()
    return [tuple(l.split("\t")) for l in out.splitlines() if l]


async def main() -> None:
    print("=== S43-4 JeecG 在线表单链回放验证（换参） ===")
    token = mint_token()
    ts = int(time.time()) % 100000
    form = f"sl_rp{ts}"
    results = {}

    # 1) Create
    before = len(db_query(
        'SELECT 1 FROM `jeecg-boot`.onl_cgform_head WHERE table_name LIKE "sl_%"'))
    r = await replay_skill(token, SKILLS["create"],
                           {"*表名": form, "*表描述": f"SL回放表单{ts}"})
    after = len(db_query(
        'SELECT 1 FROM `jeecg-boot`.onl_cgform_head WHERE table_name LIKE "sl_%"'))
    results["OnlineFormCreate"] = {"http": r["status"], "entity_created": after > before,
                                   "replay": r["body"].get("status") if isinstance(r["body"], dict) else None}
    print(f"  OnlineFormCreate: http={r['status']} 表单 {before}→{after}")

    # 2) Sync（对新建表——行按表名过滤；S43-5：换参值注入 row-anchor，
    #    行点击步的 labels 是录制时旧表行文本，跨轮必然陈旧）
    phys = db_query(
        f'SHOW TABLES FROM `jeecg-boot` LIKE "{form}"')
    r = await replay_skill(token, SKILLS["sync"],
                           {"*表名": form, "*表描述": f"SL回放表单{ts}"})
    phys2 = db_query(
        f'SHOW TABLES FROM `jeecg-boot` LIKE "{form}"')
    synced = len(phys2) > 0
    results["OnlineFormSync"] = {"http": r["status"], "entity_created": synced,
                                 "replay": r["body"].get("status") if isinstance(r["body"], dict) else None}
    print(f"  OnlineFormSync: http={r['status']} 物理表 {len(phys)}→{len(phys2)}")

    # 3) Fill（功能测试填单——POST 写证据；行锚同样注入新表名）
    r = await replay_skill(token, SKILLS["fill"],
                           {"*表名": form, "*表描述": f"SL回放表单{ts}"})
    body = r["body"] if isinstance(r["body"], dict) else {}
    results["OnlineFormFill"] = {"http": r["status"], "entity_created": body.get("status") in ("pass", "flaky-pass"),
                                 "replay": body.get("status")}
    print(f"  OnlineFormFill: http={r['status']} status={body.get('status')}")

    ok = all(v["http"] == 200 and v["entity_created"] for v in results.values())
    print(f"\n结论: {'ALL PASS' if ok else 'FAIL'}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint43"
    out.mkdir(parents=True, exist_ok=True)
    (out / "jeecg-form-replay.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
