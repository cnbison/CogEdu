"""2-0 (14.2): 账号管理 CLI — v1 无自助注册, 管理员/教师经此开户.

用法:
  python scripts/manage_users.py create <username> <password> <role> \
      [--display-name "张三"] [--learning-student-id stu_001]
  python scripts/manage_users.py disable <username>
  python scripts/manage_users.py enable  <username>
  python scripts/manage_users.py list

role ∈ guardian / student / teacher / admin; 学生账号必须带
--learning-student-id (与 students 表学习记录 1:1)。

禁用立即生效: 该账号全部活跃会话当场撤销 (web/api/auth.py 语义),
下次登录被拒。DB 由 ECOS_DB_PATH 环境变量指定 (默认 web/ecos.db)。
"""
from __future__ import annotations

import argparse
import sys

# 允许 scripts/ 直接跑: 项目根加入 sys.path
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description="CogEdu 账号管理 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create", help="创建账号")
    p_create.add_argument("username")
    p_create.add_argument("password")
    p_create.add_argument("role", choices=["guardian", "student", "teacher", "admin"])
    p_create.add_argument("--display-name", default=None)
    p_create.add_argument("--learning-student-id", default=None,
                          help="学生角色必填: 关联 students 表学习记录")

    for name in ("disable", "enable"):
        p = sub.add_parser(name, help=f"{name} 账号")
        p.add_argument("username")

    sub.add_parser("list", help="列出账号")

    args = parser.parse_args()

    from cogedu.persistence.auth_store import get_auth_store
    from web.api import auth as auth_service

    if args.cmd == "create":
        try:
            user = auth_service.create_user(
                username=args.username,
                password=args.password,
                role=args.role,
                display_name=args.display_name,
                learning_student_id=args.learning_student_id,
            )
        except auth_service.AuthError as e:
            print(f"[fail] {e}", file=sys.stderr)
            return 1
        print(f"[ok] 创建账号 {user['username']} "
              f"(role={user['role']}, user_id={user['user_id']})")
        return 0

    if args.cmd in ("disable", "enable"):
        user = get_auth_store().get_user_by_username(args.username)
        if user is None:
            print(f"[fail] 用户不存在: {args.username}", file=sys.stderr)
            return 1
        auth_service.set_user_disabled(user["user_id"], args.cmd == "disable")
        print(f"[ok] {args.cmd} {args.username} (立即生效)")
        return 0

    if args.cmd == "list":
        for u in get_auth_store().list_users():
            status = "disabled" if u.get("disabled_at") else "active"
            link = f" -> {u['learning_student_id']}" if u.get("learning_student_id") else ""
            print(f"{u['username']:<24} {u['role']:<10} {status:<9}{link}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
