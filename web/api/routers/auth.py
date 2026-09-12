"""2-0-2 (Phase 2, 14.2): 认证端点 — login / logout / me.

v1 无自助注册 (K12 场景由管理员/教师开户, CLI 见 scripts/manage_users.py);
登录失败统一 401 不区分"用户不存在/密码错" (不给枚举用户名的信号)。

token 传递: Authorization: Bearer <token> (前端 localStorage 保存,
authFetch 统一带上; 不用 HttpOnly cookie — 避免 CSRF 面和额外的
SameSite/跨端口复杂度, 灰度阶段先取简单可靠的一边, 见方案文档 14.2)。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from web.api import auth as auth_service
from web.api.auth import require_authenticated

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
def api_login(req: LoginRequest):
    """登录: 校验凭证 → 签发服务端会话 → 返回 Bearer token."""
    try:
        user = auth_service.authenticate(req.username, req.password)
        if user is None:
            # 统一 401: 不区分用户不存在/密码错/账号禁用
            return JSONResponse({"error": "用户名或密码错误"}, status_code=401)
        token, expires_at = auth_service.issue_session(user["user_id"])
        return {
            "token": token,
            "expires_at": expires_at,
            "user": auth_service.public_user(user),
        }
    except Exception:
        _log.warning("/api/auth/login 失败", exc_info=True)
        return JSONResponse({"error": "登录失败"}, status_code=500)


@router.post("/logout")
def api_logout(request: Request, user: dict = Depends(require_authenticated)):  # noqa: B008 (FastAPI 惯用)
    """登出: 撤销当前会话 (服务端删会话, 撤销立即生效)."""
    try:
        header = request.headers.get("Authorization") or ""
        token = header[len("Bearer "):].strip()
        auth_service.revoke_token(token)
        return {"ok": True}
    except Exception:
        _log.warning("/api/auth/logout 失败 (user=%s)", user.get("user_id"), exc_info=True)
        return JSONResponse({"error": "登出失败"}, status_code=500)


@router.get("/me")
def api_me(user: dict = Depends(require_authenticated)):  # noqa: B008 (FastAPI 惯用)
    """当前登录用户信息 (前端守卫用: 401 → 跳登录页)."""
    return {"user": auth_service.public_user(user)}
