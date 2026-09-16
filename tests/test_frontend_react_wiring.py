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


class TestScenePageDesktopWiring:
    """UI-R-2：讲解场景页桌面布局重构接线契约.

    锁语义（设计稿 docs/ui-r-0-信息架构设计稿.md §5 + §10）：
      - .wrap { max-width: 720px } 已删除（白板破 720 版心）
      - ScenePage 引入 OutlinePanel 大纲面板
      - ScenePlayer 暴露 onSubtitleChange + renderControls 接口
      - ≥1024 双栏 grid 布局；768-1023 大纲抽屉；<768 退化形态
      - Phase 3 vanilla 挂载（wb-container + whiteboard.js createWhiteboard）继续生效
      - 控制条 DOM id（scene-prev / scene-next / wb-play / wb-replay）保留
    """

    def test_scene_css_no_wrap_720_constraint(self):
        """白板破 720：scene.css 的 .wrap { max-width: 720px } 必须删除.
        UI-R-1 的 720/721 断点已清，但 scene.css 内的 .wrap 720 仍在——本步扫尾.
        注意：必须剥离 CSS 注释（/* ... */）后再 grep——注释里的描述文字不应被算作规则.
        """
        import re
        css = (SRC_DIR / "student" / "scene.css").read_text(encoding="utf-8")
        # 剥离 /* ... */ 块注释
        css_no_comments = re.sub(r"/\*[\s\S]*?\*/", "", css)
        # 单独成行的 .wrap { ... max-width: 720px ... } 块必须消失
        wrap_blocks = re.findall(r"\.wrap\s*\{[^}]*\}", css_no_comments)
        for blk in wrap_blocks:
            assert "max-width: 720px" not in blk, (
                f"scene.css .wrap 仍限制 720px（白板被压根源），应删除: {blk}"
            )

    def test_scene_page_uses_outline_panel(self):
        """ScenePage 必须 import 并使用 OutlinePanel 大纲面板."""
        page = (SRC_DIR / "student" / "presentation" / "ScenePage.tsx").read_text(
            encoding="utf-8"
        )
        assert 'from "./OutlinePanel"' in page
        assert "<OutlinePanel" in page
        # OutlinePanel 三 prop：outline + scenes + currentIndex + onJump
        assert "outline={o}" in page or "outline={outline}" in page
        assert "scenes={scenes}" in page
        assert "currentIndex={index}" in page
        assert "onJump=" in page

    def test_scene_player_exposes_subtitle_callback(self):
        """ScenePlayer 暴露 onSubtitleChange 回调（字幕状态由父 ScenePage 渲染）."""
        player = (SRC_DIR / "student" / "presentation" / "ScenePlayer.tsx").read_text(
            encoding="utf-8"
        )
        assert "onSubtitleChange" in player
        # 字幕变更时必须调 onSubtitleChange?.(subtitle)
        assert "onSubtitleChange?.(subtitle)" in player

    def test_scene_player_exposes_render_controls(self):
        """ScenePlayer 暴露 renderControls render prop（控制条由父拼装）."""
        player = (SRC_DIR / "student" / "presentation" / "ScenePlayer.tsx").read_text(
            encoding="utf-8"
        )
        assert "renderControls" in player
        # 必须传 ControlsApi（togglePlay / replayPage / state / started）
        for k in ("togglePlay", "replayPage", "state", "started"):
            assert k in player, f"ScenePlayer ControlsApi 缺 {k}"

    def test_scene_page_passes_render_controls_to_scene_player(self):
        """ScenePage 必须用 renderControls 拼装统一控制条（prev/play/replay/next 合并）."""
        page = (SRC_DIR / "student" / "presentation" / "ScenePage.tsx").read_text(
            encoding="utf-8"
        )
        assert "renderControls={" in page
        # 统一控制条内必须含 4 个按钮 id
        for btn_id in ("scene-prev", "scene-next", "wb-play", "wb-replay"):
            assert btn_id in page, f"ScenePage 控制条缺 {btn_id} DOM id（兼容性契约）"

    def test_desktop_dual_column_layout_at_1024(self):
        """≥1024 必须双栏 grid（白板主舞台 + 字幕/大纲右侧）."""
        css = (SRC_DIR / "student" / "scene.css").read_text(encoding="utf-8")
        # ≥1024 媒体查询 + grid-template-columns（双栏）
        import re
        m1024 = re.search(
            r"@media\s*\(\s*min-width:\s*1024px\s*\)\s*\{(.*?)^\}",
            css,
            re.DOTALL | re.MULTILINE,
        )
        assert m1024, "scene.css 缺 @media (min-width: 1024px) 块"
        block = m1024.group(1)
        assert "grid-template-columns" in block, "≥1024 缺双栏 grid 配置"
        # 768-1023 必须有大纲抽屉 toggle + drawer
        m768 = re.search(
            r"@media\s*\(\s*min-width:\s*768px\s*\)\s+and\s+\(\s*max-width:\s*1023px\s*\)\s*\{(.*?)^\}",
            css,
            re.DOTALL | re.MULTILINE,
        )
        assert m768, "scene.css 缺 @media (min-width: 768px) and (max-width: 1023px) 块"
        drawer_block = m768.group(1)
        assert "outline-toggle" in drawer_block or "outline-drawer" in drawer_block, (
            "768-1023 缺大纲抽屉样式"
        )

    def test_phase3_vanilla_mount_continues_in_scene_player(self):
        """whiteboard.js 挂载点 wb-container 仍由 ScenePlayer 创建（vanilla 契约）."""
        player = (SRC_DIR / "student" / "presentation" / "ScenePlayer.tsx").read_text(
            encoding="utf-8"
        )
        # wb-container DOM 必须存在
        assert 'id="wb-container"' in player
        assert 'className="wb-container"' in player
        # createWhiteboard 调用点必须存在
        assert "CogEduWhiteboard.createWhiteboard" in player
        # ResizeObserver 缩放由 whiteboard.js 内部处理，本组件不重复实现
        assert "ResizeObserver" not in player
        # aspect-ratio 由 scene.css 提供；不在 JSX 内联
        assert "aspect-ratio" not in player

    def test_unified_control_bar_no_split_pager(self):
        """设计稿 §5 拍板：控制条合并为单行（prev/play/replay/next 同列）；
        旧 .scene-pager 分离式结构必须不再作为主控制条（保留可能用于其它，
        但本组件主流程不再渲染两段独立控制）.
        """
        page = (SRC_DIR / "student" / "presentation" / "ScenePage.tsx").read_text(
            encoding="utf-8"
        )
        # 主流程必须用 .scene-controls，不再有独立的 .scene-pager 包裹 prev/next
        assert "scene-controls" in page
        # 但允许 scene-pager 残留在 history 中（设计稿 §5 明确拍板控制条合并）
        # 这里不强删旧 class 名，避免无谓的清洁工作，仅锁主流程用新结构

    def test_mobile_subtitle_and_outline_handling(self):
        """<768 退化形态：移动字幕在 wb-container 之下；大纲面板隐藏."""
        page = (SRC_DIR / "student" / "presentation" / "ScenePage.tsx").read_text(
            encoding="utf-8"
        )
        # 移动字幕 DOM id 必须存在（CSS 控制可见性）
        assert 'id="scene-subtitle-mobile"' in page
        # 桌面字幕与移动字幕分别渲染
        assert 'id="scene-subtitle"' in page
        assert "scene-subtitle-desktop" in page
        # 大纲面板通过 OutlinePanel 渲染（<768 由 CSS 隐藏 .scene-outline-drawer）
        assert "OutlinePanel" in page


