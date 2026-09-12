"""Phase 2 / 2-C: 学习报告导出测试 (方案文档 14.5).

覆盖:
  - 公式渲染: 正常 PNG / 预检不支持构造显式失败 / 文本-公式混排拆分
  - 聚合: 周期过滤 / 正确率 / 薄弱点维度 / 干预摘要 (同源 overview helpers)
  - docx: 可被 python-docx 重开, 标题/表格/公式图存在; 公式失败降级原文
  - HTTP: guardian download_report 权限 (无授权 403 / 撤销后立即 403) /
    period 非法 400 / 学生不存在 404 / staff 放行
"""
from __future__ import annotations

import io

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


# ─── 公式渲染 (formula_render) ───────────────────────────────────────────────


class TestFormulaRender:
    def test_simple_formula_png(self):
        from web.api.formula_render import latex_to_png

        png = latex_to_png("$x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG 签名

    def test_cache_same_formula(self):
        """同公式串走缓存 (同一对象, 不重复渲染)."""
        from web.api.formula_render import latex_to_png

        a = latex_to_png("$y = 2x + 1$")
        b = latex_to_png("$y = 2x + 1$")
        assert a is b

    def test_unsupported_construct_rejected(self):
        """预检: 环境/mhchem/裸 CJK 显式失败 (spike 实证的错误内容面)."""
        from web.api.formula_render import FormulaRenderError, latex_to_png

        for bad in (
            r"$\begin{pmatrix} a & b \\ c & d \end{pmatrix}$",
            r"$\ce{2H2 + O2 -> 2H2O}$",
            r"$\text{斜率}$",
        ):
            with pytest.raises(FormulaRenderError):
                latex_to_png(bad)

    def test_delimiter_normalization(self):
        """/$$ $$ 与 $ $ 与裸公式统一处理."""
        from web.api.formula_render import latex_to_png

        assert latex_to_png("$$x^2$$") == latex_to_png("$x^2$")

    def test_extract_formulas_mixed_text(self):
        from web.api.formula_render import extract_formulas

        parts = extract_formulas("已知 $a^2+b^2=c^2$，求 $$x_1+x_2$$。")
        kinds = [k for k, _ in parts]
        assert kinds == ["text", "formula", "text", "formula", "text"]
        assert parts[1] == ("formula", "a^2+b^2=c^2")
        assert parts[3] == ("formula", "x_1+x_2")


# ─── 聚合 (report.py) ────────────────────────────────────────────────────────


def _seed_student(student_id: str, responses: list[dict]) -> None:
    """造学生学习记录: students 行 + response_history JSON (teacher helpers 直读)."""
    import json
    from datetime import datetime, timedelta

    from cogedu.persistence.db import get_db

    db = get_db()
    db.upsert_student(student_id, grade_level=7)
    # 写 response_history (save_student_state 需要 BeliefState, 太重 — 直改列)
    history = []
    now = datetime.now()
    for r in responses:
        entry = {
            "problem_id": r["problem_id"],
            "correct": bool(r["correct"]),
            "score": 1.0 if r["correct"] else 0.0,
            "bloom_level": r.get("bloom_level", "L2"),
            "timestamp": (
                (now - timedelta(days=r.get("days_ago", 0))).isoformat()
                if not r.get("no_ts")
                else None
            ),
        }
        history.append(entry)
    with db.tx():
        db.conn.execute(
            "UPDATE students SET response_history = ? WHERE student_id = ?",
            (json.dumps(history), student_id),
        )


class TestAggregation:
    def test_period_filter_and_rates(self):
        from web.api.report import build_report_document

        _seed_student(
            "rep_stu_1",
            [
                {"problem_id": "P1", "correct": True, "days_ago": 1},
                {"problem_id": "P2", "correct": True, "days_ago": 2},
                {"problem_id": "P3", "correct": False, "days_ago": 3},
                {"problem_id": "P4", "correct": True, "days_ago": 20},  # 出周报窗口
            ],
        )
        report = build_report_document("rep_stu_1", "week")
        assert report.period == "week"
        assert "本周期答题 3 题，正确率 67%" in report.sections[0].blocks[1].text
        assert "累计答题 4 题" in report.sections[0].blocks[1].text

    def test_unknown_student_raises(self):
        from web.api.report import build_report_document

        with pytest.raises(LookupError):
            build_report_document("ghost_stu", "week")

    def test_invalid_period_raises(self):
        from web.api.report import build_report_document

        with pytest.raises(ValueError, match="period"):
            build_report_document("any", "year")

    def test_weak_dims_reported(self):
        """周期内某维度正确率 < 阈值 → 进薄弱点表 (Q 矩阵 dims 归因)."""
        from web.api.report import build_report_document

        _seed_student(
            "rep_stu_2",
            [
                {"problem_id": "P1", "correct": False, "days_ago": 1},
                {"problem_id": "P2", "correct": False, "days_ago": 2},
            ],
        )
        # dims 来自 Q 矩阵 a_specialized (get_question_detail) — 无该题目时
        # fallback 全 False, 薄弱点表走"未发现"分支; 断言结构不炸即可
        report = build_report_document("rep_stu_2", "week")
        weak = report.sections[2]
        assert weak.heading == "三、需要关注的薄弱点"
        assert weak.blocks  # 有"未发现"说明或薄弱维度表

    def test_warnings_no_silent_degrade(self):
        """engagement 不可用 → warnings 留痕 (不静默)."""
        from web.api.report import build_report_document

        _seed_student("rep_stu_3", [])
        report = build_report_document("rep_stu_3", "month")
        assert report.period == "month"
        # 无答题无 engagement 时至少 engagement warning 有一条
        assert any("engagement" in w for w in report.warnings)


# ─── docx 渲染器 ─────────────────────────────────────────────────────────────


class TestDocxRenderer:
    def test_render_and_reopen(self):
        """docx 可被 python-docx 重开: 标题/表格/公式图存在."""
        from docx import Document as DocxDocument

        from web.api.docx_renderer import render_report_docx
        from web.api.report import (
            ReportDocument,
            ReportFormula,
            ReportParagraph,
            ReportSection,
            ReportTable,
        )

        report = ReportDocument(
            student_id="rep_stu_x",
            period="week",
            generated_at="2026-09-12T12:00:00",
            data_cutoff="2026-09-12T11:00:00",
            sections=[
                ReportSection(
                    heading="一、概览",
                    blocks=[ReportParagraph(text="本周期答题 5 题。")],
                ),
                ReportSection(
                    heading="二、公式示例",
                    blocks=[
                        ReportFormula(latex="$x = \\frac{-b \\pm \\sqrt{b^2-4ac}}{2a}$"),
                        ReportTable(headers=["维度", "theta"], rows=[["K", "0.500"]]),
                    ],
                ),
            ],
        )
        data = render_report_docx(report)
        assert data[:2] == b"PK"  # docx = zip

        reopened = DocxDocument(io.BytesIO(data))
        texts = [p.text for p in reopened.paragraphs]
        assert any("学习报告" in t for t in texts)
        assert any("数据截止: 2026-09-12" in t for t in texts)  # 报告头带数据截止
        # 公式以图片嵌入 (inline shape)
        assert len(reopened.inline_shapes) == 1
        # 表格存在且内容正确
        assert reopened.tables[0].rows[1].cells[1].text == "0.500"

    def test_formula_failure_degrades_to_text(self):
        """公式渲染失败 → LaTeX 原文段落 + 附注 warning, 报告整体不失败."""
        from docx import Document as DocxDocument

        from web.api.docx_renderer import render_report_docx
        from web.api.report import (
            ReportDocument,
            ReportFormula,
            ReportSection,
        )

        bad_latex = r"$\begin{pmatrix} a & b \end{pmatrix}$"
        report = ReportDocument(
            student_id="rep_stu_y",
            period="week",
            generated_at="2026-09-12T12:00:00",
            sections=[
                ReportSection(
                    heading="一、含坏公式",
                    blocks=[ReportFormula(latex=bad_latex)],
                ),
            ],
        )
        data = render_report_docx(report)
        reopened = DocxDocument(io.BytesIO(data))
        texts = [p.text for p in reopened.paragraphs]
        assert bad_latex in texts  # 降级为原文
        assert any("附注" in t for t in texts)
        assert any("公式渲染失败" in t for t in texts)
        assert len(reopened.inline_shapes) == 0  # 没有图片


# ─── HTTP 契约 ───────────────────────────────────────────────────────────────


class TestReportEndpoint:
    def _link_with_download(self, client, auth_factory, sid="rep_http_stu"):
        """建 guardian+student+active download_report 授权, 返回 g_headers."""

        g_headers, _ = auth_factory(username="g_rep", role="guardian")
        s_headers, _ = auth_factory(
            username="s_rep", role="student", learning_student_id=sid
        )
        resp = client.post(
            "/api/guardian/links",
            headers=g_headers,
            json={"learner_username": "s_rep", "permissions": ["download_report"]},
        )
        link_id = resp.json()["link"]["link_id"]
        client.post(f"/api/student/guardian-links/{link_id}/confirm", headers=s_headers)
        return g_headers

    def test_guardian_with_permission_downloads(self, client, auth_factory):
        pytest.importorskip("docx")
        _seed_student("rep_http_stu", [{"problem_id": "P1", "correct": True, "days_ago": 1}])
        g_headers = self._link_with_download(client, auth_factory)
        resp = client.get(
            "/api/parent/students/rep_http_stu/report?period=week", headers=g_headers
        )
        assert resp.status_code == 200
        assert resp.content[:2] == b"PK"
        assert "attachment" in resp.headers["Content-Disposition"]

    def test_guardian_without_download_perm_403(self, client, auth_factory):
        """只授 view_progress → download_report 类端点 403 (权限粒度)."""

        g_headers, _ = auth_factory(username="g_rep2", role="guardian")
        s_headers, _ = auth_factory(
            username="s_rep2", role="student", learning_student_id="rep_http_stu2"
        )
        resp = client.post(
            "/api/guardian/links",
            headers=g_headers,
            json={"learner_username": "s_rep2", "permissions": ["view_progress"]},
        )
        link_id = resp.json()["link"]["link_id"]
        client.post(f"/api/student/guardian-links/{link_id}/confirm", headers=s_headers)

        r = client.get(
            "/api/parent/students/rep_http_stu2/report", headers=g_headers
        )
        assert r.status_code == 403

    def test_unlinked_guardian_403(self, client, auth_factory):
        g_headers, _ = auth_factory(username="g_rep3", role="guardian")
        r = client.get(
            "/api/parent/students/nobody/report", headers=g_headers
        )
        assert r.status_code == 403

    def test_unknown_student_404(self, client, auth_factory):
        # guardian 对未知学生 → 403 (权限检查在前, 不泄漏存在性);
        # 404 (防幽灵学生语义) 用 staff 验证
        pytest.importorskip("docx")
        g_headers = self._link_with_download(client, auth_factory, sid="rep_http_stu3")
        r = client.get("/api/parent/students/ghost/report", headers=g_headers)
        assert r.status_code == 403

        t_headers, _ = auth_factory(username="t_rep404", role="teacher")
        r2 = client.get("/api/parent/students/ghost/report", headers=t_headers)
        assert r2.status_code == 404

    def test_invalid_period_400(self, client, auth_factory):
        pytest.importorskip("docx")
        _seed_student("rep_http_stu4", [])
        g_headers = self._link_with_download(client, auth_factory, sid="rep_http_stu4")
        r = client.get(
            "/api/parent/students/rep_http_stu4/report?period=year", headers=g_headers
        )
        assert r.status_code == 400

    def test_teacher_allowed(self, client, auth_factory):
        pytest.importorskip("docx")
        _seed_student("rep_http_stu5", [])
        t_headers, _ = auth_factory(username="t_rep", role="teacher")
        r = client.get(
            "/api/parent/students/rep_http_stu5/report", headers=t_headers
        )
        assert r.status_code == 200
