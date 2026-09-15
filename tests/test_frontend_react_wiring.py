"""React 前端（UI 现代化 §10 #9 / 9-A..9-E）接线契约——双轨迁移（方案文档 §10.1.5）.

legacy 静态页的同类锁（test_auth_api / test_whiteboard_wiring /
test_frontend_event_wiring）语义不变、继续执行（legacy 页降为兜底但接线
须完整）；本文件把同一批锁语义迁移到 React 工程源文件（web/frontend/）：

- script 装载顺序（formula → playback → whiteboard，挂载式整合 §10.1.3）
- KaTeX 本地 vendor（禁 CDN）
- LLM 文本安全（React 侧连 innerHTML 都不用：无 dangerouslySetInnerHTML）
- 认证接线（Bearer + 401 跳登录 + cogedu_token 键名互操作）
- sid 来源 = 登录身份 learning_student_id（禁手输）
- API base 同源相对路径（禁写死主机名）
- presentation / parent 端点路径字面量
"""

from __future__ import annotations

from pathlib import Path

import pytest

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "web" / "frontend"
SRC_DIR = FRONTEND_DIR / "src"


def _read(rel: str) -> str:
    return (FRONTEND_DIR / rel).read_text(encoding="utf-8")


class TestScriptLoadOrder:
    """student.html 三模块顺序与 defer（= legacy scene.html TestScriptLoadOrder 语义）."""

    def test_three_modules_deferred_in_order(self):
        html = _read("student.html")
        assert 'src="/student/formula.js"' in html
        assert 'src="/student/playback.js"' in html
        assert 'src="/student/whiteboard.js"' in html
        assert "defer" in html
        # 顺序: formula → playback → whiteboard
        assert html.index("formula.js") < html.index("playback.js") < html.index(
            "whiteboard.js"
        )

    def test_react_entry_present(self):
        html = _read("student.html")
        assert 'src="/src/student/main.tsx"' in html


class TestKaTeXLocalVendor:
    def test_student_html_uses_local_vendor(self):
        html = _read("student.html")
        assert "/vendor/katex/katex.min.css" in html

    def test_no_cdn_anywhere(self):
        offenders = [
            str(p.relative_to(FRONTEND_DIR))
            for p in FRONTEND_DIR.rglob("*")
            if p.suffix in {".html", ".ts", ".tsx", ".css"}
            and "node_modules" not in p.parts
            and "dist" not in p.parts
            and p.is_file()
            and "cdn.jsdelivr.net" in p.read_text(encoding="utf-8")
        ]
        assert not offenders, f"前端源文件出现 CDN 引用: {offenders}"


class TestLlmTextSafety:
    def test_no_dangerous_html_in_react_source(self):
        """legacy 锁 innerHTML 用途；React 侧直接禁用 dangerouslySetInnerHTML."""
        offenders = [
            str(p.relative_to(SRC_DIR))
            for p in SRC_DIR.rglob("*.tsx")
            if "dangerouslySetInnerHTML" in p.read_text(encoding="utf-8")
        ]
        assert not offenders, f"React 源出现 dangerouslySetInnerHTML: {offenders}"


class TestAuthWiring:
    def test_auth_base_uses_bearer_and_session_keys(self):
        src = (SRC_DIR / "shared" / "auth.ts").read_text(encoding="utf-8")
        assert "Authorization" in src
        assert "Bearer" in src
        # localStorage 键与 legacy web/auth.js 互操作
        assert 'cogedu_token' in src
        assert 'cogedu_user' in src
        # 401 → 清会话跳登录（next 白名单由 login 页保证）
        assert "/login?next=" in src

    def test_student_sid_from_login_identity(self):
        """sid 来源 = learning_student_id；禁手输（3-F-5 语义在 React 侧延续）."""
        app_tsx = (SRC_DIR / "student" / "App.tsx").read_text(encoding="utf-8")
        assert "learningStudentId" in app_tsx
        assert "prompt(" not in app_tsx
        assert "ecos_last_student_id" not in app_tsx

    def test_no_hardcoded_host_in_react_source(self):
        offenders = [
            str(p.relative_to(SRC_DIR))
            for p in list(SRC_DIR.rglob("*.ts"))
            + list(SRC_DIR.rglob("*.tsx"))
            + list(FRONTEND_DIR.glob("*.html"))
            if "localhost:5173" in p.read_text(encoding="utf-8")
            or "127.0.0.1:5173" in p.read_text(encoding="utf-8")
        ]
        assert not offenders, f"React 源写死主机名: {offenders}"


class TestEndpointWiring:
    def test_presentation_client_paths(self):
        """presentation 域路径字面量（GET 带 ?student_id= —— require_student_access 放行所需）."""
        src = (SRC_DIR / "student" / "presentation" / "api.ts").read_text(encoding="utf-8")
        for path in (
            "/api/presentation/outline",
            "/api/presentation/scenes",
            "/status?student_id=",
            "/api/presentation/timing?student_id=",
            "/api/presentation/event",
            "/api/presentation/audio/",
        ):
            assert path in src, f"presentation client 缺少路径字面量: {path}"

    def test_scene_page_has_replay_and_event_wiring(self):
        """复看路由 + 1-F 回写事件接线."""
        page = (SRC_DIR / "student" / "presentation" / "ScenePage.tsx").read_text(
            encoding="utf-8"
        )
        assert "scene_viewed" in page
        assert "scene_completed" in page
        assert "console.warn(" in page  # 回写 best-effort 不静默

    def test_parent_endpoint_paths(self):
        """家长端三块接线（对应 legacy parent/index.html 内容锁语义迁移）."""
        src = (SRC_DIR / "parent" / "api.ts").read_text(encoding="utf-8")
        assert "/api/parent/students" in src
        assert "/api/guardian/links" in src
        assert "/report?period=" in src

    def test_student_routes_present(self):
        app_tsx = (SRC_DIR / "student" / "App.tsx").read_text(encoding="utf-8")
        assert '"/scene"' in app_tsx
        assert '"/scene/:outlineId"' in app_tsx  # 复看模式
        assert '"/guardian-links"' in app_tsx


@pytest.mark.parametrize(
    "rel",
    ["index.html", "student.html", "parent.html"],
)
def test_three_entries_exist(rel: str):
    """三入口 html 存在（static_pages DIST_DIR 约定的构建输入前提）."""
    assert (FRONTEND_DIR / rel).is_file()
