"""2-0-2 (Phase 2, 14.2): 认证与会话服务 + FastAPI 鉴权 dependencies.

CogEdu 账号体系的服务层 (此前仓库无任何身份体系, 2-A 权限模型的地基):
  - 凭证: bcrypt 哈希 (依赖 bcrypt, 纯最小依赖); 不存明文/可逆形式
  - 会话: 服务端存储 (auth_store.sessions 表), token 明文只回给客户端,
    落库存 SHA-256 哈希; 刻意不用 JWT — "撤销立即生效" (2-A 验收点)
    要求会话可即时失效, 无状态 token 做不到 (方案文档 14.2 2-0-2)
  - 账号创建: v1 无自助注册 (K12 场景由管理员/教师开户),
    CLI 见 scripts/manage_users.py

角色-路由矩阵 (2-0-3, 各 router 的 dependencies 接线):
  - teacher 路由        → teacher/admin
  - parent 路由         → guardian/teacher/admin (per-student 关系校验
                          在 2-A guardian_learner_link 落地后补上, 本
                          Phase 只做到"已认证的家长角色"粒度)
  - student 数据路由    → 学生本人 (learning_student_id 匹配) / teacher/admin
  - 其余 /api/*         → 已认证即可 (static 页面公开, JS 层 401 跳登录)

patch 面约定 (测试):
  - _resolve_request_user — conftest auth bypass 的唯一 patch 点
    (Depends 在 router 装配时捕获函数引用, 但函数体每次经模块全局
    查找调用本函数, monkeypatch 本模块属性即可生效)
  - tests 走真实鉴权时用 conftest 的 real_auth marker + make_auth_headers
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from fastapi import HTTPException, Request

from cogedu.persistence.auth_store import get_auth_store, hash_token

_log = logging.getLogger(__name__)

# ─── 常量 ────────────────────────────────────────────────────────────────────

ROLES = ("guardian", "student", "teacher", "admin")

# 管理类角色: 可访问任意学生的数据 (教师看全班, 家长只能看自己的孩子 —
# 后者的 per-student 校验在 2-A 落地, 见文件头矩阵注记)
STAFF_ROLES = ("teacher", "admin")

MIN_PASSWORD_LEN = 8
# bcrypt 只取前 72 字节 — 超长密码直接拒绝而不是静默截断 (截断会造成
# "超长部分不参与校验"的隐性弱化, 明确报错更诚实)
MAX_PASSWORD_BYTES = 72
USERNAME_MIN, USERNAME_MAX = 3, 64

DEFAULT_SESSION_TTL_HOURS = 24 * 7


class AuthError(ValueError):
    """账号业务规则错误 (用户名/密码/角色不合法等, 路由层转 400/409)."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _session_ttl_hours() -> float:
    raw = os.environ.get("COGEDU_SESSION_TTL_HOURS", "")
    try:
        return float(raw) if raw else DEFAULT_SESSION_TTL_HOURS
    except ValueError:
        _log.warning(
            "COGEDU_SESSION_TTL_HOURS 非数字 (%r), 用默认 %dh",
            raw, DEFAULT_SESSION_TTL_HOURS,
        )
        return float(DEFAULT_SESSION_TTL_HOURS)


