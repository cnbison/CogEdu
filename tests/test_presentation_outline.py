"""Phase 1 1-B-3: 大纲生成单元测试（mock LLM，三路：正常/坏 JSON/缺字段）.

覆盖:
  - OutlineGenerator.generate 正常路径: 字段传播 + step_id 重分配唯一
  - chat_json 抛 ValueError（JSON 解析失败）→ 原样上抛（重试是 1-D 的职责）
  - 结构不合规（非 dict / steps 空 / title 空）→ OutlineGenerationError 含原始输出
  - GenerationContext.from_lca_result: duck-typing 提取 + Enum→value + 缺 intervention 报错
  - prompts.build_outline_messages: 映射表字段进 prompt / 只记录字段不进 / 预留参数拼接
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from cogedu.presentation.outline import OutlineGenerationError, OutlineGenerator
from cogedu.presentation.prompts import build_outline_messages
from cogedu.presentation.types import GenerationContext


class FakeLLM:
    """SupportsChatJson 的测试替身."""

    def __init__(self, output: Any = None, error: Exception | None = None):
        self.output = output
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        if isinstance(self.output, str):
            return self.output
        return json.dumps(self.output, ensure_ascii=False)


def _ctx(**overrides: Any) -> GenerationContext:
    defaults: dict[str, Any] = dict(
        student_id="stu_001",
        intervention_id="int_abc123",
        intervention_type="explanatory",
        target_skills=["二次函数"],
        target_misconceptions=["认为抛物线开口方向由 a 的符号直接决定图像上下平移"],
        target_tcs=["函数图像与代数表达式的对应"],
        difficulty=0.4,
        scaffolding_level=0.7,
        clt_level=2,
        ca_stage="coaching",
        bloom_target="APPLY",
        rationale="学生 C 维度暴露对称性误概念",
        goal_id="goal_1",
        evidence_id="ev_9",
    )
    defaults.update(overrides)
    return GenerationContext(**defaults)


_GOOD_OUTPUT = {
    "title": "二次函数图像入门",
    "steps": [
        {"title": "回顾函数概念", "key_points": ["什么是函数图像"], "objective": "唤醒旧知"},
        {"title": "认识抛物线", "key_points": ["$y=ax^2$ 的图像形状"], "objective": "建立直观"},
        {"title": "动手练一练", "key_points": ["画 $y=2x^2$"], "objective": "巩固"},
    ],
}


class TestGenerateHappyPath:
    def test_fields_propagated_from_context(self):
        gen = OutlineGenerator(FakeLLM(_GOOD_OUTPUT))
        outline = gen.generate(_ctx())
        assert outline.student_id == "stu_001"
        assert outline.intervention_id == "int_abc123"
        assert outline.goal_id == "goal_1"
        assert outline.evidence_id == "ev_9"
        assert outline.title == "二次函数图像入门"
        assert [s.title for s in outline.steps] == ["回顾函数概念", "认识抛物线", "动手练一练"]

    def test_step_ids_reassigned_unique(self):
        """LLM 给的 step_id 不可信: 解析后统一重分配且唯一."""
        poisoned = {
            "title": "t",
            "steps": [
                {"title": "a", "step_id": "llm-dup"},
                {"title": "b", "step_id": "llm-dup"},
            ],
        }
        outline = OutlineGenerator(FakeLLM(poisoned)).generate(_ctx())
        ids = [s.step_id for s in outline.steps]
        assert len(set(ids)) == 2
        assert all(i.startswith(outline.outline_id) for i in ids)

    def test_prompt_receives_mapping_fields(self):
        """映射表"进 prompt"字段出现在消息里（13.3 口径）."""
        llm = FakeLLM(_GOOD_OUTPUT)
        OutlineGenerator(llm).generate(_ctx())
        assert len(llm.calls) == 1
        joined = "\n".join(m["content"] for m in llm.calls[0])
        assert "二次函数" in joined  # target_skills
        assert "误概念" in joined  # target_misconceptions
        assert "学生 C 维度暴露对称性误概念" in joined  # rationale
        # 只记录字段不进 prompt（映射表 §2: expected_gain/expected_risk）
        assert "expected_gain" not in joined


class TestGenerateFailures:
    def test_chat_json_error_propagates(self):
        """JSON 解析失败原样上抛 — 重试/降级是 1-D 的职责, 这里不吞."""
        llm = FakeLLM(error=ValueError("LLM 输出无法解析为 JSON"))
        with pytest.raises(ValueError, match="无法解析"):
            OutlineGenerator(llm).generate(_ctx())

    def test_non_dict_output_rejected(self):
        llm = FakeLLM(["not", "a", "dict"])
        with pytest.raises(OutlineGenerationError, match="不是 JSON 对象"):
            OutlineGenerator(llm).generate(_ctx())

    def test_empty_steps_rejected(self):
        llm = FakeLLM({"title": "t", "steps": []})
        with pytest.raises(OutlineGenerationError, match="steps 为空"):
            OutlineGenerator(llm).generate(_ctx())

    def test_missing_steps_key_rejected(self):
        llm = FakeLLM({"title": "只有标题"})
        with pytest.raises(OutlineGenerationError, match="steps 为空"):
            OutlineGenerator(llm).generate(_ctx())

    def test_empty_title_rejected(self):
        llm = FakeLLM({"title": "  ", "steps": [{"title": "s"}]})
        with pytest.raises(OutlineGenerationError, match="title 为空"):
            OutlineGenerator(llm).generate(_ctx())

    def test_empty_step_title_rejected(self):
        llm = FakeLLM({"title": "t", "steps": [{"title": ""}]})
        with pytest.raises(OutlineGenerationError, match="title 为空"):
            OutlineGenerator(llm).generate(_ctx())


class TestFromLcaResult:
    def test_duck_typing_extraction_with_enums(self):
        """Enum 值转 str（InterventionType/CLTLevel 等都是 Enum）."""
        from enum import Enum

        class FakeType(str, Enum):
            EXPLANATORY = "explanatory"

        class FakeCLT(Enum):
            DEVELOPING = 2

        class FakeIntervention:
            intervention_id = "int_x"
            intervention_type = FakeType.EXPLANATORY
            target_skills = ["s1"]
            target_misconceptions = ["m1"]
            target_tcs = []
            difficulty = 0.3
            scaffolding_level = 0.6
            clt_level = FakeCLT.DEVELOPING
            ca_stage = "coaching"
            bloom_target = "APPLY"
            rationale = "r"

        class FakeResult:
            student_id = "stu_1"
            intervention = FakeIntervention()
            rationale = "top_rationale"

        ctx = GenerationContext.from_lca_result(FakeResult(), goal_id="g", evidence_id="e")
        assert ctx.intervention_id == "int_x"
        assert ctx.intervention_type == "explanatory"  # Enum → value
        assert ctx.clt_level == 2  # Enum → value
        assert ctx.rationale == "r"  # intervention.rationale 优先
        assert ctx.goal_id == "g" and ctx.evidence_id == "e"

    def test_missing_intervention_raises(self):
        from cogedu.presentation.types import RuntimeContractError

        class FakeResult:
            student_id = "stu_1"
            intervention = None

        with pytest.raises(RuntimeContractError, match="intervention 缺失"):
            GenerationContext.from_lca_result(FakeResult())


class TestPromptReservedParams:
    def test_kb_snippets_appended(self):
        msgs = build_outline_messages(_ctx(), kb_snippets=["片段A"])
        joined = "\n".join(m["content"] for m in msgs)
        assert "片段A" in joined

    def test_pdf_params_appended(self):
        """pdf_text/pdf_images 预留参数（Phase 1 不传, 传了要生效）."""
        msgs = build_outline_messages(_ctx(), pdf_text="教材原文", pdf_images=["b64img"])
        joined = "\n".join(m["content"] for m in msgs)
        assert "教材原文" in joined
        assert "img_0" in joined
