"""Phase 2 / 2-A: guardian_learner_link 权限模型测试 (方案文档 14.3).

覆盖 (2-A-5):
  - 授权流程: 申请 → 学生确认 → active; 拒绝; 双方撤销 (留痕)
  - 申请规则: 自绑禁止 / 非 student 角色 / 权限白名单 / 同对唯一活跃关系
  - guardian_can_access: 每次现查 — pending 不可见 / 撤销下一请求即失效 /
    角色变更后旧授权失效 / 权限项粒度
  - 家长端数据接口: roster 只列已关联学生 / overview 未授权 403 /
    多家长关联互不干扰 / staff 视图不受限

全部 @pytest.mark.real_auth (退出 conftest auth_bypass, 走真实鉴权语义)。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.real_auth

PASSWORD = "password123"


@pytest.fixture()
def client():
    from web.api.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _init_schema():
    from cogedu.persistence.db import get_db

    get_db().init_schema()


class _People:
    """造人 helper: guardian / student(绑定 sid) / staff 各造一个."""

    def __init__(self, auth_factory, tag="a"):
        self.g_headers, self.guardian = auth_factory(
            username=f"g_{tag}", role="guardian"
        )
        self.s_headers, self.student = auth_factory(
            username=f"s_{tag}", role="student", learning_student_id=f"stu_{tag}"
        )
        self.admin_headers, self.admin = auth_factory(
            username=f"adm_{tag}", role="admin"
        )


@pytest.fixture()
def people(auth_factory):
    return _People(auth_factory)


def _request_link(client, headers, learner_username, permissions=None, tag="a"):
    """家长发起申请 (默认只申请 view_progress), 返回 (resp, link_id).

    注意 permissions=None 才用默认值 — 空列表是合法入参 (应被服务端拒绝)。
    """
    if permissions is None:
        permissions = ["view_progress"]
    resp = client.post(
        "/api/guardian/links",
        headers=headers,
        json={
            "learner_username": learner_username,
            "permissions": permissions,
        },
    )
    link_id = resp.json().get("link", {}).get("link_id")
    return resp, link_id


# ─── 授权流程 ────────────────────────────────────────────────────────────────


class TestLinkFlow:
    def test_full_flow_request_confirm_active(self, client, people):
        resp, link_id = _request_link(
            client, people.g_headers, "s_a", ["view_progress", "download_report"]
        )
        assert resp.status_code == 200
        assert resp.json()["link"]["status"] == "pending"

        # pending 期间学生可见申请
        lst = client.get("/api/student/guardian-links", headers=people.s_headers)
        assert lst.status_code == 200
        assert any(x["link_id"] == link_id for x in lst.json()["links"])

        # 学生确认 → active
        confirm = client.post(
            f"/api/student/guardian-links/{link_id}/confirm", headers=people.s_headers
        )
        assert confirm.status_code == 200
        assert confirm.json()["link"]["status"] == "active"

    def test_pending_not_visible_to_guardian(self, client, people):
        """pending 未确认不可见任何数据 (2-A-5 验收点)."""
        _, link_id = _request_link(client, people.g_headers, "s_a")
        # roster 空
        roster = client.get("/api/parent/students", headers=people.g_headers)
        assert roster.status_code == 200
        assert roster.json()["students"] == []
        # overview 拒绝
        ov = client.get(
            "/api/parent/students/stu_a/overview", headers=people.g_headers
        )
        assert ov.status_code == 403
        assert link_id  # 申请确实建了

    def test_confirm_by_other_student_rejected(self, client, people, auth_factory):
        _, link_id = _request_link(client, people.g_headers, "s_a")
        other_headers, _ = auth_factory(
            username="s_other", role="student", learning_student_id="stu_other"
        )
        resp = client.post(
            f"/api/student/guardian-links/{link_id}/confirm",
            headers=other_headers,
        )
        assert resp.status_code == 400
        # 仍是 pending
        lst = client.get("/api/student/guardian-links", headers=people.s_headers)
        status = next(
            x["status"] for x in lst.json()["links"] if x["link_id"] == link_id
        )
        assert status == "pending"

    def test_admin_can_confirm_on_behalf(self, client, people):
        """低龄场景: admin 代确认 (2-A-3)."""
        _, link_id = _request_link(client, people.g_headers, "s_a")
        resp = client.post(
            f"/api/student/guardian-links/{link_id}/confirm",
            headers=people.admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["link"]["status"] == "active"

    def test_reject_flow(self, client, people):
        _, link_id = _request_link(client, people.g_headers, "s_a")
        resp = client.post(
            f"/api/student/guardian-links/{link_id}/reject", headers=people.s_headers
        )
        assert resp.status_code == 200
        assert resp.json()["link"]["status"] == "rejected"
        # 拒绝后家长端不可见
        ov = client.get(
            "/api/parent/students/stu_a/overview", headers=people.g_headers
        )
        assert ov.status_code == 403

    def test_learner_revoke_immediate_effect(self, client, people):
        """学生撤销 → 家长端下一次请求立即失效 (2-A 验收点)."""
        _, link_id = _request_link(client, people.g_headers, "s_a")
        client.post(f"/api/student/guardian-links/{link_id}/confirm", headers=people.s_headers)

        # active 后可见
        ov = client.get("/api/parent/students/stu_a/overview", headers=people.g_headers)
        assert ov.status_code == 404  # 无学习记录 → 404 (授权过了, 数据还没有)

        # 学生撤销
        revoke = client.delete(
            f"/api/student/guardian-links/{link_id}", headers=people.s_headers
        )
        assert revoke.status_code == 200
        assert revoke.json()["link"]["status"] == "revoked"

        # 撤销后下一请求即 403 — 无缓存延迟
        ov2 = client.get(
            "/api/parent/students/stu_a/overview", headers=people.g_headers
        )
        assert ov2.status_code == 403
        roster = client.get("/api/parent/students", headers=people.g_headers)
        assert roster.json()["students"] == []

    def test_guardian_revoke_leaves_trail(self, client, people):
        _, link_id = _request_link(client, people.g_headers, "s_a")
        client.post(f"/api/student/guardian-links/{link_id}/confirm", headers=people.s_headers)
        resp = client.delete(f"/api/guardian/links/{link_id}", headers=people.g_headers)
        assert resp.status_code == 200
        link = resp.json()["link"]
        assert link["status"] == "revoked"
        assert link["revoked_by"] == people.guardian["user_id"]  # 撤销留痕
        assert link["revocation_reason"] == "guardian_revoked"


# ─── 申请规则 ────────────────────────────────────────────────────────────────


class TestRequestRules:
    def test_cannot_link_self(self, client, people):
        resp, _ = _request_link(client, people.g_headers, "g_a")
        assert resp.status_code == 400

    def test_cannot_link_non_student(self, client, people, auth_factory):
        auth_factory(username="g2_a", role="guardian")
        resp, _ = _request_link(client, people.g_headers, "g2_a")
        assert resp.status_code == 400

    def test_cannot_link_unknown_user(self, client, people):
        # 目标账号不存在 → 404 (申请指向的对象明确缺失, 与业务规则 400 区分)
        resp, _ = _request_link(client, people.g_headers, "ghost_user")
        assert resp.status_code == 404

    def test_invalid_permissions_rejected(self, client, people):
        resp, _ = _request_link(client, people.g_headers, "s_a", permissions=[])
        assert resp.status_code == 400
        resp2, _ = _request_link(
            client, people.g_headers, "s_a", permissions=["hack_admin"]
        )
        assert resp2.status_code == 400

    def test_duplicate_pending_409(self, client, people):
        _request_link(client, people.g_headers, "s_a")
        resp, _ = _request_link(client, people.g_headers, "s_a")
        assert resp.status_code == 409

    def test_reapply_after_revoke_allowed(self, client, people):
        """撤销后同对可重新申请 (partial unique index 只约束活跃关系)."""
        _, link_id = _request_link(client, people.g_headers, "s_a")
        client.post(f"/api/student/guardian-links/{link_id}/confirm", headers=people.s_headers)
        client.delete(f"/api/guardian/links/{link_id}", headers=people.g_headers)
        resp, _ = _request_link(client, people.g_headers, "s_a")
        assert resp.status_code == 200

    def test_teacher_cannot_request(self, client, people, auth_factory):
        t_headers, _ = auth_factory(username="t_a", role="teacher")
        resp, _ = _request_link(client, t_headers, "s_a")
        assert resp.status_code == 403


# ─── guardian_can_access 语义 ────────────────────────────────────────────────


class TestCanAccess:
    def _active_link(self, client, people, permissions=None):
        _, link_id = _request_link(
            client, people.g_headers, "s_a", permissions=permissions
        )
        client.post(f"/api/student/guardian-links/{link_id}/confirm", headers=people.s_headers)
        return link_id

    def test_permission_granularity(self, client, people):
        """只授 view_progress → download_report 类操作不可见 (权限项粒度)."""
        self._active_link(client, people, permissions=["view_progress"])
        from web.api import guardian as svc

        assert svc.guardian_can_access_student(
            people.guardian["user_id"], "stu_a", "view_progress"
        )
        assert not svc.guardian_can_access_student(
            people.guardian["user_id"], "stu_a", "download_report"
        )

    def test_unknown_permission_denied(self, client, people):
        from web.api import guardian as svc

        assert not svc.guardian_can_access(
            people.guardian["user_id"], people.student["user_id"], "super_power"
        )

    def test_role_change_invalidates_old_grant(self, client, people):
        """角色变更后旧授权失效 (现查语义, DeepTutor 防御思路)."""
        self._active_link(client, people)
        # 学生账号被改为 guardian 角色 (直改 DB 模拟管理操作)
        from cogedu.persistence.auth_store import get_auth_store

        store = get_auth_store()
        with store._tx():
            store.conn.execute(
                "UPDATE users SET role = 'guardian' WHERE user_id = ?",
                (people.student["user_id"],),
            )
        from web.api import guardian as svc

        assert not svc.guardian_can_access(
            people.guardian["user_id"], people.student["user_id"], "view_progress"
        )

    def test_disabled_learner_denies_access(self, client, people):
        self._active_link(client, people)
        from web.api import auth as auth_service
        from web.api import guardian as svc

        auth_service.set_user_disabled(people.student["user_id"], True)
        assert not svc.guardian_can_access_student(
            people.guardian["user_id"], "stu_a", "view_progress"
        )


# ─── 家长端数据接口 (per-student 校验) ────────────────────────────────────────


class TestParentEndpoints:
    def test_roster_only_linked_students(self, client, people, auth_factory):
        """多学生场景: guardian 只看到自己关联的; 多家长关联同一学生互不干扰."""
        # 学习记录懒创建 — roster 只显示"已授权且有学习记录"的学生
        from cogedu.persistence.db import get_db

        get_db().upsert_student("stu_a")
        get_db().upsert_student("stu_b")
        # 另一个学生 stu_b + 另一个家长 g_b 关联 stu_a 和 stu_b
        g_b_headers, g_b = auth_factory(username="g_b", role="guardian")
        s_b_headers, _ = auth_factory(
            username="s_b", role="student", learning_student_id="stu_b"
        )
        # g_a ↔ stu_a, g_b ↔ stu_a & stu_b
        _, l1 = _request_link(client, people.g_headers, "s_a")
        client.post(f"/api/student/guardian-links/{l1}/confirm", headers=people.s_headers)
        _, l2 = _request_link(client, g_b_headers, "s_a")
        client.post(f"/api/student/guardian-links/{l2}/confirm", headers=people.s_headers)
        _, l3 = _request_link(client, g_b_headers, "s_b")
        client.post(f"/api/student/guardian-links/{l3}/confirm", headers=s_b_headers)

        # g_a 只看到 stu_a
        roster_a = client.get("/api/parent/students", headers=people.g_headers)
        sids_a = [s["student_id"] for s in roster_a.json()["students"]]
        assert sids_a == ["stu_a"]
        # g_b 看到 stu_a + stu_b (多家长关联同一学生互不干扰)
        roster_b = client.get("/api/parent/students", headers=g_b_headers)
        sids_b = sorted(s["student_id"] for s in roster_b.json()["students"])
        assert sids_b == ["stu_a", "stu_b"]

    def test_overview_requires_view_progress(self, client, people, auth_factory):
        """未授权学生数据 403 (2-A-5 验收点) — 已授权的进了 handler 后走 404
        (学习记录不存在, 防幽灵学生语义不变)。"""
        _, link_id = _request_link(
            client, people.g_headers, "s_a", permissions=["view_progress"]
        )
        client.post(f"/api/student/guardian-links/{link_id}/confirm", headers=people.s_headers)
        # 未关联的学生 → 403
        auth_factory(username="s_c", role="student", learning_student_id="stu_c")
        resp = client.get(
            "/api/parent/students/stu_c/overview", headers=people.g_headers
        )
        assert resp.status_code == 403
        # 已关联但无学习记录 → 404 (防幽灵学生, 不创建)
        resp2 = client.get(
            "/api/parent/students/stu_a/overview", headers=people.g_headers
        )
        assert resp2.status_code == 404

    def test_staff_view_unaffected(self, client, people, auth_factory):
        """staff (admin) 保持全量 roster — 存量教师端行为不变."""
        t_headers, _ = auth_factory(username="t_b", role="teacher")
        # 学生先答题建学习记录 (staff roster 读 students 表)
        from cogedu.persistence.db import get_db

        get_db().upsert_student("stu_a")
        roster = client.get("/api/teacher/students", headers=t_headers)
        assert roster.status_code == 200
        assert any(s["student_id"] == "stu_a" for s in roster.json()["students"])
