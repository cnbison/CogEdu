"""1-C-2 (Phase 1, 13.4) / 1-D (13.5): 场景生成器 SceneGenerator.

两阶段生成的第二阶段：Outline → 每步一个 Scene（讲解文字 + 配图）。

参考对象：OpenMAIC scene-generator.ts（1931 行体量）——本文件按 Phase 1
范围裁剪为 text/image 两种 block、单一讲解视角；媒体生成、多角色、
交互组件等是后续 Phase 的事。

图片策略（2026-09-12 决策）：v1 只做占位图（``placeholder=True``），
``image_provider`` 注入点留出生成/检索位——将来接图片生成或检索时
注入该接口即可，生成器逻辑不动。

失败语义（1-D）：
- ``policy=None``（默认）：严格模式，任一步失败整体上抛（1-C 基线）。
- ``policy`` 传入：解析失败先按 policy 重试（call_with_retry）；重试
  耗尽 → 该步降级为模板化 ``degraded`` scene（``degraded=True`` +
  ``warnings`` 留痕 + _log.warning），**不让学生端卡空白**（13.5 降级
  决策）。传输层失败（RuntimeError，client 内部已重试耗尽）不降级、
  原样上抛——网络问题不该伪装成"内容生成好了"。
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from cogedu.presentation import prompts
from cogedu.presentation.json_repair import parse_llm_json
from cogedu.presentation.outline import GENERATION_MAX_TOKENS, SupportsChat
from cogedu.presentation.retry import RetryPolicy, call_with_retry
from cogedu.presentation.types import (
    GenerationContext,
    ImageBlock,
    Outline,
    OutlineStep,
    Scene,
    TextBlock,
)

_log = logging.getLogger(__name__)

# 图片提供者接口（1-C-2 预留：v1 为 None → 占位图；未来接生成/检索）
ImageProvider = Callable[[GenerationContext, Outline, OutlineStep], ImageBlock]

# 降级 warning 里截断 reason, 防止把原始 LLM 输出整段塞进 warnings
_REASON_TRUNCATE = 200


class SceneGenerationError(Exception):
    """场景生成失败（LLM 输出结构不合规等）。message 携带原始输出供留痕."""


def _placeholder_image(step: OutlineStep, image_concept: str) -> ImageBlock:
    """v1 占位图（已决策：不接生成/检索，接口留位）."""
    return ImageBlock(
        url=None,
        alt=image_concept or f"配图：{step.title}",
        placeholder=True,
    )


def _degraded_scene(
    outline: Outline,
    ctx: GenerationContext,
    step: OutlineStep,
    reason: str,
) -> Scene:
    """1-D-3: 模板化降级场景——重试耗尽后保证学生端有内容可看.

    模板内容由 step 自带的 title/key_points/objective 组装（这些来自
    大纲, 不依赖本轮失败的 LLM 输出）; ``degraded=True`` + ``warnings``
    留痕, 落库时进 ``degraded`` 列可统计降级率。
    """
    points = "\n".join(f"- {p}" for p in step.key_points) or "- （大纲未给出要点）"
    text = (
        f"本步骤我们学习：{step.title}。\n\n"
        f"{step.objective or ''}\n\n"
        f"要点提示：\n{points}\n\n"
        "（本页为简化讲解——详细内容生成遇到问题，已自动降级。"
        "你可以先按要点自行梳理，稍后重试或向老师提问。）"
    )
    return Scene(
        outline_id=outline.outline_id,
        step_id=step.step_id,
        student_id=ctx.student_id,
        intervention_id=ctx.intervention_id,
        goal_id=ctx.goal_id,
        evidence_id=ctx.evidence_id,
        title=f"{step.title}（简化讲解）",
        blocks=[
            TextBlock(content=text),
            _placeholder_image(step, ""),
        ],
        degraded=True,
        warnings=[f"scene 生成失败已降级 (step={step.step_id}): {reason[:_REASON_TRUNCATE]}"],
    )


class SceneGenerator:
    """按大纲逐步生成场景."""

    def __init__(
        self,
        llm_client: SupportsChat,
        image_provider: ImageProvider | None = None,
    ) -> None:
        self._llm = llm_client
        self._image_provider = image_provider

    def generate_for_outline(
        self,
        outline: Outline,
        ctx: GenerationContext,
        policy: RetryPolicy | None = None,
    ) -> list[Scene]:
        """为大纲每步生成一个 Scene.

        policy=None: 严格模式（任一步失败整体上抛, 1-C 基线）。
        policy 传入: 解析失败重试 → 耗尽降级为 degraded scene（1-D-3）。
        """
        scenes: list[Scene] = []
        for step in outline.steps:
            if policy is None:
                scenes.append(self.generate_one(outline, ctx, step))
                continue
            try:
                scenes.append(
                    call_with_retry(
                        lambda: self.generate_one(outline, ctx, step),  # noqa: B023
                        policy,
                        retry_on=(ValueError, SceneGenerationError),
                        what=f"scene[{step.step_id}] 生成",
                    )
                )
            except (ValueError, SceneGenerationError) as e:
                # 重试耗尽 → 降级, warning 留痕 (不静默)
                _log.warning(
                    "scene 生成失败, 降级为模板内容 (outline=%s, step=%s): %s",
                    outline.outline_id, step.step_id, e,
                )
                scenes.append(_degraded_scene(outline, ctx, step, str(e)))
        return scenes

    def generate_one(
        self,
        outline: Outline,
        ctx: GenerationContext,
        step: OutlineStep,
    ) -> Scene:
        """单步生成（1-D 重试/降级复用的最小单元）."""
        messages = prompts.build_scene_messages(ctx, outline.title, step)
        raw = parse_llm_json(
            self._llm.chat(messages, max_tokens=GENERATION_MAX_TOKENS)
        )
        scene = self._parse_scene(raw, outline=outline, ctx=ctx, step=step)
        if self._image_provider is not None:
            # 注入了 provider → 替换占位 image block（blocks[1]，1-C-2 约定：
            # Phase 1 每个场景恒为 [text, image] 两个 block）
            scene.blocks[1] = self._image_provider(ctx, outline, step)
        return scene

    @staticmethod
    def _parse_scene(
        raw: Any,
        outline: Outline,
        ctx: GenerationContext,
        step: OutlineStep,
    ) -> Scene:
        """解析 + schema 校验单步 LLM 输出为 Scene."""
        if not isinstance(raw, dict):
            raise SceneGenerationError(
                f"LLM 场景输出不是 JSON 对象: type={type(raw).__name__}"
            )
        text = str(raw.get("text") or "").strip()
        if not text:
            raise SceneGenerationError(f"LLM 场景 text 为空\n原始输出: {raw!r}")
        title = str(raw.get("title") or "").strip() or step.title
        image_concept = str(raw.get("image_concept") or "")

        return Scene(
            outline_id=outline.outline_id,
            step_id=step.step_id,
            student_id=ctx.student_id,
            # 追溯三字段: 引用不拷贝（13.4 "现在就要带上"，
            # 第 11 章"错因诊断可视化"的物理前提）
            intervention_id=ctx.intervention_id,
            goal_id=ctx.goal_id,
            evidence_id=ctx.evidence_id,
            title=title,
            blocks=[
                TextBlock(content=text),
                _placeholder_image(step, image_concept),
            ],
        )
