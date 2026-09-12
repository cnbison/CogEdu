"""2-A-3 (Phase 2, 14.3): 授权流程端点 — 家长申请/学生确认/双方撤销.

角色侧:
  /api/guardian/links        家长: 发起申请 / 查看我的申请与授权 / 撤销
  /api/student/guardian-links  学生: 待确认列表 / 确认 / 拒绝 / 撤销
                             (低龄无学生账号在用场景: admin 可代确认/拒绝)

错误语义: 业务规则违反 (GuardianLinkError) → 400; 不存在的记录 → 404;
    重复申请 → 409; 其余 500 + warning 留痕 (对齐仓库错误分级约定)。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from web.api import guardian as guardian_service
from web.api.auth import require_roles
from web.api.guardian import GuardianLinkError

_log = logging.getLogger(__name__)

router = APIRouter(tags=["guardian-links"])


def _error_response(e: GuardianLinkError):
    """业务错误 → HTTP: 记录不存在 404, 重复申请 409, 其余 400."""
    msg = str(e)
    if "不存在" in msg:
        return JSONResponse({"error": msg}, status_code=404)
    if "已存在进行中" in msg or "重复申请" in msg:
        return JSONResponse({"error": msg}, status_code=409)
    return JSONResponse({"error": msg}, status_code=400)


# ─── Pydantic 请求/响应模型 ──────────────────────────────────────────────────


class LinkRequest(BaseModel):
    """POST /api/guardian/links 请求体."""

    learner_username: str
    permissions: list[str]


class LinkActionResponse(BaseModel):
    ok: bool
    link: dict


# ─── 家长侧 ──────────────────────────────────────────────────────────────────


@router.post("/api/guardian/links", response_model=LinkActionResponse)
def api_request_link(
    req: LinkRequest,
    user: dict = Depends(require_roles("guardian")),  # noqa: B008 (FastAPI 惯用)
):
    """家长发起绑定申请 (pending; 学生确认前不生效)."""
    try:
        link = guardian_service.request_link(user, req.learner_username, req.permissions)
        return {"ok": True, "link": guardian_service.decorate_links([link])[0]}
    except GuardianLinkError as e:
        return _error_response(e)
    except Exception:
        _log.warning("/api/guardian/links 失败 (guardian=%s)", user.get("user_id"), exc_info=True)
        return JSONResponse({"error": "申请失败"}, status_code=500)


@router.get("/api/guardian/links")
def api_list_my_links(
    user: dict = Depends(require_roles("guardian")),  # noqa: B008 (FastAPI 惯用)
):
    """我的申请与授权 (含全部状态历史)."""
    try:
        links = guardian_service.list_links_for_guardian(user["user_id"])
        return {"links": guardian_service.decorate_links(links)}
    except Exception:
        _log.warning("list guardian links 失败 (guardian=%s)", user.get("user_id"), exc_info=True)
        return JSONResponse({"error": "查询失败"}, status_code=500)


@router.delete("/api/guardian/links/{link_id}", response_model=LinkActionResponse)
def api_guardian_cancel_or_revoke(
    link_id: str,
    user: dict = Depends(require_roles("guardian")),  # noqa: B008 (FastAPI 惯用)
):
    """家长侧: 撤回 pending 申请 / 撤销 active 授权 (立即生效)."""
    try:
        link = guardian_service._get_link_or_raise(link_id)  # 404 语义
        if link["guardian_user_id"] != user["user_id"]:
            return JSONResponse({"error": "该授权记录不属于当前家长"}, status_code=403)
        if link["status"] == "pending":
            updated = guardian_service.reject_link(link_id, user)  # 撤回 = rejected 留痕
        else:
            updated = guardian_service.revoke_link(link_id, user)
        return {"ok": True, "link": guardian_service.decorate_links([updated])[0]}
    except GuardianLinkError as e:
        return _error_response(e)
    except Exception:
        _log.warning("guardian cancel/revoke 失败 (link=%s)", link_id, exc_info=True)
        return JSONResponse({"error": "操作失败"}, status_code=500)


# ─── 学生侧 ──────────────────────────────────────────────────────────────────


@router.get("/api/student/guardian-links")
def api_learner_links(
    user: dict = Depends(require_roles("student", "admin")),  # noqa: B008 (FastAPI 惯用)
):
    """与我的账号相关的申请/授权 (学生端确认页数据源)."""
    try:
        links = guardian_service.list_links_for_learner(user["user_id"])
        return {"links": guardian_service.decorate_links(links)}
    except Exception:
        _log.warning("list learner links 失败 (user=%s)", user.get("user_id"), exc_info=True)
        return JSONResponse({"error": "查询失败"}, status_code=500)


@router.post("/api/student/guardian-links/{link_id}/confirm", response_model=LinkActionResponse)
def api_confirm_link(
    link_id: str,
    user: dict = Depends(require_roles("student", "admin")),  # noqa: B008 (FastAPI 惯用)
):
    """学生确认绑定申请 (admin 可代确认, 低龄场景). 生效立即可见数据."""
    try:
        updated = guardian_service.confirm_link(link_id, user)
        return {"ok": True, "link": guardian_service.decorate_links([updated])[0]}
    except GuardianLinkError as e:
        return _error_response(e)
    except Exception:
        _log.warning("confirm link 失败 (link=%s)", link_id, exc_info=True)
        return JSONResponse({"error": "操作失败"}, status_code=500)


@router.post("/api/student/guardian-links/{link_id}/reject", response_model=LinkActionResponse)
def api_reject_link(
    link_id: str,
    user: dict = Depends(require_roles("student", "admin")),  # noqa: B008 (FastAPI 惯用)
):
    """学生拒绝绑定申请 (admin 可代拒绝)."""
    try:
        updated = guardian_service.reject_link(link_id, user)
        return {"ok": True, "link": guardian_service.decorate_links([updated])[0]}
    except GuardianLinkError as e:
        return _error_response(e)
    except Exception:
        _log.warning("reject link 失败 (link=%s)", link_id, exc_info=True)
        return JSONResponse({"error": "操作失败"}, status_code=500)


@router.delete("/api/student/guardian-links/{link_id}", response_model=LinkActionResponse)
def api_learner_revoke(
    link_id: str,
    user: dict = Depends(require_roles("student", "admin")),  # noqa: B008 (FastAPI 惯用)
):
    """学生撤销授权 (立即生效 — 家长端下一请求即 403)."""
    try:
        updated = guardian_service.revoke_link(link_id, user)
        return {"ok": True, "link": guardian_service.decorate_links([updated])[0]}
    except GuardianLinkError as e:
        return _error_response(e)
    except Exception:
        _log.warning("learner revoke 失败 (link=%s)", link_id, exc_info=True)
        return JSONResponse({"error": "操作失败"}, status_code=500)
