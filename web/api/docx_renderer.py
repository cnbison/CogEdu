"""2-C-3 (Phase 2, 14.5): ReportDocument → Word (docx) 渲染器.

只做翻译, 不算数 — 聚合在 web/api/report.py (同源 overview)。
公式块 → mathtext PNG 嵌入 (formula_render.latex_to_png, lru_cache 按
公式串去重); **单条公式渲染失败降级为 LaTeX 原文段落 + warning 留痕**,
不让整份报告失败 (仓库"宁可明确降级不静默"约定)。

报告头尾带生成时间 + 数据截止时间 — 家长看到的数字要能对上"哪天的状态"。
"""

from __future__ import annotations

import io
import logging

from web.api.formula_render import FormulaRenderError, extract_formulas, latex_to_png
from web.api.report import (
    ReportDocument,
    ReportFormula,
    ReportParagraph,
    ReportTable,
)

_log = logging.getLogger(__name__)


def _add_text_with_formulas(doc, text: str, warnings: list[str]) -> None:
    """段落写入, 内嵌 $...$/$$...$$ 公式按 formula 块渲染.

    场景/题面文本是"文字 + 行内公式"混排 — 拆成 文字段/公式段 序列,
    公式独占一行居中 (v1 不做行内图文混排, docx 行内图片基线对齐难看)。
    """
    for kind, content in extract_formulas(text):
        if kind == "text" and content.strip():
            doc.add_paragraph(content.strip())
        elif kind == "formula":
            _add_formula(doc, ReportFormula(latex=content), warnings)


def _add_formula(doc, block: ReportFormula, warnings: list[str]) -> None:
    """公式块 → PNG 居中嵌入; 失败降级 LaTeX 原文 + warning 留痕."""
    try:
        png = latex_to_png(block.latex)
    except FormulaRenderError as e:
        warnings.append(f"公式渲染失败, 保留原文: {block.latex} ({e})")
        doc.add_paragraph(block.latex)
        return
    stream = io.BytesIO(png)
    # 宽度按原图比例缩到 14cm 内 (A4 正文宽), Word 里等比清晰
    paragraph = doc.add_paragraph()
    paragraph.alignment = 1  # WD_ALIGN_PARAGRAPH.CENTER
    run = paragraph.add_run()
    try:
        run.add_picture(stream, width=min(14.0, _png_width_inches(png)))
    except Exception:
        # 尺寸探测失败不阻塞 — 用固定宽度兜底
        _log.warning("公式 PNG 尺寸探测失败, 用默认宽度", exc_info=True)
        stream.seek(0)
        run.add_picture(stream, width=6.0)


def _png_width_inches(png: bytes) -> float:
    """读 PNG IHDR 像素宽 + spike 同款 dpi → 英寸 (限制过大公式)."""
    import struct

    # PNG: 8B 签名 + 4B len + 4B "IHDR" + 4B width + 4B height
    width_px = struct.unpack(">I", png[16:20])[0]
    dpi = 200.0
    return width_px / dpi


def render_report_docx(report: ReportDocument) -> bytes:
    """ReportDocument → docx bytes."""
    import docx
    from docx.shared import Pt

    doc = docx.Document()
    warnings: list[str] = list(report.warnings)

    # ── 报告头 ────────────────────────────────────────────────────────────
    title = doc.add_heading(f"学习报告（{report.period}）", level=0)
    for run in title.runs:
        run.font.size = Pt(20)
    meta_lines = [f"学生: {report.student_id}"]
    if report.data_cutoff:
        meta_lines.append(f"数据截止: {str(report.data_cutoff)[:19]}")
    meta_lines.append(f"报告生成时间: {str(report.generated_at)[:19]}")
    for line in meta_lines:
        p = doc.add_paragraph(line)
        for run in p.runs:
            run.font.size = Pt(9)

    # ── 正文 ──────────────────────────────────────────────────────────────
    for section in report.sections:
        doc.add_heading(section.heading, level=1)
        for block in section.blocks:
            if isinstance(block, ReportParagraph):
                _add_text_with_formulas(doc, block.text, warnings)
            elif isinstance(block, ReportTable):
                table = doc.add_table(
                    rows=1 + len(block.rows), cols=len(block.headers)
                )
                table.style = "Light Grid Accent 1"
                for col, header in enumerate(block.headers):
                    cell = table.rows[0].cells[col]
                    cell.text = header
                    for run in cell.paragraphs[0].runs:
                        run.bold = True
                for r, row_vals in enumerate(block.rows, start=1):
                    for c, val in enumerate(row_vals):
                        table.rows[r].cells[c].text = str(val)
            elif isinstance(block, ReportFormula):
                _add_formula(doc, block, warnings)

    # ── 报告尾 ────────────────────────────────────────────────────────────
    if warnings:
        doc.add_heading("附注", level=1)
        for w in warnings:
            doc.add_paragraph(f"· {w}")
    footer = doc.add_paragraph(
        "本报告由 CogEdu 学习系统基于学生答题与认知状态数据自动生成。"
    )
    for run in footer.runs:
        run.font.size = Pt(9)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
