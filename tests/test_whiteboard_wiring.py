"""3-B: 白板/播放前端接线 grep 契约 (对齐 test_presentation_events.py 模式).

守护"前端接线不能删": 行为本身由 node 测试 (tests/js/) 锁定, 本文件锁
vanilla 模块 (formula/playback/whiteboard.js, React 挂载式整合的依赖,
§10.1.3) 的静态接线 — 共享公式模块、LLM 文本安全约定。JS 侧无法进
pytest 行为断言的部分以此为防线。

双轨终点 (2026-09-16): legacy scene.html/scene.js 已删除, 页面级接线
锁由 tests/test_frontend_react_wiring.py 承接 (script 顺序/复看路由/
KaTeX 加载顺序等)。
"""
from __future__ import annotations

from pathlib import Path

WEB_STUDENT = Path(__file__).resolve().parents[1] / "web" / "student"


def _read(name: str) -> str:
    return (WEB_STUDENT / name).read_text(encoding="utf-8")


class TestFormulaSingleSourced:
    def test_kaTeX_rendering_only_in_formula_js(self):
        """3-B-2 "同一能力只写一次": renderToString 只允许出现在 formula.js."""
        assert "renderToString" in _read("formula.js")
        for name in ("playback.js", "whiteboard.js"):
            assert "renderToString" not in _read(name), f"{name} 不得再私有渲染公式"


class TestLlmTextSafety:
    def test_whiteboard_llm_text_via_textcontent(self):
        """wb_draw_text 的 LLM 文本必须 textContent, 不 innerHTML."""
        js = _read("whiteboard.js")
        assert "el.textContent = spec.text" in js

    def test_innerhtml_only_for_clear_and_katex_output(self):
        """innerHTML 仅两处合法: 容器清空 ('') 与 KaTeX 本地渲染产物."""
        for name in ("formula.js", "playback.js", "whiteboard.js"):
            for line in _read(name).splitlines():
                if ".innerHTML" in line and "= ''" not in line:
                    assert "katex" in line or "renderToString" in line, (
                        f"{name} 出现非法 innerHTML 赋值: {line.strip()}"
                    )


class TestKaTeXLocalVendor:
    """KaTeX 本地 vendor (2026-09-14): 替代 jsdelivr CDN——国内网络下 CDN
    加载失败会让全部公式降级源码直出 (3-G 验收实测暴露)."""

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

    def test_react_entries_reference_local_vendor(self):
        """三入口 html 均 use 本地 vendor 且无 CDN (React 侧的等价断言
        细节——加载顺序/defer——在 test_frontend_react_wiring.py)."""
        frontend = Path(__file__).resolve().parents[1] / "web" / "frontend"
        for entry in ("index.html", "student.html", "parent.html"):
            html = (frontend / entry).read_text(encoding="utf-8")
            assert "cdn.jsdelivr.net" not in html, entry
        # 学生入口是公式渲染的实际消费方
        student = (frontend / "student.html").read_text(encoding="utf-8")
        assert 'href="/vendor/katex/katex.min.css"' in student
        assert 'src="/vendor/katex/katex.min.js"' in student
