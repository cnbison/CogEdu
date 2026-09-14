"""1-B-1 (Phase 1, 13.3): 大纲生成 prompt.

输入字段口径以 ``docs/presentation-runtime-map.md`` §2 映射表为准：
进 prompt 的 LCAResult 字段（intervention_type / target_skills /
target_misconceptions / target_tcs / difficulty / scaffolding_level /
clt_level / ca_stage / bloom_target / rationale）在这里组装；expected_gain
/ expected_risk 等只记录字段**刻意不出现**在 prompt 里。

预留参数（Phase 5 前）：``kb_snippets``（知识库片段，恒空）、
``pdf_text`` / ``pdf_images``（教材 PDF 输入，照抄 OpenMAIC
outline-generator 的可选参数思路，Phase 1 暂不传）。
"""
from __future__ import annotations

from cogedu.presentation.types import GenerationContext, OutlineStep

# CLT 级别 → 讲解铺垫指导（expertise reversal：新手给完整例题，高手给留白）
_CLT_HINTS: dict[int, str] = {
    1: "学生是新手：每步给出完整的例题演示和即时解释，铺垫要足。",
    2: "学生有一定基础：给出部分例题，留一些步骤让学生自己完成。",
    3: "学生较熟练：不再给完整例题，直接讲解要点并配少量提示。",
    4: "学生已熟练：以要点和易错点提醒为主，最大程度让学生自主回忆。",
}

# CA 阶段 → 教练口吻
_CA_STAGE_HINTS: dict[str, str] = {
    "modeling": "处于示范阶段：以示范和讲解为主。",
    "coaching": "处于教练阶段：讲解中穿插引导性提问，鼓励学生参与。",
    "scaffolding": "处于搭建阶段：重点提供支撑和提示，逐步放手。",
    "fading": "处于淡出阶段：以确认和纠偏为主，减少直接讲解。",
}


def build_outline_messages(
    ctx: GenerationContext,
    kb_snippets: list[str] | None = None,
    pdf_text: str | None = None,
    pdf_images: list[str] | None = None,
) -> list[dict[str, str]]:
    """组装大纲生成 messages（OpenAI 格式）.

    Returns:
        [{"role": "system", ...}, {"role": "user", ...}]
    """
    clt_hint = _CLT_HINTS.get(int(ctx.clt_level), _CLT_HINTS[2])
    ca_hint = _CA_STAGE_HINTS.get(ctx.ca_stage, "")

    system = (
        "你是一位面向中国 K12 学生（初中/高中）的数理化学习教练。"
        "你根据给定的教学干预要求，为学生设计一份分步讲解大纲。\n"
        "要求：\n"
        "- 全程使用中文。\n"
        "- 数学/物理/化学内容如需公式，用 LaTeX 记号（行内 $...$，独立公式 $$...$$）。\n"
        "- 只输出 JSON，不要输出任何其他文字或代码围栏。\n"
        "- JSON 格式：{\"title\": str, \"steps\": [{\"title\": str, "
        "\"key_points\": [str, ...], \"objective\": str}]}。\n"
        "- steps 数量 3~6 步，每步聚焦一个要点。"
    )

    user_parts: list[str] = [
        f"干预类型：{ctx.intervention_type}",
        f"目标知识点：{', '.join(ctx.target_skills) or '（未指定）'}",
    ]
    if ctx.target_misconceptions:
        user_parts.append(f"学生已暴露的误概念（讲解要针对性纠正）：{', '.join(ctx.target_misconceptions)}")
    if ctx.target_tcs:
        user_parts.append(f"待跨越的概念边界：{', '.join(ctx.target_tcs)}")
    user_parts.append(f"内容难度（0 极易~1 极难）：{ctx.difficulty:.2f}")
    user_parts.append(f"支持程度（0~1，越高铺垫越多）：{ctx.scaffolding_level:.2f}")
    user_parts.append(f"认知层次目标：{ctx.bloom_target}")
    user_parts.append(f"呈现指导：{clt_hint}")
    if ca_hint:
        user_parts.append(f"教练口吻：{ca_hint}")
    if ctx.rationale:
        user_parts.append(f"选择该干预的理由（供参考）：{ctx.rationale}")

    # Phase 5 前恒空 / 恒 None 的预留输入——出现时拼进 prompt
    if kb_snippets:
        user_parts.append("参考资料片段：\n" + "\n".join(kb_snippets))
    if pdf_text:
        user_parts.append("教材原文：\n" + pdf_text)
    if pdf_images:
        user_parts.append(f"教材图片 {len(pdf_images)} 张（编号 img_0..img_{len(pdf_images) - 1}，讲解步骤可引用编号）")

    user_parts.append("请输出讲解大纲 JSON。")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]


# ─── 场景生成 (1-C-1) ────────────────────────────────────────────────────────