# ─── 密码 ────────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    """bcrypt 哈希 (salt 内嵌在返回串里, 校验时 bcrypt 自动取)."""
    _validate_password(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码. 哈希格式坏 → False + warning (不抛, 登录失败即可)."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        _log.warning("verify_password: password_hash 格式异常, 按校验失败处理")
        return False


# ─── 账号 ────────────────────────────────────────────────────────────────────


def _validate_password(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LEN:
        raise AuthError(f"密码长度至少 {MIN_PASSWORD_LEN} 位")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise AuthError("密码过长 (bcrypt 上限 72 字节)")


def create_user(
    username: str,
    password: str,
    role: str,
    display_name: str | None = None,
    learning_student_id: str | None = None,
) -> dict[str, Any]:
    """创建账号 (管理员/教师开户 + 测试用). 规则违反 → AuthError.

    学生角色必须带 learning_student_id (与 students 表学习记录 1:1);
    不校验 students 行是否已存在 — 学习记录是懒创建的, 账号可先建。
    """
    username = (username or "").strip()
    if not (USERNAME_MIN <= len(username) <= USERNAME_MAX):
        raise AuthError(f"用户名长度需在 {USERNAME_MIN}-{USERNAME_MAX} 之间")
    if role not in ROLES:
        raise AuthError(f"未知角色: {role!r} (可选: {', '.join(ROLES)})")
    if role == "student" and not (learning_student_id or "").strip():
        raise AuthError("学生账号必须关联 learning_student_id")
    _validate_password(password)

    store = get_auth_store()
    if store.get_user_by_username(username) is not None:
        raise AuthError(f"用户名已存在: {username}")
    user_id = f"u_{secrets.token_hex(8)}"
    store.create_user(
        user_id=user_id,
        username=username,
        password_hash=hash_password(password),
        role=role,
        display_name=(display_name or "").strip() or None,
        learning_student_id=(learning_student_id or "").strip() or None,
        created_at=_now_iso(),
    )
    created = store.get_user_by_id(user_id)
    if created is None:  # 防御性自检: 写后读不到 = 存储层异常, 必须显式失败
        raise RuntimeError(f"create_user 写后读失败 (user_id={user_id})")
    return created


def set_user_disabled(user_id: str, disabled: bool) -> int:
    """禁用/解禁账号; 禁用时撤销全部活跃会话 (立即生效)."""
    store = get_auth_store()
    now = _now_iso()
    changed = store.set_disabled(user_id, now if disabled else None)
    if disabled and changed:
        store.revoke_user_sessions(user_id, now)
    return changed


# ─── 登录 / 会话 ─────────────────────────────────────────────────────────────


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    """用户名+密码登录校验. 成功返回 user 行, 失败返回 None (不区分
    用户不存在/密码错 — 不给枚举用户名的信号). 禁用账号按失败处理."""
    user = get_auth_store().get_user_by_username((username or "").strip())
    if user is None:
        return None
    if user.get("disabled_at"):
        return None
    if not verify_password(password or "", user["password_hash"]):
        return None
    return user


def issue_session(user_id: str) -> tuple[str, str]:
    """签发会话: 返回 (明文 token, expires_at ISO). 服务端只存哈希."""
    store = get_auth_store()
    now = datetime.now(UTC)
    expires = now + timedelta(hours=_session_ttl_hours())
    # 登录时顺带清理已过期会话行 (失败只 warning, 不影响登录)
    try:
        store.purge_expired_sessions(now.isoformat())
    except Exception:
        _log.warning("purge_expired_sessions 失败, 不影响登录", exc_info=True)
    token = secrets.token_urlsafe(32)
    store.create_session(
        token_hash=hash_token(token),
        user_id=user_id,
        created_at=now.isoformat(),
        expires_at=expires.isoformat(),
    )
    return token, expires.isoformat()


def resolve_session(token: str) -> dict[str, Any] | None:
    """token → 当前用户 (过期/撤销/用户禁用 → None). 每请求现查, 无缓存 —
    撤销立即生效语义的物理实现."""
    if not token:
        return None
    store = get_auth_store()
    session = store.get_session(hash_token(token))
    if session is None or session.get("revoked_at"):
        return None
    expires_at = session.get("expires_at") or ""
    try:
        if datetime.fromisoformat(expires_at) < datetime.now(UTC):
            return None
    except ValueError:
        _log.warning("resolve_session: expires_at 非法 (%r), 按无效处理", expires_at)
        return None
    user = store.get_user_by_id(session["user_id"])
    if user is None or user.get("disabled_at"):
        return None
    return user


def revoke_token(token: str) -> int:
    """撤销单个会话 (登出). token 无效/已撤销 → 0 (幂等)."""
    return get_auth_store().revoke_session(hash_token(token), _now_iso())


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    """user 行 → 可回给前端的形状 (绝不带 password_hash)."""
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "role": user["role"],
        "display_name": user.get("display_name"),
        "learning_student_id": user.get("learning_student_id"),
    }


# ─── FastAPI dependencies (各 router 的 dependencies 接线用) ─────────────────


def _resolve_request_user(request: Request) -> dict[str, Any] | None:
    """从 Authorization: Bearer <token> 解析当前用户; 无 token/无效 → None.

    ★ conftest auth bypass 的唯一 patch 点 (见模块 docstring patch 面约定):
    monkeypatch web.api.auth._resolve_request_user 即可让全部存量契约测试
    免登录跑; 需要真实鉴权语义的测试用 real_auth marker 退出 bypass。
    """
    header = request.headers.get("Authorization") or ""
    if not header.startswith("Bearer "):
        return None
    return resolve_session(header[len("Bearer "):].strip())


def _request_user_or_401(request: Request) -> dict[str, Any]:
    user = _resolve_request_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="未登录或会话已失效")
    return user


def require_authenticated(request: Request) -> dict[str, Any]:
    """已认证 (任意角色)."""
    return _request_user_or_401(request)


def require_roles(*roles: str):
    """限定角色列表 (如 require_roles("teacher", "admin"))."""

    def _dep(request: Request) -> dict[str, Any]:
        user = _request_user_or_401(request)
        if user["role"] not in roles:
            raise HTTPException(
                status_code=403, detail=f"需要角色 {'/'.join(roles)}"
            )
        return user

    return _dep


async def require_student_access(request: Request, student_id: str | None = None) -> dict[str, Any]:
    """学生数据访问: 学生本人 (learning_student_id 匹配) / staff 任意.

    student_id 优先取路径参数 (FastAPI 对同名 path param 自动注入),
    路径没有时从 JSON body 取 (覆盖 /api/answer、/api/judge 这类
    student_id 在请求体里的端点; body 由 FastAPI 缓存, 不影响端点解析)。
    """
    user = _request_user_or_401(request)
    if user["role"] in STAFF_ROLES:
        return user
    target = student_id
    if target is None:
        try:
            body = await request.body()
            import json as _json

            target = (_json.loads(body) or {}).get("student_id") if body else None
        except Exception:
            target = None
    if (
        user["role"] == "student"
        and user.get("learning_student_id")
        and user["learning_student_id"] == target
    ):
        return user
    raise HTTPException(status_code=403, detail="无权访问该学生的数据")
