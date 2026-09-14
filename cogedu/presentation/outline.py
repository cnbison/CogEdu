"""1-B-2 (Phase 1, 13.3) / 1-D (13.5): 大纲生成器 OutlineGenerator.

依赖注入（1-A-5）：LLM client 由调用方注入，本模块只声明最小 Protocol
（有 ``chat`` 方法即可），不绑定 ``ECOSLLMClient`` 具体类型、不依赖 web 层。

解析校验策略：
- ``chat`` 拿原始文本 → ``parse_llm_json``（1-D-1: think 块剥离 + 围栏
  清理 + json-repair 容错修复）→ 结构校验。
- 结构不合规（缺 steps / steps 空 / 字段类型不对）→ 抛
  ``OutlineGenerationError``，message 含原始输出（不静默吞）。
- ``policy`` 传入时对解析失败做生成层重试（1-D-2，仅 ValueError；
  传输层 RuntimeError 由 client 内部重试后原样上抛，此处不重复重试）。
- LLM 给的 step_id 不可信：解析后统一重新分配，保证唯一。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol

from cogedu.presentation import prompts
from cogedu.presentation.json_repair import parse_llm_json
from cogedu.presentation.retry import RetryPolicy, call_with_retry
from cogedu.presentation.types import GenerationContext, Outline, OutlineStep

_log = logging.getLogger(__name__)


class SupportsChat(Protocol):
    """生成器对 LLM client 的最小要求（结构化类型，方便 mock）."""

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str: ...


# 生成输出 token 预算: MiniMax-M3 等 thinking 模型的 <think> 块计入
# max_tokens, LLMConfig 默认 1024 会被推理块耗尽 → strip 后剩空文本
# (1-G-1 灰度实测)。JSON 输出 + 推理余量取 4096。
GENERATION_MAX_TOKENS = 4096

# 3-G 验收实证（2026-09-14）：thinking 模型单次调用可超共享客户端默认 30s
# （维护者页面验收时大纲连续 3 次尝试全部超时）。与 scene 的独立超时同款
# 机制：经 chat(**kwargs) 透传 openai SDK per-request timeout，不动共享客户端。
OUTLINE_TIMEOUT_SEC_DEFAULT = 120.0


def _outline_timeout() -> float:
    """大纲生成的单次请求超时秒数. env
    ``COGEDU_PRESENTATION_OUTLINE_TIMEOUT_SEC`` 可配（非法值 warning + 兜底）."""
    raw = os.environ.get("COGEDU_PRESENTATION_OUTLINE_TIMEOUT_SEC", "").strip()
    if not raw:
        return OUTLINE_TIMEOUT_SEC_DEFAULT
    try:
        return float(raw)
    except ValueError:
        _log.warning(
            "COGEDU_PRESENTATION_OUTLINE_TIMEOUT_SEC 非法 (%r), 回退 %s",
            raw, OUTLINE_TIMEOUT_SEC_DEFAULT,
        )
        return OUTLINE_TIMEOUT_SEC_DEFAULT


class OutlineGenerationError(Exception):
    """大纲生成失败（LLM 输出结构不合规等）。message 携带原始输出供留痕."""


class OutlineGenerator:
    """两阶段生成的第一阶段：intervention → 结构化大纲.

    参考对象：OpenMAIC outline-generator.ts（233 行体量）——按 Phase 1
    范围裁剪，不引入 widget/media 概念；``kb_snippets`` / ``pdf_text`` /
    ``pdf_images`` 为预留可选参数（Phase 5 前不传）。
    """

    def __init__(self, llm_client: SupportsChat) -> None:
        self._llm = llm_client

    def generate(
        self,
        ctx: GenerationContext,
        kb_snippets: list[str] | None = None,
        pdf_text: str | None = None,
        pdf_images: list[str] | None = None,
        policy: RetryPolicy | None = None,
    ) -> Outline:
        """调 LLM 生成大纲并校验.

        policy=None 时单次尝试（严格模式）；传入 policy 时对解析失败
        重试（1-D-2）。传输层失败（RuntimeError）原样上抛。
        """
        messages = prompts.build_outline_messages(
            ctx,
            kb_snippets=kb_snippets,
            pdf_text=pdf_text,
            pdf_images=pdf_images,
        )

        def _call() -> Any:
            return parse_llm_json(
                self._llm.chat(
                    messages,
                    max_tokens=GENERATION_MAX_TOKENS,
                    timeout=_outline_timeout(),
                )
            )

        raw = (
            call_with_retry(_call, policy, what="outline 生成")
            if policy is not None
            else _call()
        )
        return self.parse_outline(raw, ctx)

    @staticmethod
    def parse_outline(raw: Any, ctx: GenerationContext) -> Outline:
        """解析 + schema 校验 LLM 输出为 Outline.

        独立成方法：1-D 的容错解析在重试时对同一输入复用这条校验路径。
        """
        if not isinstance(raw, dict):
            raise OutlineGenerationError(
                f"LLM 大纲输出不是 JSON 对象: type={type(raw).__name__}"
            )
        try:
            outline = Outline(
                student_id=ctx.student_id,
                intervention_id=ctx.intervention_id,
                goal_id=ctx.goal_id,
                evidence_id=ctx.evidence_id,
                title=str(raw.get("title") or f"{ctx.intervention_type} 讲解"),
                steps=[
                    OutlineStep(
                        title=str(step.get("title") or "").strip(),
                        key_points=[str(k) for k in (step.get("key_points") or [])],
                        objective=step.get("objective"),
                    )
                    for step in raw.get("steps") or []
                ],
            )
        except Exception as e:
            raise OutlineGenerationError(
                f"LLM 大纲输出结构不合规: {e}\n原始输出: {raw!r}"
            ) from e

        if not outline.title.strip():
            raise OutlineGenerationError(f"LLM 大纲 title 为空\n原始输出: {raw!r}")
        if not outline.steps:
            raise OutlineGenerationError(
                f"LLM 大纲 steps 为空（至少需要 1 步）\n原始输出: {raw!r}"
            )
        # step_id 统一重分配（LLM 给的 id 不可信，保证唯一）
        for i, step in enumerate(outline.steps):
            step.step_id = f"{outline.outline_id}_step{i + 1}"
            if not step.title:
                raise OutlineGenerationError(
                    f"LLM 大纲第 {i + 1} 步 title 为空\n原始输出: {raw!r}"
                )
        return outline