def build_scene_messages(
    ctx: GenerationContext,
    outline_title: str,
    step: OutlineStep,
) -> list[dict[str, str]]:
    """组装单步场景生成 messages.

    Phase 1 范围约束（13.4）：
    - 每个场景产出讲解文字（text block）+ 配图意图（image block，
      v1 为占位图，``image_concept`` 作为配图说明/alt）
    - 公式一律 LaTeX（$...$ 行内 / $$...$$ 独立），渲染归前端 KaTeX
    - **单一讲解视角**：多角色讨论 / AI 同学插话是 v1 范围外
      （方案文档第 3/8 章），prompt 里显式禁止，防止 LLM 自作主张

    Phase 3 (3-F-1)：新增 ``actions`` 动作序列输出段——LLM 在 Scene JSON
    内输出白板/语音动作数组（参考 OpenMAIC system.md 的 "MUST output +
    完整示例" 模式），边讲边画；坐标/字段口径与 3-A schema 一致，
    动作类型说明独立成段便于迭代。
    """
    system = (
        "你是一位面向中国 K12 学生（初中/高中）的数理化学习教练，"
        "正在为学生撰写一个讲解场景（一段连贯的讲解内容）。\n"
        "要求：\n"
        "- 全程使用中文。\n"
        "- 数学/物理/化学公式一律用 LaTeX 记号：行内公式用 $...$，"
        "独立公式用 $$...$$（渲染由前端处理，直接写 LaTeX 即可）。\n"
        "- 只用单一的讲解者视角，不要写多角色对话，不要虚构 AI 同学插话。\n"
        "- 讲解要口语化、有引导性，贴合给定难度和支持程度。\n"
        "- 只输出 JSON，不要输出任何其他文字或代码围栏。\n"
        '- JSON 格式：{"title": str, "text": str, "image_concept": str, '
        '"actions": [动作, ...]}。\n'
        "- text 为讲解正文（300~600 字），image_concept 为一句话的配图意图。\n"
        "\n"
        "actions 是白板讲解的动作序列（按数组顺序播放，与讲解词配合，边讲边画）。\n"
        "动作类型只有以下五种，字段如下：\n"
        '- speech：{"type": "speech", "text": str} —— 一段讲解词；把本页讲解'
        "按讲述节奏拆成多个 speech 动作，每个 50~150 字。\n"
        '- wb_draw_text：{"type": "wb_draw_text", "content": str, "x": int, '
        '"y": int, "width": int, "font_size": int} —— 画一段文字标注。\n'
        '- wb_draw_shape：{"type": "wb_draw_shape", "shape": "rectangle" | '
        '"circle" | "triangle", "x": int, "y": int, "width": int, "height": int}'
        " —— 画一个图形。\n"
        '- wb_draw_line：{"type": "wb_draw_line", "x1": int, "y1": int, '
        '"x2": int, "y2": int} —— 画一条线段（坐标轴、数轴、辅助线）。\n'
        '- wb_draw_latex：{"type": "wb_draw_latex", "latex": str, "x": int, '
        '"y": int, "width": int} —— 画一条公式。latex 字段只放公式本体：'
        "不要带 $ 或 $$ 定界符，不要混入中文等说明文字；中文标注请另用"
        "一条 wb_draw_text 动作。\n"
        "坐标系：虚拟画布宽 1000、高 562.5，原点在左上角，单位为像素；"
        "所有 x/y 都要在画布内。\n"
        "不要输出 action_id / estimated_duration_ms / audio_id 字段"
        "（服务端统一分配、估算和回填）。\n"
        "示例（一元二次方程求根公式的讲解片段）：\n"
        '{"actions": ['
        '{"type": "speech", "text": "我们先来看一元二次方程的求根公式。"}, '
        '{"type": "wb_draw_latex", "latex": "x = \\\\frac{-b \\\\pm \\\\sqrt{b^2-4ac}}{2a}", '
        '"x": 120, "y": 200, "width": 600}, '
        '{"type": "speech", "text": "其中判别式 b 平方减 4ac 决定根的个数。"}, '
        '{"type": "wb_draw_line", "x1": 60, "y1": 480, "x2": 940, "y2": 480}, '
        '{"type": "wb_draw_text", "content": "判别式 > 0：两个不相等的实根", '
        '"x": 120, "y": 380, "width": 500, "font_size": 20}]}'
    )

    user_parts: list[str] = [
        f"讲解主题：{outline_title}",
        f"本步骤标题：{step.title}",
    ]
    if step.key_points:
        user_parts.append("本步骤要点：\n- " + "\n- ".join(step.key_points))
    if step.objective:
        user_parts.append(f"本步骤目标：{step.objective}")
    user_parts.append(f"干预类型：{ctx.intervention_type}")
    user_parts.append(f"目标知识点：{', '.join(ctx.target_skills) or '（未指定）'}")
    if ctx.target_misconceptions:
        user_parts.append(
            f"学生已暴露的误概念（讲解要针对性纠正）：{', '.join(ctx.target_misconceptions)}"
        )
    user_parts.append(f"内容难度（0 极易~1 极难）：{ctx.difficulty:.2f}")
    user_parts.append(f"支持程度（0~1，越高铺垫越多）：{ctx.scaffolding_level:.2f}")
    user_parts.append(f"认知层次目标：{ctx.bloom_target}")

    user_parts.append("请输出本步骤的讲解场景 JSON（含 actions 动作序列）。")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "\n".join(user_parts)},
    ]
