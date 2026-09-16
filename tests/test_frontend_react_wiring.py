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

    def test_student_css_imported(self):
        """学生端专属样式表必须被引入（2026-09-15 人工验收发现：漏引致整页裸排版）.

        student/index.css 自带 @import "../index.css"，引它即同时拿全局基础。
        """
        main_tsx = (SRC_DIR / "student" / "main.tsx").read_text(encoding="utf-8")
        assert 'import "./index.css"' in main_tsx


class TestKaTeXLocalVendor:
    def test_student_html_uses_local_vendor(self):
        html = _read("student.html")
        assert "/vendor/katex/katex.min.css" in html

    def test_katex_js_loaded_before_formula(self):
        """katex.min.js 必须加载且在 formula.js 之前（defer 按文档序执行）.

        2026-09-15 验收发现：9-D 移植时漏抄这行 → window.katex 缺失 →
        formula.js 降级等宽原文直出（白板 $$ 源码复现）。
        """
        html = _read("student.html")
        assert 'src="/vendor/katex/katex.min.js"' in html
        assert html.index("katex.min.js") < html.index("formula.js")

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

    def test_scene_page_consumes_route_param(self):
        """/scene/:outlineId 的路由参数必须被 ScenePage 消费（复看模式激活的前提）.

        2026-09-15 验收发现：路由存在但组件未读 useParams 且 App 未传 prop，
        点讲解记录行只原地重渲染列表、复看永不激活。
        """
        page = (SRC_DIR / "student" / "presentation" / "ScenePage.tsx").read_text(
            encoding="utf-8"
        )
        assert "useParams" in page
        assert "params.outlineId" in page


@pytest.mark.parametrize(
    "rel",
    ["index.html", "student.html", "parent.html"],
)
def test_three_entries_exist(rel: str):
    """三入口 html 存在（static_pages DIST_DIR 约定的构建输入前提）."""
    assert (FRONTEND_DIR / rel).is_file()


def test_parent_entry_has_router_provider():
    """家长端入口必须包 HashRouter（无 Routes ≠ 无 Router）.

    2026-09-15 验收发现：9-B 重写 parent/main.tsx 时漏了 HashRouter，
    ParentHomePage 的 useSearchParams 在 Router 上下文外直接抛异常，
    整端白屏（守卫/退出登录全部不可达）。
    """
    main_tsx = (SRC_DIR / "parent" / "main.tsx").read_text(encoding="utf-8")
    assert "HashRouter" in main_tsx
    # 包裹顺序：HashRouter 必须在 QueryClientProvider 内层且包住 App
    assert main_tsx.index("<HashRouter>") < main_tsx.index("<App />")


