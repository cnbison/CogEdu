"""2-A (Phase 2, 14.3): 家长-学生授权关系服务 — guardian_learner_link.

显式授权记录（不是隐含的角色继承）：谁（家长账号）对谁（学生账号）
有什么权限、什么时候建立的、能不能撤销。借鉴 DeepTutor guardians.py
的三个核心防御思路，落地方式按 CogEdu 约定重写：
  1. 撤销留痕（revoked_by / revocation_reason）
  2. guardian_can_access **每次现查双方当前角色**——角色变更后旧授权
     自动失效（防"前学生变家长"类越权路径），不依赖授权时点快照
  3. 单一校验入口——所有家长端取数必经 guardian_can_access，不做
     任何缓存（"撤销立即生效"的物理实现；家长端 QPS 低，现查无压力）

授权建立流程（2-A-3）：家长发起申请 → 学生本人确认才生效
（pending → active）；低龄无账号在用场景由 admin 代确认。流程状态
pending → active / rejected；active → revoked（学生或家长均可撤销）。

v1 无自助注册配套：学生账号由管理员开户（scripts/manage_users.py），
家长按学生账号的 username 发起申请。
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime
from typing import Any

from cogedu.persistence.auth_store import get_auth_store

_log = logging.getLogger(__name__)

# ─── 权限项 (2-A-2, DeepTutor 四项按 K12 教学场景调整) ───────────────────────

GUARDIAN_PERMISSIONS = (
    "view_progress",      # 查看学习进度/Belief 概览 (v1 必做)
    "view_evidence",      # 查看证据链细节 (完整版依赖 Phase 4)
    "download_report",    # 下载导出的学习报告 (2-C 用)
    "receive_alerts",     # 接收异常预警通知 (v1 可选, 表结构先留)
    "assign_materials",   # 分配学习材料 (不进 v1, 等 Phase 5 知识库, 留位)
)

LINK_STATUS = ("pending", "active", "rejected", "revoked")


class GuardianLinkError(ValueError):
    """授权关系业务规则错误 (路由层转 400/409)."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _validate_permissions(permissions: list[str]) -> list[str]:
    """权限项白名单过滤 + 去重; 空集拒绝 (对齐 DeepTutor: 至少一项)."""
    if not isinstance(permissions, list):
        raise GuardianLinkError("permissions 需为字符串数组")
    allowed = sorted({str(p) for p in permissions if p in GUARDIAN_PERMISSIONS})
    if not allowed:
        raise GuardianLinkError(
            f"至少需要一项合法权限 (可选: {', '.join(GUARDIAN_PERMISSIONS)})"
        )
    return allowed


def request_link(
    guardian_user: dict[str, Any],
    learner_username: str,
    permissions: list[str],
) -> dict[str, Any]:
    """家长发起绑定申请 → pending 记录 (学生确认前不生效).

    规则 (照搬 DeepTutor _require_ordinary_user 防御 + 自绑禁止):
    发起方须 guardian 角色; 对方须存在、student 角色、未禁用;
    不能绑定自己; 同对已有 pending/active 时拒绝 (可先撤销再重申)。
    """
    if guardian_user.get("role") != "guardian":
        raise GuardianLinkError("只有家长账号可以发起绑定申请")
    allowed = _validate_permissions(permissions)

    store = get_auth_store()
    learner = store.get_user_by_username((learner_username or "").strip())
    if learner is None:
        raise GuardianLinkError("学生账号不存在")
    if learner["user_id"] == guardian_user["user_id"]:
        raise GuardianLinkError("不能绑定自己的账号")
    if learner.get("role") != "student":
        raise GuardianLinkError("对方不是学生账号")
    if learner.get("disabled_at"):
        raise GuardianLinkError("对方账号已禁用")

    existing = store.find_active_or_pending_link(
        guardian_user["user_id"], learner["user_id"]
    )
    if existing is not None:
        raise GuardianLinkError(
            f"已存在进行中的授权关系 (状态: {existing['status']}), 请勿重复申请"
        )

    link_id = f"gl_{secrets.token_hex(8)}"
    store.create_link(
        link_id=link_id,
        guardian_user_id=guardian_user["user_id"],
        learner_user_id=learner["user_id"],
        permissions_json=json.dumps(allowed),
        requested_at=_now_iso(),
    )
    created = store.get_link(link_id)
    if created is None:  # 防御性自检: 写后读不到 = 存储层异常
        raise RuntimeError(f"request_link 写后读失败 (link_id={link_id})")
    return created


