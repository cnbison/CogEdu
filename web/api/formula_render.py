"""2-C-1/2-C-3 (Phase 2, 14.5): LaTeX 公式 → PNG 渲染 (matplotlib mathtext).

v1 决策 (方案文档 14.5): 公式导出用"渲染成图片嵌入"方案 (简单可靠,
导出后不可编辑); mathml2omml 可编辑公式链路排 v2。渲染引擎选
matplotlib mathtext — 离线、无 headless browser。

spike 结论 (scripts/spike_mathtext_formula.py, 2026-09-12, 33 样本):
  - Phase 1 prompt 约束形态 5/5、K12 典型公式 21/21 通过
  - 失败面: \\begin{...} 环境、\\ce{} (mhchem)、$$ 未剥离 → 本模块预检
    已知不支持构造, 显式失败 (调用方降级), 不产出错误内容的图
  - 两个实测坑 (spike 记录): ① math_to_image 必须保留 $...$ 定界符,
    剥离后整串按普通文本渲染 (不报错但内容错误); ② mathtext 对不支持
    的命令有的抛 ParseFatalException、有的静默按字面输出 — 预检优先于
    依赖解析异常
  - 已知限制: 公式内 CJK 字形缺失时渲染占位方块 (不报错) — 预检一并拒绝
"""

from __future__ import annotations

import io
import logging
import re
from functools import lru_cache

_log = logging.getLogger(__name__)

# 预检: mathtext 已知不支持/内容会错的构造 (spike 实证)
_UNSUPPORTED_PATTERNS = (
    re.compile(r"\\begin\{"),     # LaTeX 环境 (pmatrix/cases/align...)
    re.compile(r"\\ce\{"),        # mhchem 化学宏
    re.compile(r"\\operatorname"),  # mathtext 不支持 (spike: 按字面输出)
    re.compile(r"[\u4e00-\u9fff]"),  # CJK 字形缺失 → 占位方块
)


class FormulaRenderError(ValueError):
    """公式渲染失败 (调用方降级为 LaTeX 原文 + warning 留痕)."""


@lru_cache(maxsize=256)
def latex_to_png(latex: str, dpi: int = 200) -> bytes:
    """LaTeX 公式串 → PNG bytes. 失败抛 FormulaRenderError.

    lru_cache: 同一公式串 (同一报告内重复出现) 只渲染一次;
    bytes 不可变, 缓存安全。dpi=200 保证 Word 里缩放后清晰。
    """
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import mathtext

    # 定界符归一: $$...$$ / $...$ / 裸公式 → 统一为 mathtext 需要的
    # 单层 $...$ (spike 坑①: 必须有定界符)
    inner = latex.strip()
    if inner.startswith("$$") and inner.endswith("$$"):
        inner = inner[2:-2].strip()
    elif inner.startswith("$") and inner.endswith("$"):
        inner = inner[1:-1].strip()
    if not inner:
        raise FormulaRenderError("空公式")

    for pattern in _UNSUPPORTED_PATTERNS:
        if pattern.search(inner):
            raise FormulaRenderError(
                f"mathtext 不支持的构造: {pattern.pattern} (降级为原文)"
            )

    buf = io.BytesIO()
    try:
        mathtext.math_to_image(f"${inner}$", buf, dpi=dpi, format="png")
    except Exception as e:
        raise FormulaRenderError(f"mathtext 渲染失败: {e}") from e
    data = buf.getvalue()
    if len(data) < 100:
        # 防御性自检: 异常小的 PNG 视为失败 (不嵌入可疑内容)
        raise FormulaRenderError(f"渲染产物异常 (PNG {len(data)}B)")
    return data


def extract_formulas(text: str) -> list[tuple[str, str]]:
    """从文本提取公式段: 返回 [(类型标记, 内容)] 有序序列.

    类型: "text" (普通文本段) / "formula" ($...$ 或 $$...$$ 公式)。
    用于把含公式的题目文本/讲解文本拆成 docx 可渲染的块序列。
    """
    parts: list[tuple[str, str]] = []
    pos = 0
    # $$ 优先匹配 (避免被两个 $...$ 误切)
    pattern = re.compile(r"\$\$(.+?)\$\$|\$(.+?)\$", re.DOTALL)
    for m in pattern.finditer(text):
        if m.start() > pos:
            parts.append(("text", text[pos : m.start()]))
        formula = (m.group(1) or m.group(2) or "").strip()
        if formula:
            parts.append(("formula", formula))
        pos = m.end()
    if pos < len(text):
        parts.append(("text", text[pos:]))
    return parts
