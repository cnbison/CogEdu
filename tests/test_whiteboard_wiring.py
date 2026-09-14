"""3-B: 白板/播放前端接线 grep 契约 (对齐 test_presentation_events.py 模式).

守护"前端接线不能删": 行为本身由 node 测试 (tests/js/) 锁定, 本文件锁
HTML/JS 之间的静态接线 — script 加载顺序、翻页联动、共享公式模块、
LLM 文本安全约定。JS 侧无法进 pytest 行为断言的部分以此为防线。
"""
from __future__ import annotations

from pathlib import Path

WEB_STUDENT = Path(__file__).resolve().parents[1] / "web" / "student"


def _read(name: str) -> str:
    return (WEB_STUDENT / name).read_text(encoding="utf-8")


class TestScriptLoadOrder:
    def test_scene_html_loads_playback_scripts_before_scene_js(self):
        """defer 按文档顺序执行: formula → playback → whiteboard → scene."""
        html = _read("scene.html")
        positions = [
            html.index('src="/student/formula.js'),
            html.index('src="/student/playback.js'),
            html.index('src="/student/whiteboard.js'),
            html.index('src="/student/scene.js'),
        ]
        assert positions == sorted(positions), "依赖脚本必须先于 scene.js 加载"

    def test_all_playback_scripts_are_deferred(self):
        html = _read("scene.html")
        for name in ("formula.js", "playback.js", "whiteboard.js", "scene.js"):
            line = next(l for l in html.splitlines() if f"/student/{name}" in l)
            assert "defer" in line, f"{name} 必须 defer (依赖文档顺序执行)"


class TestSceneJsWiring:
    def test_page_change_stops_engine(self):
        """3-C-4 翻页联动: showScene 必须先 stopPlayback (令牌失效+音频停止)."""
        js = _read("scene.js")
        assert "function stopPlayback()" in js
        assert "engine.stop()" in js
        show_scene = js[js.index("function showScene"):]
        assert "stopPlayback()" in show_scene[:400], "showScene 开头必须调 stopPlayback"

    def test_playback_guards_on_actions(self):
        """actions 为 null (Phase 1 旧场景) 不得触发播放接线."""
        js = _read("scene.js")
        assert "scene.actions && scene.actions.length" in js
        assert "setupPlayback(" in js

    def test_engine_gets_whiteboard_renderer(self):
        js = _read("scene.js")
        assert "renderer: wb.renderer" in js
        assert "CogEduPlayback.createPlaybackEngine" in js
        assert "CogEduWhiteboard.createWhiteboard" in js


class TestFormulaSingleSourced:
    def test_kaTeX_rendering_only_in_formula_js(self):
        """3-B-2 "同一能力只写一次": renderToString 只允许出现在 formula.js."""
        assert "renderToString" in _read("formula.js")
        for name in ("scene.js", "whiteboard.js"):
            assert "renderToString" not in _read(name), f"{name} 不得再私有渲染公式"

    def test_scene_js_uses_shared_module(self):
        js = _read("scene.js")
        assert "CogEduFormula.renderFormulaInto" in js


class TestLlmTextSafety:
    def test_whiteboard_llm_text_via_textcontent(self):
        """wb_draw_text 的 LLM 文本必须 textContent, 不 innerHTML."""
        js = _read("whiteboard.js")
        assert "el.textContent = spec.text" in js

    def test_innerhtml_only_for_clear_and_katex_output(self):
        """innerHTML 仅两处合法: 容器清空 ('') 与 KaTeX 本地渲染产物."""
        for name in ("scene.js", "whiteboard.js", "formula.js"):
            for line in _read(name).splitlines():
                if ".innerHTML" in line and "= ''" not in line:
                    assert "katex" in line or "renderToString" in line, (
                        f"{name} 出现非法 innerHTML 赋值: {line.strip()}"
                    )


class TestKaTeXLocalVendor:
    """KaTeX 本地 vendor (2026-09-14): 替代 jsdelivr CDN——国内网络下 CDN
    加载失败会让全部公式降级源码直出 (3-G 验收实测暴露)."""

    def test_scene_html_references_local_vendor(self):
        html = _read("scene.html")
        assert 'href="/vendor/katex/katex.min.css"' in html
        assert 'src="/vendor/katex/katex.min.js"' in html
        assert "cdn.jsdelivr.net" not in html

    def test_vendor_files_exist_and_served(self):
        import os

        from fastapi.testclient import TestClient

        from web.api.app import app

        vendor = Path(__file__).resolve().parents[1] / "web" / "vendor" / "katex"
        assert (vendor / "katex.min.js").is_file()
        assert (vendor / "katex.min.css").is_file()
        assert any(f.endswith(".woff2") for f in os.listdir(vendor / "fonts"))
        client = TestClient(app)
        assert client.get("/vendor/katex/katex.min.js").status_code == 200
        font = next(f for f in os.listdir(vendor / "fonts") if f.endswith(".woff2"))
        assert client.get(f"/vendor/katex/fonts/{font}").status_code == 200
        assert client.get("/vendor/katex/../auth.js").status_code == 404  # 穿越防护