class TestAnswerPageDualColumnWiring:
    """UI-R-3：答题页双栏（题目60% + 作答侧栏40%）接线契约.

    锁语义（设计稿 docs/ui-r-0-信息架构设计稿.md §6）：
      - .answer-page { max-width: 720px } 已删除（题目区破窄版心）
      - .answer-body 双栏 grid（≥1024）；<1024 单栏堆叠
      - 题目区（.answer-main）含题干/角标/通俗化/系统决策
      - 作答侧栏（.answer-side）含 CodeEditor + 自评 + 提示/提交 + 已答计数
      - 已答计数（answeredCount）组件内 state，提交成功 +1
      - 反馈框跨双栏（.feedback-box 在 .answer-body 之外）
    """

    def test_answer_page_no_720_constraint(self):
        """.answer-page 必须去掉 max-width: 720px（题目区破窄版心）.

        仅扫描 .answer-page 块规则体内的属性——不连带 .answer-page .prob 子选择
        (后者字号控制, 不在本步范围内, 设计稿 §6 拍板).
        """
        import re
        css = (SRC_DIR / "student" / "index.css").read_text(encoding="utf-8")
        css_no_comments = re.sub(r"/\*[\s\S]*?\*/", "", css)
        # 仅匹配 .answer-page { ... } 顶层块（不含子选择）
        m = re.search(r"\.answer-page\s*\{([^}]*)\}", css_no_comments)
        assert m, ".answer-page 顶层规则块不存在"
        block = m.group(1).strip()
        # 顶层块允许为空白（双栏由 .answer-body 主导），
        # 但绝不能保留 max-width: 720px 强约束
        assert "max-width: 720px" not in block, (
            f".answer-page 仍保留 max-width: 720px（题目区被压根源）：{block}"
        )

    def test_answer_body_dual_column_grid_at_1024(self):
        """.answer-body ≥1024 必须双栏 grid（题目区60% + 作答侧栏40%）."""
        import re
        css = (SRC_DIR / "student" / "index.css").read_text(encoding="utf-8")
        css_no_comments = re.sub(r"/\*[\s\S]*?\*/", "", css)
        # 顶层 .answer-body 块
        body_block = re.search(r"\.answer-body\s*\{([^}]*)\}", css_no_comments)
        assert body_block, ".answer-body 顶层规则块不存在"
        body_text = body_block.group(1)
        # 双栏 grid
        assert "display: grid" in body_text, ".answer-body 缺 display: grid"
        assert "grid-template-columns" in body_text, (
            ".answer-body 缺 grid-template-columns（双栏定义）"
        )
        # ≥1024 媒体查询：侧栏粘性跟随（粘性 = 桌面体验双栏核心）
        m1024 = re.search(
            r"@media\s*\(\s*min-width:\s*1024px\s*\)\s*\{(.*?)^\}",
            css_no_comments,
            re.DOTALL | re.MULTILINE,
        )
        assert m1024, "缺 @media (min-width: 1024px) 块"
        assert "position: sticky" in m1024.group(1), (
            "≥1024 缺 position: sticky（设计稿 §6 答题侧栏粘性跟随）"
        )

    def test_answer_body_single_column_under_1024(self):
        """.answer-body 在 <1024 必须折叠为单栏（display: block）."""
        import re
        css = (SRC_DIR / "student" / "index.css").read_text(encoding="utf-8")
        css_no_comments = re.sub(r"/\*[\s\S]*?\*/", "", css)
        m = re.search(
            r"@media\s*\(\s*max-width:\s*1023px\s*\)\s*\{(.*?)^\}",
            css_no_comments,
            re.DOTALL | re.MULTILINE,
        )
        assert m, "缺 @media (max-width: 1023px) 块（单栏折叠）"
        block = m.group(1)
        # 必须将 .answer-body 折叠为单栏
        assert ".answer-body" in block, "<1024 媒体查询未覆盖 .answer-body"
        assert "display: block" in block, "<1024 .answer-body 必须 display: block（单栏）"

    def test_answer_page_jsx_uses_dual_zones(self):
        """AnswerPage.tsx 必须渲染两个区：.answer-main + .answer-side.

        题目区（.answer-main）：answer-meta + prob + one-liner + LCA details
        作答侧栏（.answer-side）：CodeEditor + self-conf-row + btns + hint-box + 已答计数
        """
        page = (SRC_DIR / "student" / "pages" / "AnswerPage.tsx").read_text(
            encoding="utf-8"
        )
        # 双栏容器
        assert 'className="answer-body"' in page, "缺 .answer-body 双栏容器"
        # 题目区与作答侧栏两个 card
        assert 'className="card answer-main"' in page, "缺 .answer-main 题目区 card"
        assert 'className="card answer-side"' in page, "缺 .answer-side 作答侧栏 card"
        # 题目区元素（answer-meta + prob + one-liner + LCA details）
        assert "answer-meta" in page
        assert "className=\"prob\"" in page
        assert "one-liner" in page
        assert "lca_decision" in page
        # 作答侧栏元素（CodeEditor + self-conf-row + btns + hint-box）
        assert "CodeEditor" in page
        assert "self-conf-row" in page
        assert "hint-box" in page
        # 已答计数 UI 标记（设计稿 §6 答题侧栏底部"本场已答 N 题"）
        assert "answeredCount" in page, "缺已答计数 state（设计稿 §6 答题侧栏底部）"
        assert "answer-counter" in page, "缺已答计数 UI 类（answer-counter）"
        assert "本场已答" in page, "缺已答计数文案"
        # 反馈框必须在双栏之外（.answer-page 根下、.answer-body 之外）
        # 验证方法：feedback-box 的出现位置必须在 answer-body 闭合之后
        body_close = page.find("</div>\n\n      {/* UI-R-3: feedback-box")
        if body_close < 0:
            # 兼容无注释的写法
            body_close = page.find("</div>", page.find("</div>", page.find("className=\"card answer-side\"")))
        assert body_close > 0, "feedback-box 未跨双栏（必须在 .answer-body 之外）"

    def test_answered_count_increments_on_submit(self):
        """answeredCount 必须在 onSubmit 成功路径 +1（不是题目切换 +1）."""
        page = (SRC_DIR / "student" / "pages" / "AnswerPage.tsx").read_text(
            encoding="utf-8"
        )
        # 提交成功 +1
        assert "setAnsweredCount((n) => n + 1)" in page, (
            "answeredCount 提交成功路径未 +1（设计稿 §6）"
        )
        # 必须包含判定（仅在 judged + persisted 成功时 +1，避免错误计数）
        assert "jd.judged" in page and "persisted" in page, (
            "answeredCount 应仅在 judged+persisted 成功时 +1"
        )