def confirm_link(link_id: str, confirmed_by: dict[str, Any]) -> dict[str, Any]:
    """学生本人确认 (或 admin 代确认, 低龄场景) → active, 立即可见数据."""
    link = _get_link_or_raise(link_id)
    is_owner = (
        confirmed_by["role"] == "student"
        and confirmed_by["user_id"] == link["learner_user_id"]
    )
    if not (is_owner or confirmed_by["role"] == "admin"):
        raise GuardianLinkError("只有学生本人或管理员可以确认该申请")
    if link["status"] != "pending":
        raise GuardianLinkError(f"该申请当前状态为 {link['status']}, 不能确认")
    store = get_auth_store()
    changed = store.set_link_status(
        link_id, "active", confirmed_by=confirmed_by["user_id"],
        now_iso=_now_iso(),
    )
    if not changed:  # 并发下状态已被流转
        raise GuardianLinkError("该申请已被处理")
    return store.get_link(link_id)  # type: ignore[return-value]


def reject_link(link_id: str, rejected_by: dict[str, Any]) -> dict[str, Any]:
    """学生拒绝申请 (pending → rejected, 留痕)."""
    link = _get_link_or_raise(link_id)
    is_owner = confirmed_by_is_owner(link, rejected_by)
    if not (is_owner or rejected_by["role"] == "admin"):
        raise GuardianLinkError("只有学生本人或管理员可以拒绝该申请")
    if link["status"] != "pending":
        raise GuardianLinkError(f"该申请当前状态为 {link['status']}, 不能拒绝")
    store = get_auth_store()
    changed = store.set_link_status(
        link_id, "rejected", revoked_by=rejected_by["user_id"],
        revocation_reason="learner_rejected", now_iso=_now_iso(),
    )
    if not changed:
        raise GuardianLinkError("该申请已被处理")
    return store.get_link(link_id)  # type: ignore[return-value]


def revoke_link(
    link_id: str, revoked_by: dict[str, Any], reason: str = ""
) -> dict[str, Any]:
    """撤销授权 (active → revoked): 学生或家长任一方可撤, 下一请求即失效."""
    link = _get_link_or_raise(link_id)
    is_guardian = revoked_by["user_id"] == link["guardian_user_id"]
    is_learner = revoked_by["user_id"] == link["learner_user_id"]
    if not (is_guardian or is_learner or revoked_by["role"] == "admin"):
        raise GuardianLinkError("只有授权双方或管理员可以撤销")
    if link["status"] != "active":
        raise GuardianLinkError(f"该授权当前状态为 {link['status']}, 不能撤销")
    store = get_auth_store()
    changed = store.set_link_status(
        link_id, "revoked",
        revoked_by=revoked_by["user_id"],
        revocation_reason=reason or ("learner_revoked" if is_learner else "guardian_revoked"),
        now_iso=_now_iso(),
    )
    if not changed:
        raise GuardianLinkError("该授权已被撤销")
    return store.get_link(link_id)  # type: ignore[return-value]


def confirmed_by_is_owner(link: dict[str, Any], user: dict[str, Any]) -> bool:
    """user 是否为该 link 的学生本人."""
    return user.get("role") == "student" and user.get("user_id") == link["learner_user_id"]


def list_links_for_guardian(guardian_user_id: str) -> list[dict[str, Any]]:
    """家长的申请/授权列表 (含 pending/rejected/revoked 全历史)."""
    return get_auth_store().list_links(guardian_user_id=guardian_user_id)


