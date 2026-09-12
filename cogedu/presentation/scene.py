"""1-C-2 (Phase 1, 13.4): 场景生成器 SceneGenerator.

两阶段生成的第二阶段：Outline → 每步一个 Scene（讲解文字 + 配图）。

参考对象：OpenMAIC scene-generator.ts（1931 行体量）——本文件按 Phase 1
范围裁剪为 text/image 两种 block、单一讲解视角；媒体生成、多角色、
交互组件等是后续 Phase 的事。

图片策略（2026-09-12 决策）：v1 只做占位图（``placeholder=True``），
``image_provider`` 注入点留出生成/检索位——将来接图片生成或检索时
注入该接口即可，生成器逻辑不动。

LLM 注入 / 失败语义同 OutlineGenerator（1-B-2）：解析失败上抛不吞，
结构不合规抛 SceneGenerationError 含原始输出；重试与降级是 1-D 的职责
（``generate_one`` 是 1-D 重试/降级复用的最小单元）。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from cogedu.presentation import prompts
from cogedu.presentation.outline import SupportsChatJson
from cogedu.presentation.types import (
    GenerationContext,
    ImageBlock,
    Outline,
    OutlineStep,
    Scene,
    TextBlock,
)

# 图片提供者接口（1-C-2 预留：v1 为 None → 占位图；未来接生成/检索）
ImageProvider = Callable[[GenerationContext, Outline, OutlineStep], ImageBlock]


class SceneGenerationError(Exception):
    """场景生成失败（LLM 输出结构不合规等）。message 携带原始输出供留痕."""


def _placeholder_image(step: OutlineStep, image_concept: str) -> ImageBlock:
    """v1 占位图（已决策：不接生成/检索，接口留位）."""
    return ImageBlock(
        url=None,
        alt=image_concept or f"配图：{step.title}",
        placeholder=True,
    )


class SceneGenerator:
    """按大纲逐步生成场景."""

    def __init__(
        self,
        llm_client: SupportsChatJson,
        image_provider: ImageProvider | None = None,
    ) -> None:
        self._llm = llm_client
        self._image_provider = image_provider

    def generate_for_outline(
        self, outline: Outline, ctx: GenerationContext
    ) -> list[Scene]:
        """为大纲每步生成一个 Scene（顺序生成，任一步失败整体上抛）.

        失败语义（1-D 收敛前的基线）：任一步失败 → 整体失败，避免
        "半份场景"落库造成学生端看到断头内容；1-D 的重试/降级在此
        之上把可恢复的失败收敛为 degraded scene。
        """
        return [self.generate_one(outline, ctx, step) for step in outline.steps]

    def generate_one(
        self,
        outline: Outline,
        ctx: GenerationContext,
        step: OutlineStep,
    ) -> Scene:
        """单步生成（1-D 重试/降级复用的最小单元）."""
        messages = prompts.build_scene_messages(ctx, outline.title, step)
        raw = self._llm.chat_json(messages)
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
