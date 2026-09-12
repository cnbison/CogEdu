"""2-C-1 (Phase 2, 14.5): 公式渲染 spike — matplotlib mathtext 可行性验证.

背景: 学习报告导出 (Word/docx) 需要把 Scene 里的 LaTeX 公式渲染成图片
嵌入 (v1 决策: 公式不可编辑, mathml2omml 可编辑链路排 v2)。候选方案
matplotlib mathtext (离线、无 headless browser、numpy 系依赖已入库) 的
已知风险: mathtext 不是完整 LaTeX (不支持 \\begin{...} 环境和部分宏)。

样本集说明 (诚实来源记录):
  - Phase 1 灰度 (1-G) 的真实 LLM 产出在 tmp canary 库里, 未存档入仓,
    无法直接回放。本 spike 的样本按两个来源构建:
    a) phase1-prompt-style: Phase 1 prompt 已锁定的公式形态约束
       ($...$/$$...$$ 行内/行间公式) 下的典型输出形状;
    b) k12-typical / risk-construct: K12 数理化典型公式 + 已知 mathtext
       风险构造 (环境、\\text、\\operatorname 等), 用于摸清降级面。
  - Phase 5 接入真实题库/教材后, 应用真实样本回归本 spike (重跑本脚本)。

用法: python scripts/spike_mathtext_formula.py
输出: 逐样本渲染结果 + 分类统计 + 主方案建议。
"""
from __future__ import annotations

import io
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use("Agg")  # 无显示环境渲染
from matplotlib import mathtext  # noqa: E402


class GlyphWarningError(Exception):
    """渲染成功但字形缺失 (如 CJK) — 内容降级信号, 单独归类."""

# (tag, latex) — tag ∈ phase1-prompt-style / k12-typical / risk-construct
SAMPLES: list[tuple[str, str]] = [
    # ── a) Phase 1 prompt 约束下的典型输出形态 (scene 文本里 $...$ 包裹) ──
    ("phase1-prompt-style", r"$x^2$"),
    ("phase1-prompt-style", r"$y = 2x^2 - 3x + 1$"),
    ("phase1-prompt-style", r"$y = ax^2 + bx + c$"),
    ("phase1-prompt-style", r"$a \neq 0$"),
    ("phase1-prompt-style", r"$\Delta = b^2 - 4ac$"),
    # ── b) K12 数理化典型公式 ──
    ("k12-typical", r"$x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$"),  # 求根公式
    ("k12-typical", r"$\frac{1}{2}mv^2 = mgh$"),  # 机械能守恒
    ("k12-typical", r"$F = ma$"),
    ("k12-typical", r"$pv = nRT$"),
    ("k12-typical", r"$a_n = a_1 + (n-1)d$"),  # 等差数列
    ("k12-typical", r"$S_n = \frac{n(a_1 + a_n)}{2}$"),
    ("k12-typical", r"$\sin^2\theta + \cos^2\theta = 1$"),
    ("k12-typical", r"$\vec{F} = m\vec{a}$"),
    ("k12-typical", r"$H_2O$"),
    ("k12-typical", r"$2H_2 + O_2 \rightarrow 2H_2O$"),
    ("k12-typical", r"$\sqrt{2} \approx 1.414$"),
    ("k12-typical", r"$\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$"),
    ("k12-typical", r"$\int_0^1 x^2\,dx = \frac{1}{3}$"),
    ("k12-typical", r"$\lim_{x \to 0} \frac{\sin x}{x} = 1$"),
    ("k12-typical", r"$\log_2 8 = 3$"),
    ("k12-typical", r"$\angle A + \angle B = 180^\circ$"),
    ("k12-typical", r"$\triangle ABC \sim \triangle DEF$"),
    ("k12-typical", r"$\pi \approx 3.14159$"),
    ("k12-typical", r"$\alpha + \beta = \gamma$"),
    ("k12-typical", r"$\hat{y} = kx + b$"),
    ("k12-typical", r"$\overline{AB} \parallel \overline{CD}$"),
    # ── c) 已知风险构造 (预期部分失败 — 摸清降级面) ──
    ("risk-construct", r"$\begin{pmatrix} a & b \\ c & d \end{pmatrix}$"),  # 矩阵环境
    ("risk-construct", r"$\begin{cases} x = 1 \\ y = 2 \end{cases}$"),  # 方程组环境
    ("risk-construct", r"$\text{斜率}$"),  # \text + 中文
    ("risk-construct", r"$\operatorname{sgn}(x)$"),  # \operatorname
    ("risk-construct", r"$\ce{2H2 + O2 -> 2H2O}$"),  # mhchem 化学宏
    ("risk-construct", r"$$\frac{a}{b}$$"),  # 行间定界符 (应剥离后可渲染)
    ("risk-construct", r"$x_i^2 + y_1$"),  # 上下标混合
]


def render(latex: str, dpi: float = 200.0) -> bytes:
    """LaTeX → PNG bytes (mathtext, Agg). 失败抛异常由调用方统计.

    注意 (spike 实测踩坑): math_to_image 需要保留 $...$ 定界符 —
    剥离后整串按普通文本渲染 (反斜杠原样输出), 不报错但内容错误。
    """
    buf = io.BytesIO()
    # math_to_image 是官方"单公式转图"接口 (内部自建 Figure, 无需布局)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mathtext.math_to_image(latex.strip(), buf, dpi=dpi, format="png")
    for w in caught:
        if "missing from font" in str(w.message):
            raise GlyphWarningError(str(w.message))
    return buf.getvalue()


def main() -> int:
    results: dict[str, list[tuple[str, bool, str]]] = {}
    for tag, latex in SAMPLES:
        ok, err = True, ""
        try:
            render(latex)
        except GlyphWarningError as e:
            ok, err = False, f"[字形缺失-内容降级] {e}"
        except Exception as e:
            ok, err = False, f"{type(e).__name__}: {e}"
        results.setdefault(tag, []).append((latex, ok, err))

    total_ok = total = 0
    for tag, items in results.items():
        n_ok = sum(1 for _, ok, _ in items if ok)
        total_ok += n_ok
        total += len(items)
        print(f"\n── {tag}: {n_ok}/{len(items)} 通过")
        for latex, ok, err in items:
            mark = "✅" if ok else "❌"
            print(f"  {mark} {latex}")
            if not ok:
                print(f"      ↳ {err[:120]}")

    print(f"\n总计: {total_ok}/{total} 通过 ({total_ok / total:.0%})")
    print("\n结论建议:")
    if total_ok / total >= 0.75:
        print("  mathtext 可作 v1 主方案; 失败样本 → LaTeX 原文嵌入 + warning (降级)。")
    else:
        print("  mathtext 通过率不足, 需评估 KaTeX+无头浏览器 或 第三方渲染服务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