class TestSidebarShellWiring:
    """UI-R-1：SidebarShell + DrawerNav 接线契约.

    锁语义（设计稿 docs/ui-r-0-信息架构设计稿.md §10.3）：
      - 单一导航源 navTree（侧栏与抽屉必须共用，禁止双套维护）
      - 8 个学生路由在 navTree 全可达（不留死链）
      - Phase 4-6 槽位 disabled（enabled = false，不提前渲染可点链接）
      - 旧 .bottom-nav / .student-topbar 已退役（不泄漏到三端）
      - 三形态断点 = 768 / 1024（不是旧的 720 / 721）
      - vanilla 模块挂载点（student.html 三 script defer 顺序）继续生效
    """

    def test_navtree_is_single_source_for_sidebar_and_drawer(self):
        """侧栏与抽屉必须 import 自同一份 navTree，禁止硬编码列表."""
        sidebar = (SRC_DIR / "student" / "components" / "SidebarShell.tsx").read_text(
            encoding="utf-8"
        )
        drawer = (SRC_DIR / "student" / "components" / "DrawerNav.tsx").read_text(
            encoding="utf-8"
        )
        # 都从同目录 navTree 拿 NAV_GROUPS
        assert 'from "./navTree"' in sidebar
        assert "NAV_GROUPS" in sidebar
        assert 'from "./navTree"' in drawer
        assert "NAV_GROUPS" in drawer
        # 禁双套维护：不允许 SidebarShell/DrawerNav 内自建 items 数组
        assert "const items = [" not in sidebar
        assert "const items = [" not in drawer

    def test_navtree_has_all_eight_student_routes(self):
        """8 个学生路由全部在 navTree 可达（设计稿 §4 路由表）."""
        navtree = (SRC_DIR / "student" / "components" / "navTree.ts").read_text(
            encoding="utf-8"
        )
        expected = {
            "/",  # 今天
            "/answer",  # 答题
            "/scene",  # 讲解（/scene/:outlineId 由 /scene 触发，不另列）
            "/where",  # 我在哪
            "/growth",  # 成长
            "/report",  # 学习报告
            "/guardian-links",  # 家长授权
            "/settings",  # 设置
        }
        for path in expected:
            assert f'path: "{path}"' in navtree, f"navTree 缺少路径 {path}"

    def test_phase_4_6_slots_disabled(self):
        """工具组 4 个 Phase 4-6 槽位必须 enabled=false（占位不渲染可点链接）."""
        navtree = (SRC_DIR / "student" / "components" / "navTree.ts").read_text(
            encoding="utf-8"
        )
        # 槽位特征：enabled: false + comingIn: "Phase N"
        # 必须出现 4 次 enabled: false（在 navTree 单源内）
        assert navtree.count("enabled: false") == 4
        for phase in ("Phase 4", "Phase 5", "Phase 6"):
            assert phase in navtree, f"navTree 缺少 {phase} 槽位注释"

    def test_old_bottom_nav_and_student_topbar_retired(self):
        """App.tsx 必须移除旧的 .bottom-nav 与 .student-topbar 类."""
        app_tsx = (SRC_DIR / "student" / "App.tsx").read_text(encoding="utf-8")
        assert 'className="bottom-nav"' not in app_tsx
        assert 'className="student-topbar"' not in app_tsx
        # student/index.css 也必须彻底移除旧类（防止泄漏）
        index_css = (SRC_DIR / "student" / "index.css").read_text(encoding="utf-8")
        assert ".bottom-nav" not in index_css
        assert ".student-topbar" not in index_css

    def test_app_wraps_routes_in_sidebar_shell(self):
        """SidebarShell 必须包住整段 Routes（设计稿 §3 工作台形态）."""
        app_tsx = (SRC_DIR / "student" / "App.tsx").read_text(encoding="utf-8")
        assert "SidebarShell" in app_tsx
        assert "<Routes>" in app_tsx
        # SidebarShell 必须包住 Routes：SidebarShell 的开标签出现在 <Routes> 之前
        assert app_tsx.index("SidebarShell") < app_tsx.index("<Routes>")
        # Routes 必须闭合于 SidebarShell 内部：</Routes> 出现在 </SidebarShell> 之前
        assert app_tsx.index("</Routes>") < app_tsx.index("</SidebarShell>")

    def test_breakpoints_are_768_and_1024_not_720_721(self):
        """UI-R-1 断点 = 768 / 1024（设计稿 §2 三形态）；
        旧 720 / 721 必须彻底清掉，防止新旧断点并存导致 CSS 优先级混乱.
        注意：`.answer-page { max-width: 720px }` 是合法固定宽度（手机友好的答题页），
        不是断点——这里只断言 @media 媒体查询层面无 720/721 残留.
        """
        import re
        index_css = (SRC_DIR / "student" / "index.css").read_text(encoding="utf-8")
        sidebar = (SRC_DIR / "student" / "components" / "SidebarShell.tsx").read_text(
            encoding="utf-8"
        )
        # 只在 @media 查询内查 720/721（旧断点），不在普通选择器内查
        media_blocks = re.findall(r"@media[^{]+\{[^}]*\{[^}]*\}", index_css)
        # 也覆盖未嵌套的简单媒体块
        media_blocks.extend(re.findall(r"@media[^{]+\{[^@]*?\}\s*\n", index_css))
        joined = "\n".join(media_blocks)
        for legacy in ("max-width: 720px", "min-width: 721px"):
            assert legacy not in joined, f"index.css 残留旧断点: {legacy}"
        # 新断点必须存在
        assert "max-width: 767px" in index_css
        assert "min-width: 768px" in index_css
        assert "min-width: 1024px" in index_css
        # SidebarShell 必须按断点判断形态
        assert "min-width: 768px" in sidebar
        assert "min-width: 1024px" in sidebar

    def test_no_new_fixed_width_constraint_on_shell_content(self):
        """shell-content 是 SidebarShell 主内容区，必须用响应式 padding（无 max-width），
        让各页（如 answer-page max-width: 720px）自管宽度.
        """
        index_css = (SRC_DIR / "student" / "index.css").read_text(encoding="utf-8")
        assert ".shell-content" in index_css
        # 抽取 .shell-content 规则块，确认不带 max-width
        import re
        blocks = re.findall(r"\.shell-content[^{]*\{[^}]*\}", index_css)
        assert blocks, ".shell-content 未定义"
        for blk in blocks:
            assert "max-width" not in blk, (
                f".shell-content 不应有 max-width 约束（设计稿 §7 让各页自管宽度）: {blk}"
            )

    def test_phase3_vanilla_modules_unaffected(self):
        """Phase 3 vanilla 三模块挂载点（design 9-D / §10.1.3 拍板）必须继续生效.
        UI-R-1 仅前端布局重构，不动 student.html script 顺序与 react entry.
        """
        html = _read("student.html")
        # 三模块 defer 顺序锁（与 TestScriptLoadOrder.test_three_modules_deferred_in_order 一致）
        assert html.index("formula.js") < html.index("playback.js") < html.index(
            "whiteboard.js"
        )
        # react entry 不变
        assert 'src="/src/student/main.tsx"' in html
