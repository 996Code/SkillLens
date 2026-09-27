"""S21 块 S：建号引导脚本（空库无用户时无法登录，不做默认弱口令）。

用法：uv run python -m app.create_user <username> <password> <role>
role 三选一：admin | reviewer | viewer。重名退出码 1。
"""
import sys

from app.auth import create_user
from app.db import SessionLocal


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[3] not in ("admin", "reviewer", "viewer"):
        print("用法: python -m app.create_user <username> <password> <admin|reviewer|viewer>")
        return 2
    username, password, role = sys.argv[1], sys.argv[2], sys.argv[3]
    db = SessionLocal()
    try:
        user = create_user(db, username, password, role)
        uid, uname, urole = user.id, user.username, user.role
    except ValueError as exc:
        print(f"失败: {exc}")
        return 1
    finally:
        db.close()
    print(f"已创建用户 {uname}（role={urole}, id={uid}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
