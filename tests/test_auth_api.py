"""Phase 2 / 2-0: 账号体系测试 (方案文档 14.2).

覆盖:
  - 服务层: 密码哈希/校验、create_user 规则、会话签发/过期/撤销/禁用
  - HTTP 契约: login / logout / me
  - 角色-路由矩阵: 未登录 401、角色不符 403、学生越权 403、staff 放行

全部用 @pytest.mark.real_auth 退出 conftest 的 auth_bypass —
这是仓库里唯一测真实鉴权语义的地方 (存量契约测试免登录跑, 见 conftest)。
"""
from __future__ import annotations

from datetime import UTC

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.real_auth

PASSWORD = "password123"


@pytest.fixture()
def client():
    from web.api.app import app

    with TestClient(app) as c:
        yield c


# ─── 服务层: 密码 ────────────────────────────────────────────────────────────


class TestPassword:
    def test_hash_and_verify(self):
        from web.api.auth import hash_password, verify_password

        h = hash_password(PASSWORD)
        assert h != PASSWORD
        assert h.startswith("$2")  # bcrypt 格式
        assert verify_password(PASSWORD, h)
        assert not verify_password("wrong-password", h)

    def test_hash_salt_random(self):
        from web.api.auth import hash_password

        # 同密码两次哈希 salt 不同 (防 rainbow table)
        assert hash_password(PASSWORD) != hash_password(PASSWORD)

    def test_password_too_short_rejected(self):
        from web.api.auth import AuthError, hash_password

        with pytest.raises(AuthError):
            hash_password("short")

    def test_verify_bad_hash_format_returns_false(self):
        from web.api.auth import verify_password

        # 哈希格式坏 → False + warning, 不抛 (登录失败即可)
        assert not verify_password(PASSWORD, "not-a-bcrypt-hash")


# ─── 服务层: 账号 ────────────────────────────────────────────────────────────


class TestCreateUser:
    def test_create_student_requires_learning_student_id(self):
        from web.api.auth import AuthError, create_user

        with pytest.raises(AuthError, match="learning_student_id"):
            create_user("stu_no_link", PASSWORD, "student")

    def test_create_unknown_role_rejected(self):
        from web.api.auth import AuthError, create_user

        with pytest.raises(AuthError, match="未知角色"):
            create_user("role_x", PASSWORD, "superuser")

    def test_duplicate_username_rejected(self):
        from web.api.auth import AuthError, create_user

        create_user("dup_user", PASSWORD, "guardian")
        with pytest.raises(AuthError, match="已存在"):
            create_user("dup_user", PASSWORD, "guardian")

    def test_username_length_enforced(self):
        from web.api.auth import AuthError, create_user

        with pytest.raises(AuthError):
            create_user("ab", PASSWORD, "guardian")  # < 3

    def test_public_user_never_leaks_hash(self):
        from web.api.auth import create_user, public_user

        user = create_user("leak_check", PASSWORD, "guardian")
        pub = public_user(user)
        assert "password_hash" not in pub
        assert pub["role"] == "guardian"


# ─── 服务层: 会话生命周期 ─────────────────────────────────────────────────────


