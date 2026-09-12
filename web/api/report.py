"""2-C-2 (Phase 2, 14.5): 学习报告内容结构层 — 周期聚合 + ReportDocument.

框架无关 (不绑 docx): 聚合逻辑产出结构化 ReportDocument, docx 渲染器
(web/api/docx_renderer.py) 只做 ReportDocument → 文件的翻译。聚合与
overview 接口**同源取数** (同一批 teacher/parent helpers), 保证家长在
报告里看到的数字和 overview 一致, 不各算各的。

周期: week = 近 7 天, month = 近 30 天 (按 response_history 的
timestamp 过滤; 无 timestamp 的历史条目不计入周期, 计入累计)。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from web.api import parent as parent_helpers
from web.api import teacher as teacher_helpers

_log = logging.getLogger(__name__)

PERIODS = ("week", "month")
_PERIOD_DAYS = {"week": 7, "month": 30}

# 薄弱点判定: 周期内该维度答题数 ≥ 此值且正确率 < 此阈值才进报告
_WEAK_MIN_ANSWERS = 2
_WEAK_RATE_THRESHOLD = 0.6
_WEAK_TOP_N = 3

# 5D 维度名 (与 teacher._parse_theta 同序; 字母口径沿内核)
_DIM_NAMES = ("K", "P", "S", "C", "X")
_BLOOM_NAMES = {
    "L1": "记忆",
    "L2": "理解",
    "L3": "应用",
    "L4": "分析",
    "L5": "评价",
    "L6": "创造",
}


# ─── ReportDocument 结构 (不绑 docx) ─────────────────────────────────────────


class ReportParagraph(BaseModel):
    type: Literal["paragraph"] = "paragraph"
    text: str


class ReportTable(BaseModel):
    type: Literal["table"] = "table"
    headers: list[str]
    rows: list[list[str]]


class ReportFormula(BaseModel):
    """公式块: docx 渲染时转 PNG; 失败降级为 LaTeX 原文 + warning."""

    type: Literal["formula"] = "formula"
    latex: str


ReportBlock = ReportParagraph | ReportTable | ReportFormula


class ReportSection(BaseModel):
    heading: str
    blocks: list[ReportBlock] = Field(default_factory=list)


class ReportDocument(BaseModel):
    student_id: str
    period: str  # week / month
    generated_at: str
    data_cutoff: str | None = None  # 数据截止 (students.last_active_at)
    sections: list[ReportSection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)  # 聚合层降级留痕


# ─── 聚合 ────────────────────────────────────────────────────────────────────


def _period_cutoff(period: str, now: datetime) -> datetime:
    return now - timedelta(days=_PERIOD_DAYS[period])


def _in_period(ts: str | None, cutoff: datetime) -> bool:
    if not ts:
        return False
    try:
        # response_history 的时间戳是 naive 本地 ISO (仓库 12.5 口径);
        # aware 时间戳剥离 tzinfo 再比 (统一 naive 语义)
        ts_dt = datetime.fromisoformat(ts)
        if ts_dt.tzinfo is not None:
            ts_dt = ts_dt.replace(tzinfo=None)
        return ts_dt >= cutoff
    except (ValueError, TypeError):
        return False


def _rate(correct: int, total: int) -> str:
    return f"{correct / total:.0%}" if total else "—"


def build_report_document(
    student_id: str,
    period: str,
    now: datetime | None = None,
) -> ReportDocument:
    """聚合学生学习数据 → ReportDocument (与 overview 接口同源取数).

    Raises:
        LookupError: 学生学习记录不存在 (路由层转 404, 防幽灵学生语义)。
        ValueError: period 非法。
    """
    if period not in PERIODS:
        raise ValueError(f"period 需为 {'/'.join(PERIODS)}")
    # naive 本地时间口径 — response_history 时间戳 naive ISO (仓库 12.5 惯例)
    now = now or datetime.now()
    cutoff = _period_cutoff(period, now)

    row = teacher_helpers._load_student_row(student_id)
    if row is None:
        raise LookupError(f"学生不存在: {student_id}")

    responses = teacher_helpers._parse_responses(student_id)
    period_resp = [r for r in responses if _in_period(r.get("timestamp"), cutoff)]
    theta = teacher_helpers._parse_theta(row) or {}
    bloom = teacher_helpers._parse_bloom_summary(row)
    misconceptions = teacher_helpers._parse_misconceptions(student_id)
    interventions = teacher_helpers._get_intervention_history(student_id)
    engagement = parent_helpers._get_engagement_report(student_id)

    warnings: list[str] = []
    sections: list[ReportSection] = []

    # ── 一、本周期学习进度概览 ────────────────────────────────────────────
    period_total = len(period_resp)
    period_correct = sum(1 for r in period_resp if r["correct"])
    all_total = len(responses)
    all_correct = sum(1 for r in responses if r["correct"])
    current_state = (engagement or {}).get("current_state")

    overview_lines = [
        f"报告周期: 近 {_PERIOD_DAYS[period]} 天"
        f"（{cutoff.date().isoformat()} ~ {now.date().isoformat()}）",
        f"本周期答题 {period_total} 题，正确率 {_rate(period_correct, period_total)}；"
        f"累计答题 {all_total} 题，累计正确率 {_rate(all_correct, all_total)}。",
    ]
    if current_state:
        overview_lines.append(f"当前学习状态: {current_state}")
    else:
        warnings.append("engagement 报告不可用 (LCA 状态缺失或派生失败)")
    if bloom and bloom.get("dominant"):
        overview_lines.append(
            f"当前主导 Bloom 层级: {bloom['dominant']}"
            f"（{_BLOOM_NAMES.get(str(bloom['dominant']), '')}）"
        )

    sections.append(
        ReportSection(
            heading="一、本周期学习进度概览",
            blocks=[ReportParagraph(text=t) for t in overview_lines],
        )
    )

    # ── 二、关键知识点掌握情况 ────────────────────────────────────────────
    kb_blocks: list[ReportBlock] = []
    # Bloom 六层 (当前画像, overview 同源)
    if bloom and bloom.get("levels"):
        kb_blocks.append(ReportParagraph(text="Bloom 认知层级画像:"))
        kb_blocks.append(
            ReportTable(
                headers=["层级", "含义", "掌握度"],
                rows=[
                    [level, _BLOOM_NAMES[level], f"{bloom['levels'].get(level, 0.0):.0%}"]
                    for level in ("L1", "L2", "L3", "L4", "L5", "L6")
                ],
            )
        )
    else:
        warnings.append("Bloom 画像缺失, 掌握情况表跳过")
    # 5D theta (当前画像, overview 同源)
    if theta:
        kb_blocks.append(ReportParagraph(text="五维能力画像 (theta, 越高越强):"))
        kb_blocks.append(
            ReportTable(
                headers=["维度", "theta"],
                rows=[[dim, f"{theta.get(dim, 0.0):.3f}"] for dim in _DIM_NAMES],
            )
        )
    sections.append(ReportSection(heading="二、关键知识点掌握情况", blocks=kb_blocks))

    # ── 三、需要关注的薄弱点 ──────────────────────────────────────────────
    weak_blocks: list[ReportBlock] = []
    # 维度级正确率 (周期内, 按 Q 矩阵 a_specialized 维度加载归因)
    dim_stats: dict[int, list[bool]] = {i: [] for i in range(5)}
    for r in period_resp:
        for i, loaded in enumerate(r.get("dims") or [False] * 5):
            if loaded:
                dim_stats[i].append(bool(r["correct"]))
    weak_dims = []
    for dim, marks in dim_stats.items():
        total = len(marks)
        if total < _WEAK_MIN_ANSWERS:
            continue
        correct = sum(marks)
        if correct / total < _WEAK_RATE_THRESHOLD:
            weak_dims.append((dim, correct, total))
    weak_dims.sort(key=lambda x: x[1] / x[2])
    weak_dims = weak_dims[:_WEAK_TOP_N]
    if weak_dims:
        weak_blocks.append(ReportParagraph(text="周期内正确率偏低的维度:"))
        weak_blocks.append(
            ReportTable(
                headers=["维度", "答题数", "正确率"],
                rows=[
                    [_DIM_NAMES[dim], str(total), _rate(correct, total)]
                    for dim, correct, total in weak_dims
                ],
            )
        )
    else:
        weak_blocks.append(
            ReportParagraph(text="周期内未发现明显薄弱维度 (答题量不足或正确率均达标)。")
        )
    # 最近误概念 (全部历史取前 3, 不按周期过滤 — 干预参考价值不随周期过期)
    if misconceptions:
        misc_lines = [
            f"{m['misc_id']}（置信度 {m['confidence']:.2f}, {str(m.get('timestamp') or '')[:10]}）"
            for m in misconceptions[:3]
        ]
        weak_blocks.append(ReportParagraph("最近检出的误解: " + "; ".join(misc_lines)))
    sections.append(ReportSection(heading="三、需要关注的薄弱点", blocks=weak_blocks))

    # ── 四、本周期教学干预摘要 ────────────────────────────────────────────
    period_interv = [
        iv
        for iv in interventions
        if _in_period(str(iv.get("timestamp") or ""), cutoff)
    ]
    if period_interv:
        rows = [
            [
                str(iv.get("timestamp") or "")[:10],
                str(iv.get("intervention_type") or ""),
                str(iv.get("rationale_text") or "")[:60],
            ]
            for iv in period_interv[:5]
        ]
        sections.append(
            ReportSection(
                heading="四、本周期教学干预摘要",
                blocks=[
                    ReportParagraph(text=f"共 {len(period_interv)} 次干预 (最多列 5 条):"),
                    ReportTable(headers=["日期", "类型", "理由"], rows=rows),
                ],
            )
        )
    else:
        sections.append(
            ReportSection(
                heading="四、本周期教学干预摘要",
                blocks=[ReportParagraph(text="本周期无教学干预记录。")],
            )
        )

    return ReportDocument(
        student_id=student_id,
        period=period,
        generated_at=now.isoformat(),
        data_cutoff=row.get("last_active_at"),
        sections=sections,
        warnings=warnings,
    )