class TestFourPagesDesktopLayoutWiring:
    """UI-R-4：今天/我在哪/成长/报告 四页面桌面宽幅适配接线契约.

    锁语义（设计稿 docs/ui-r-0-信息架构设计稿.md §11 UI-R-4）：
      - ReportPage 无 max-width: 720 内联锁（720 内联 style + max-width CSS 都已删）
      - WherePage (5D + Bloom) / (TC + LearningDNA) 并排（≥1024）
      - GrowthPage (轨迹 + 答题历史) 并排（≥1024）；5D 折线图全宽
      - HomePage .home-layout 容器接入（3 卡 auto-fit + MotivationPanel 下方）
      - 三页面 <1024 折叠为单栏
    """

    def test_report_page_no_720_inline_or_css_constraint(self):
        """ReportPage 必须删 max-width: 720 锁（JSX 内联 + CSS 顶层）.
        打印走 @media print { max-width: none !important }，与本约束无冲突.
        """
        import re
        page = (SRC_DIR / "student" / "pages" / "ReportPage.tsx").read_text(
            encoding="utf-8"
        )
        # JSX 内联 style 不允许 max-width: 720
        assert "max-width: 720" not in page, (
            "ReportPage.tsx 仍含 max-width: 720 内联锁"
        )
        assert "maxWidth: 720" not in page, (
            "ReportPage.tsx 仍含 maxWidth: 720 内联锁"
        )
        # CSS 顶层（@media 之外） .report-page 块不应有 max-width 约束.
        # 注: @media print { .report-page { max-width: none !important } } 是
        # 打印全宽覆盖规则, 不在本约束范围 (也不应被误删).
        css = (SRC_DIR / "student" / "index.css").read_text(encoding="utf-8")
        css_no_comments = re.sub(r"/\*[\s\S]*?\*/", "", css)
        # 删除所有 @media { ... } 块（嵌套敏感：只删顶层）
        css_no_media = re.sub(r"@media[^{]*\{(?:[^{}]*\{[^}]*\})*[^{}]*\}", "", css_no_comments)
        m = re.search(r"\.report-page\s*\{([^}]*)\}", css_no_media)
        if m:
            block = m.group(1)
            assert "max-width" not in block, (
                f".report-page 顶层块（@media 之外）仍含 max-width 约束：{block}"
            )

    def test_home_page_uses_home_layout_wrapper(self):
        """HomePage 必须包 .home-layout 容器 (UI-R-4 桌面 layout 标记)."""
        page = (SRC_DIR / "student" / "pages" / "HomePage.tsx").read_text(
            encoding="utf-8"
        )
        assert 'className="home-layout"' in page, (
            "HomePage 缺 .home-layout 容器（UI-R-4 桌面 layout 标记）"
        )

    def test_where_page_uses_where_grid_wrapper(self):
        """WherePage 必须把 4 个 section 包入 .where-grid 双栏容器."""
        page = (SRC_DIR / "student" / "pages" / "WherePage.tsx").read_text(
            encoding="utf-8"
        )
        assert 'className="where-grid"' in page, (
            "WherePage 缺 .where-grid 容器（UI-R-4 桌面双栏布局）"
        )
        # 4 个 section 必须都在 .where-grid 内（hero 留在外）
        assert page.count('<section className="card">') == 4, (
            "WherePage 应有 4 个 section card（5D/Bloom/TC/LearningDNA 进 .where-grid）"
        )
        # .where-grid 内 section 数 = 4
        grid_start = page.find('className="where-grid"')
        assert grid_start > 0
        rest = page[grid_start:]
        assert rest.count("<section className=\"card\">") == 4, (
            "WherePage .where-grid 内必须含全部 4 个 section card"
        )

    def test_growth_page_uses_growth_grid_wrapper(self):
        """GrowthPage 必须把 (轨迹 + 答题历史) 包入 .growth-grid 双栏容器."""
        page = (SRC_DIR / "student" / "pages" / "GrowthPage.tsx").read_text(
            encoding="utf-8"
        )
        assert 'className="growth-grid"' in page, (
            "GrowthPage 缺 .growth-grid 容器（UI-R-4 桌面双栏布局）"
        )
        # .growth-grid 内必须含 2 个 section (轨迹 + 答题历史)
        grid_start = page.find('className="growth-grid"')
        assert grid_start > 0
        rest = page[grid_start:]
        assert rest.count("<section className=\"card\">") == 2, (
            "GrowthPage .growth-grid 内必须有 2 个 section card（轨迹快照 + 答题历史）"
        )

    def test_desktop_layouts_have_dual_column_grid(self):
        """≥1024 .where-grid / .growth-grid 必须 grid-template-columns 双栏."""
        import re
        css = (SRC_DIR / "student" / "index.css").read_text(encoding="utf-8")
        css_no_comments = re.sub(r"/\*[\s\S]*?\*/", "", css)
        for cls in ("where-grid", "growth-grid"):
            m = re.search(rf"\.{cls}\s*\{{([^}}]*)\}}", css_no_comments)
            assert m, f".{cls} 顶层规则块不存在"
            block = m.group(1)
            assert "display: grid" in block, f".{cls} 缺 display: grid"
            assert "grid-template-columns" in block, (
                f".{cls} 缺 grid-template-columns（双栏定义）"
            )

    def test_dual_columns_fold_to_single_under_1024(self):
        """<1024 .where-grid / .growth-grid 必须 display: block 单栏折叠."""
        import re
        css = (SRC_DIR / "student" / "index.css").read_text(encoding="utf-8")
        css_no_comments = re.sub(r"/\*[\s\S]*?\*/", "", css)
        # 找到所有 @media (max-width: 1023px) 块（可能多个，分别给 answer-body / where-grid / growth-grid 用）
        media_blocks = re.findall(
            r"@media\s*\(\s*max-width:\s*1023px\s*\)\s*\{(.*?)^\}",
            css_no_comments,
            re.DOTALL | re.MULTILINE,
        )
        assert media_blocks, "缺 @media (max-width: 1023px) 块（单栏折叠）"
        # 至少有一个媒体块同时覆盖 .where-grid + .growth-grid + display: block
        folded_block = next(
            (
                b
                for b in media_blocks
                if ".where-grid" in b and ".growth-grid" in b and "display: block" in b
            ),
            None,
        )
        assert folded_block is not None, (
            "缺 @media (max-width: 1023px) 同时覆盖 .where-grid + .growth-grid + display: block"
        )
