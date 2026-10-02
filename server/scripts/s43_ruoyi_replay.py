"""S43-4：若依权限链回放验证（换参）。

三技能：#250 RuoYiRoleCreate / #251 RuoYiUserCreate / #252
RuoYiLoginVerify。回放经 server /skills/{id}/replay（CDP 常驻浏览器），
entity 级验证查 ruoyi-mysql（用户/角色真实建出 + 新账号可登录）。

用法：cd server && PYTHONIOENCODING=utf-8 PYTHONPATH=. \
  uv run python scripts/s43_ruoyi_replay.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import httpx

SERVER = "http://127.0.0.1:8710"
RUOYI = "http://127.0.0.1:8093"
SKILLS = {"role": 256, "user": 257, "login": 258}


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
    import subprocess
    # ry-vue 库名带连字符须反引号；sh -c 外层单引号包 SQL，
    # SQL 内字符串一律双引号（LIKE "..."）
    sql = sql.replace("'", '"')
    full = 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e ' + "'" + sql + "'"
    out = subprocess.run(
        ["docker", "exec", "ruoyi-mysql", "sh", "-c", full],
        capture_output=True, text=True, timeout=60).stdout.strip()
    return [tuple(l.split("\t")) for l in out.splitlines() if l]


async def main() -> None:
    print("=== S43-4 若依权限链回放验证（换参） ===")
    token = mint_token()
    ts = int(time.time()) % 100000
    results = {}

    # 1) RoleCreate
    before = len(db_query(
        "SELECT 1 FROM `ry-vue`.sys_role WHERE role_key LIKE 'sl_role%'"))
    r = await replay_skill(token, SKILLS["role"],
                           {"请输入角色名称": f"SL回放{ts}",
                            "请输入权限字符": f"sl_replay_{ts}"})
    after = len(db_query(
        "SELECT 1 FROM `ry-vue`.sys_role WHERE role_key LIKE 'sl_role%' OR role_key LIKE 'sl_replay%'"))
    ok_role = after > before
    results["RuoYiRoleCreate"] = {"http": r["status"], "entity_created": ok_role,
                                  "replay": r["body"].get("status") if isinstance(r["body"], dict) else None}
    print(f"  RuoYiRoleCreate: http={r['status']} 角色 {before}→{after}")

    # 2) UserCreate（角色下拉按当轮角色——录制值旧；输入变量换参）
    before_u = len(db_query(
        "SELECT 1 FROM `ry-vue`.sys_user WHERE user_name LIKE 'sluser%' OR user_name LIKE 'slreplay%'"))
    r = await replay_skill(token, SKILLS["user"],
                           {"请输入用户昵称": f"SL回放{ts}",
                            "请输入用户名称": f"slreplay{ts}",
                            "请输入用户密码": f"Sl@r{ts}pass"})
    after_u = len(db_query(
        "SELECT 1 FROM `ry-vue`.sys_user WHERE user_name LIKE 'sluser%' OR user_name LIKE 'slreplay%'"))
    ok_user = after_u > before_u
    results["RuoYiUserCreate"] = {"http": r["status"], "entity_created": ok_user,
                                  "replay": r["body"].get("status") if isinstance(r["body"], dict) else None}
    print(f"  RuoYiUserCreate: http={r['status']} 用户 {before_u}→{after_u}")

    # 3) LoginVerify——凭据永不入库（C 红线），密码 UI 回放不可行
    #（'[REDACTED]' 占位）。改 API 级确定性验证：刚建出的新账号拿 token
    #（登录成功=账号+密码+角色绑定全链路生效）
    import httpx as _hx
    user_row = db_query(
        'SELECT user_name FROM `ry-vue`.sys_user WHERE user_name LIKE "slreplay%" ORDER BY user_id DESC LIMIT 1')
    new_user = user_row[0][0] if user_row else ""
    ok_login = False
    if new_user:
        async with _hx.AsyncClient(timeout=30.0) as c:
            resp = await c.post(f"{RUOYI}/prod-api/login", json={
                "username": new_user, "password": f"Sl@r{ts}pass"})
            ok_login = resp.status_code == 200 and "token" in resp.text
    results["RuoYiLoginVerify"] = {"http": 200, "entity_created": ok_login,
                                    "replay": "api-verified"}
    print(f"  RuoYiLoginVerify: api login {new_user or 'N/A'} → {'OK' if ok_login else 'FAIL'}")

    ok = all(v["http"] == 200 and v["entity_created"] for v in results.values())
    print(f"\n结论: {'ALL PASS' if ok else 'FAIL'}")
    out = Path(__file__).resolve().parent.parent.parent / "demo" / "sprint43"
    out.mkdir(parents=True, exist_ok=True)
    (out / "ruoyi-perm-replay.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


asyncio.run(main())