def list_links_for_learner(learner_user_id: str) -> list[dict[str, Any]]:
    """学生的申请/授权列表 (学生端确认页数据源)."""
    return get_auth_store().list_links(learner_user_id=learner_user_id)


def list_active_linked_student_ids(guardian_user_id: str) -> list[str]:
    """家长可见的学习记录键列表 (家长端 roster 数据源).

    链路: active link → learner_user → learning_student_id;
    学习记录懒创建, 该键可能还没有 students 行 (roster 时跳过)。
    """
    store = get_auth_store()
    result: list[str] = []
    for link in store.list_links(guardian_user_id=guardian_user_id, status="active"):
        learner = store.get_user_by_id(link["learner_user_id"])
        if learner is None or learner.get("role") != "student":
            continue  # 角色已变 → 旧授权不再放行 (现查语义)
        sid = learner.get("learning_student_id")
        if sid:
            result.append(sid)
    return result


def guardian_can_access(
    guardian_user_id: str,
    learner_user_id: str,
    permission: str,
) -> bool:
    """★ 2-A-4 单一校验入口: 家长能否以 permission 访问该学生.

    每次现查 (无缓存): active link 含该权限 + 双方账号当前角色/禁用
    状态复核 (对齐 DeepTutor: 角色变更后旧授权自动失效)。
    """
    if permission not in GUARDIAN_PERMISSIONS:
        _log.warning("guardian_can_access: 未知权限项 %r, 拒绝", permission)
        return False
    store = get_auth_store()
    guardian = store.get_user_by_id(guardian_user_id)
    learner = store.get_user_by_id(learner_user_id)
    # 双方角色现查: 角色变更后旧授权失效 (前学生变家长类越权路径)
    if guardian is None or guardian.get("role") != "guardian" or guardian.get("disabled_at"):
        return False
    if learner is None or learner.get("role") != "student" or learner.get("disabled_at"):
        return False
    link = store.find_active_link(guardian_user_id, learner_user_id)
    if link is None:
        return False
    try:
        permissions = json.loads(link.get("permissions") or "[]")
    except (TypeError, ValueError):
        _log.warning(
            "guardian_can_access: link %s permissions 非法 JSON, 拒绝", link["link_id"],
        )
        return False
    return permission in permissions


def guardian_can_access_student(
    guardian_user_id: str,
    learning_student_id: str,
    permission: str,
) -> bool:
    """家长端取数入口的便捷封装: 学习记录键 (student_id) 版本.

    家长端接口拿到的是 students 表键 (URL 里的 student_id),
    经 learning_student_id 反查学生账号后再走 guardian_can_access。
    """
    store = get_auth_store()
    learner = store.get_student_user_by_learning_student_id(learning_student_id)
    if learner is None:
        return False
    return guardian_can_access(guardian_user_id, learner["user_id"], permission)


# ─── 内部 ────────────────────────────────────────────────────────────────────


def _get_link_or_raise(link_id: str) -> dict[str, Any]:
    link = get_auth_store().get_link(link_id)
    if link is None:
        raise GuardianLinkError("授权记录不存在")
    return link


def decorate_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """link 行 → 前端友好形状 (补对方 username/display_name; permissions 转 list)."""
    store = get_auth_store()
    out: list[dict[str, Any]] = []
    for link in links:
        item = dict(link)
        try:
            item["permissions"] = json.loads(link.get("permissions") or "[]")
        except (TypeError, ValueError):
            item["permissions"] = []
            _log.warning("decorate_links: link %s permissions 非法 JSON", link["link_id"])
        guardian = store.get_user_by_id(link["guardian_user_id"])
        learner = store.get_user_by_id(link["learner_user_id"])
        item["guardian_username"] = guardian["username"] if guardian else None
        item["guardian_display_name"] = (guardian or {}).get("display_name")
        item["learner_username"] = learner["username"] if learner else None
        item["learner_student_id"] = (learner or {}).get("learning_student_id")
        out.append(item)
    return out