class TestSessionLifecycle:
    def _user(self, username="sess_user", role="guardian"):
        from web.api.auth import create_user

        return create_user(username, PASSWORD, role)

    def test_issue_and_resolve(self):
        from web.api.auth import issue_session, resolve_session

        user = self._user("sess_ok")
        token, expires_at = issue_session(user["user_id"])
        assert token and expires_at
        resolved = resolve_session(token)
        assert resolved is not None
        assert resolved["user_id"] == user["user_id"]

    def test_resolve_invalid_token_none(self):
        from web.api.auth import resolve_session

        assert resolve_session("garbage-token") is None
        assert resolve_session("") is None

    def test_revoke_immediate_effect(self):
        """撤销立即生效 (服务端会话的核心理由, 2-A 验收点的前置语义)."""
        from web.api.auth import issue_session, resolve_session, revoke_token

        user = self._user("sess_revoke")
        token, _ = issue_session(user["user_id"])
        assert resolve_session(token) is not None
        assert revoke_token(token) == 1
        assert resolve_session(token) is None  # 撤销后下一请求即失效
        # 幂等: 再撤一次不报错
        assert revoke_token(token) == 0

    def test_expired_session_rejected(self, monkeypatch):
        from web.api.auth import issue_session, resolve_session

        user = self._user("sess_expire")
        token, _ = issue_session(user["user_id"])
        # 时间冻结到 TTL 之后 (只动 resolve_session 里的 now, fromisoformat 原样)
        from datetime import datetime, timedelta

        future = datetime.now(UTC) + timedelta(hours=24 * 7 + 1)
        real_fromisoformat = datetime.fromisoformat

        class _FakeDatetime:
            fromisoformat = staticmethod(real_fromisoformat)

            @staticmethod
            def now(tz=None):
                return future

        monkeypatch.setattr("web.api.auth.datetime", _FakeDatetime)
        assert resolve_session(token) is None

    def test_disabled_user_session_invalidated(self):
        """禁用账号: 登录被拒 + 存量会话立即失效."""
        from web.api import auth as auth_service

        user = self._user("sess_disable")
        token, _ = auth_service.issue_session(user["user_id"])
        assert auth_service.resolve_session(token) is not None

        auth_service.set_user_disabled(user["user_id"], True)
        # 登录失败
        assert auth_service.authenticate("sess_disable", PASSWORD) is None
        # 存量会话立即失效
        assert auth_service.resolve_session(token) is None

    def test_authenticate_wrong_password_none(self):
        from web.api.auth import authenticate

        self._user("auth_neg")
        assert authenticate("auth_neg", "wrong-password-99") is None
        # 用户不存在同样 None (不区分, 防用户名枚举)
        assert authenticate("no_such_user", PASSWORD) is None

    def test_token_never_stored_plaintext(self):
        """token 明文不落库 — sessions 表只存哈希."""
        from cogedu.persistence.auth_store import get_auth_store, hash_token
        from web.api.auth import issue_session

        user = self._user("sess_hash")
        token, _ = issue_session(user["user_id"])
        assert get_auth_store().get_session(token) is None  # 明文查不到
        assert get_auth_store().get_session(hash_token(token)) is not None


# ─── HTTP 契约: /api/auth/* ──────────────────────────────────────────────────


class TestAuthEndpoints:
    def test_login_success(self, client, auth_factory):
        auth_factory(username="http_user", role="guardian")
        resp = client.post(
            "/api/auth/login",
            json={"username": "http_user", "password": PASSWORD},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["token"]
        assert body["user"]["role"] == "guardian"
        assert "password_hash" not in body["user"]

    def test_login_wrong_password_401(self, client, auth_factory):
        auth_factory(username="http_bad", role="guardian")
        resp = client.post(
            "/api/auth/login",
            json={"username": "http_bad", "password": "wrong-password-99"},
        )
        assert resp.status_code == 401

    def test_login_unknown_user_401(self, client):
        resp = client.post(
            "/api/auth/login",
            json={"username": "ghost", "password": PASSWORD},
        )
        assert resp.status_code == 401

    def test_me_requires_token(self, client):
        assert client.get("/api/auth/me").status_code == 401

    def test_me_with_token(self, client, auth_factory):
        headers, user = auth_factory(username="http_me", role="student",
                                     learning_student_id="stu_001")
        resp = client.get("/api/auth/me", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["user"]["learning_student_id"] == "stu_001"

    def test_logout_revokes_token(self, client, auth_factory):
        headers, _ = auth_factory(username="http_out", role="guardian")
        assert client.get("/api/auth/me", headers=headers).status_code == 200
        assert client.post("/api/auth/logout", headers=headers).status_code == 200
        # 撤销后同一 token 下一请求即 401
        assert client.get("/api/auth/me", headers=headers).status_code == 401


# ─── 前端登录态接线 (2-0-4) ──────────────────────────────────────────────────


class TestFrontendWiring:
    def test_login_page_served(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "/api/auth/login" in resp.text

    def test_auth_js_served(self, client):
        resp = client.get("/auth.js")
        assert resp.status_code == 200
        assert "Authorization" in resp.text

    def test_all_pages_include_auth_js(self):
        """各端页面都引入 auth.js (页面守卫的前提)."""
        from pathlib import Path

        web_dir = Path(__file__).resolve().parent.parent / "web"
        for rel in (
            "student/index.html",
            "student/scene.html",
            "teacher/index.html",
            "parent/index.html",
        ):
            html = (web_dir / rel).read_text(encoding="utf-8")
            assert 'src="/auth.js' in html, f"{rel} 未引入 /auth.js"

    def test_scene_event_writes_carry_identity(self):
        """scene.js 行为回写带 Authorization (匿名可写越权面的接线锁定)."""
        from pathlib import Path

        scene_js = (
            Path(__file__).resolve().parent.parent / "web" / "student" / "scene.js"
        ).read_text(encoding="utf-8")
        assert "Authorization" in scene_js

    def test_scene_api_helper_uses_authfetch(self):
        """scene 页 api 助手走 authFetch (2026-09-14 补).

        outline/scenes/timing 是页面内主要请求路径, 此前裸 fetch 不带
        凭证——真实鉴权下"点击讲解"必 401 (测试 auth_bypass 掩盖),
        维护者页面观感验收时暴露.
        """
        from pathlib import Path

        scene_js = (
            Path(__file__).resolve().parent.parent / "web" / "student" / "scene.js"
        ).read_text(encoding="utf-8")
        assert "CogEduAuth.authFetch(url, opts)" in scene_js

    def test_app_js_uses_authfetch(self):
        """学生端 api 封装走 authFetch (401 统一跳登录)."""
        from pathlib import Path

        app_js = (
            Path(__file__).resolve().parent.parent / "web" / "student" / "app.js"
        ).read_text(encoding="utf-8")
        assert "authFetch" in app_js

    def test_app_js_sid_resolves_to_bound_identity(self):
        """app.js 的 sid 解析: 登录账号绑定优先, 硬编码兜底已删 (2026-09-14).

        2-0-4 只修了 scene.js, index 页 app.js 漏了同款问题——登录态下
        仍可能拿 localStorage 旧值/硬编码 'python_student_001' 请求他人
        数据 → 服务端 403 → "登录后数据加载失败" (维护者实测暴露).
        """
        from pathlib import Path

        app_js = (
            Path(__file__).resolve().parent.parent / "web" / "student" / "app.js"
        ).read_text(encoding="utf-8")
        assert "learning_student_id" in app_js
        assert "sid = 'python_student_001'" not in app_js

    def test_frontend_api_base_no_hardcoded_host(self):
        """前端 API base 不得写死主机名 (2026-09-14).

        app.js 曾写死 http://localhost:5173/api——从 0.0.0.0/局域网 IP
        打开页面时变跨源请求, 浏览器直接拒 ("Failed to fetch").
        静态页由 FastAPI 同源托管, 必须用源相对路径 '/api'.
        """
        from pathlib import Path

        web_dir = Path(__file__).resolve().parent.parent / "web"
        offenders = [
            str(p.relative_to(web_dir.parent))
            for p in web_dir.rglob("*.js")
            # 排除第三方依赖与构建产物：本锁针对 CogEdu 自有前端源文件
            if "node_modules" not in p.parts
            and "dist" not in p.parts
            and (
                "localhost:5173" in p.read_text(encoding="utf-8")
                or "127.0.0.1:5173" in p.read_text(encoding="utf-8")
            )
        ]
        assert not offenders, f"写死主机名的前端文件: {offenders}"


class TestPhase2DFrontend:
    """2-D (14.6): 家长端真实页 + 学生端授权确认页 — 路由与接线契约."""

    def test_parent_page_served(self, client):
        """/parent/ 路由 200（9-A 起 dist 优先返回 React 壳）+ legacy 兜底页接线完整.

        双轨过渡（方案文档 §10.1.5）：React dist 存在时路由由 dist 接管，
        legacy 页（web/parent/index.html）降为兜底但须保持接线完整，
        直至 9-E 家长端切换完成后移除。
        """
        resp = client.get("/parent/index.html")
        assert resp.status_code == 200
        assert "<div id=\"root\">" in resp.text  # React 壳（dist 优先）
        # legacy 兜底页三大块: 仪表盘(roster/overview) + 授权管理 + 报告下载
        # (页面 JS 经 authFetch('/api' + path) 拼接, 断言 path 字面量)
        from pathlib import Path

        legacy = (
            Path(__file__).resolve().parent.parent
            / "web" / "parent" / "index.html"
        ).read_text(encoding="utf-8")
        assert "'/parent/students'" in legacy
        assert "'/guardian/links'" in legacy
        assert "/report?period=' + period" in legacy

    def test_student_guardian_links_page_served(self, client):
        resp = client.get("/student/guardian-links.html")
        assert resp.status_code == 200
        assert "'/student/guardian-links'" in resp.text
        assert '"/confirm"' in resp.text and '"/reject"' in resp.text

    def test_student_index_has_links_page_entry(self):
        from pathlib import Path

        html = (
            Path(__file__).resolve().parent.parent
            / "web" / "student" / "index.html"
        ).read_text(encoding="utf-8")
        assert "/student/guardian-links.html" in html


# ─── 角色-路由矩阵 (2-0-3) ───────────────────────────────────────────────────

class TestRoleMatrix:
    """每个受保护域至少覆盖: 未登录 401 / 角色不符 403 / 合法角色 200。

    业务 200 路径由各域契约测试负责 (auth_bypass), 这里只锁鉴权语义。
    """

    @pytest.fixture(autouse=True)
    def _init_schema(self):
        # 200 路径会真查 students 表 — tmp DB 需先建 schema
        from cogedu.persistence.db import get_db

        get_db().init_schema()

    def test_unauthenticated_401_across_domains(self, client):
        # (method, path) — 每个受保护域至少一条
        for method, path in (
            ("GET", "/api/teacher/students"),
            ("GET", "/api/parent/students"),
            ("GET", "/api/state/stu_001"),
            ("POST", "/api/event/hint"),
            ("POST", "/api/answer"),
            ("POST", "/api/presentation/event"),
            ("GET", "/api/dual_agent/debug/stu_001"),
            ("GET", "/api/students/recent"),
            ("GET", "/api/auth/me"),
        ):
            resp = client.request(
                method,
                path,
                json={"student_id": "stu_001"} if method == "POST" else None,
            )
            assert resp.status_code == 401, f"{method} {path}"

    def test_teacher_domain_rejects_guardian(self, client, auth_factory):
        headers, _ = auth_factory(username="g_role", role="guardian")
        assert client.get("/api/teacher/students", headers=headers).status_code == 403

    def test_teacher_domain_allows_teacher(self, client, auth_factory):
        headers, _ = auth_factory(username="t_role", role="teacher")
        assert client.get("/api/teacher/students", headers=headers).status_code == 200

    def test_parent_domain_rejects_student(self, client, auth_factory):
        headers, _ = auth_factory(username="s_role", role="student",
                                  learning_student_id="stu_001")
        assert client.get("/api/parent/students", headers=headers).status_code == 403

    def test_parent_domain_allows_guardian(self, client, auth_factory):
        headers, _ = auth_factory(username="g_ok", role="guardian")
        # 空库 roster 返回空列表 (200) — 鉴权通过即达契约
        assert client.get("/api/parent/students", headers=headers).status_code == 200

    def test_student_cannot_read_other_student(self, client, auth_factory):
        """学生只能读自己 learning_student_id 的数据 — 越权 403."""
        headers, _ = auth_factory(username="s_own", role="student",
                                  learning_student_id="stu_mine")
        assert client.get("/api/state/stu_other", headers=headers).status_code == 403

    def test_student_can_read_own_data(self, client, auth_factory):
        headers, _ = auth_factory(username="s_self", role="student",
                                  learning_student_id="stu_mine")
        assert client.get("/api/state/stu_mine", headers=headers).status_code == 200

    def test_student_cannot_write_answer_as_other(self, client, auth_factory):
        """/api/answer 的 student_id 在请求体 — body 路径越权同样 403."""
        headers, _ = auth_factory(username="s_body", role="student",
                                  learning_student_id="stu_mine")
        resp = client.post(
            "/api/answer",
            headers=headers,
            json={
                "student_id": "stu_other",
                "problem_id": "p1",
                "skill_id": "s1",
                "correct": True,
            },
        )
        assert resp.status_code == 403

    def test_teacher_can_access_any_student(self, client, auth_factory):
        headers, _ = auth_factory(username="t_any", role="teacher")
        assert client.get("/api/state/stu_anyone", headers=headers).status_code == 200

    def test_student_role_required_for_event_write(self, client, auth_factory):
        """guardian 不能替学生回写行为事件 (回写权在学生端)."""
        headers, _ = auth_factory(username="g_evt", role="guardian")
        resp = client.post(
            "/api/event/hint",
            headers=headers,
            json={"student_id": "stu_001", "skill_id": "s1"},
        )
        assert resp.status_code == 403
