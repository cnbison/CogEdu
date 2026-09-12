"""Phase 1 1-C: 场景生成单元测试（mock LLM）.

覆盖:
  - SceneGenerator.generate_for_outline: 步数一致 / blocks=[text, image] /
    占位图标记 / 追溯三字段 (intervention_id/goal_id/evidence_id 引用不拷贝)
  - prompt 公式格式约束命中 / 单一视角禁令存在
  - 失败路径: 非 dict / text 空 → SceneGenerationError 含原始输出
  - image_provider 注入: 占位图被替换 (1-C-2 接口留位)
"""
from __future__ import annotations

from typing import Any

import pytest

from cogedu.presentation.scene import SceneGenerationError, SceneGenerator
from cogedu.presentation.types import GenerationContext, ImageBlock, Outline, OutlineStep


class FakeLLM:
    def __init__(self, outputs: list[Any] | None = None, error: Exception | None = None):
        self.outputs = outputs or []
        self.error = error
        self.calls: list[list[dict[str, str]]] = []

    def chat_json(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        self.calls.append(messages)
        if self.error is not None:
            raise self.error
        if not self.outputs:
            raise AssertionError("FakeLLM 输出耗尽")
        return self.outputs.pop(0)


def _ctx() -> GenerationContext:
    return GenerationContext(
        student_id="stu_001",
        intervention_id="int_abc123",
        intervention_type="explanatory",
        target_skills=["二次函数"],
        target_misconceptions=["误把平移当开口方向"],
        difficulty=0.4,
        scaffolding_level=0.7,
        clt_level=2,
        ca_stage="coaching",
        bloom_target="APPLY",
        goal_id="goal_1",
        evidence_id="ev_9",
    )


def _outline() -> Outline:
    return Outline(
        student_id="stu_001",
        intervention_id="int_abc123",
        goal_id="goal_1",
        evidence_id="ev_9",
        title="二次函数图像入门",
        steps=[
            OutlineStep(title="认识抛物线", key_points=["$y=ax^2$ 图像形状"]),
            OutlineStep(title="动手练一练", key_points=["画 $y=2x^2$"]),
        ],
    )


_SCENE_OUTPUT = {
    "title": "认识抛物线",
    "text": "我们先看 $y=x^2$ 的图像……$$y = ax^2 + bx + c$$ 其中 $a$ 决定开口方向。",
    "image_concept": "抛物线开口方向示意图",
}


class TestGenerateForOutline:
    def test_scene_per_step_and_traceability(self):
        outline = _outline()
        llm = FakeLLM([dict(_SCENE_OUTPUT), dict(_SCENE_OUTPUT, title="练一练")])
        scenes = SceneGenerator(llm).generate_for_outline(outline, _ctx())
        # 场景数与大纲步数一致 (1-C-4 校验点)
        assert len(scenes) == 2
        for scene in scenes:
            # 追溯三字段: 引用不拷贝, 从 ctx 透传 (13.4 "现在就要带上")
            assert scene.intervention_id == "int_abc123"
            assert scene.goal_id == "goal_1"
            assert scene.evidence_id == "ev_9"
            assert scene.outline_id == outline.outline_id
            # Phase 1 契约: [text, image] 两个 block
            assert [b.type for b in scene.blocks] == ["text", "image"]

    def test_step_ids_match_outline(self):
        outline = _outline()
        llm = FakeLLM([dict(_SCENE_OUTPUT)] * 2)
        scenes = SceneGenerator(llm).generate_for_outline(outline, _ctx())
        assert [s.step_id for s in scenes] == [st.step_id for st in outline.steps]

    def test_placeholder_image_default(self):
        llm = FakeLLM([dict(_SCENE_OUTPUT)] * 2)
        scene = SceneGenerator(llm).generate_for_outline(_outline(), _ctx())[0]
        image = scene.blocks[1]
        assert isinstance(image, ImageBlock)
        # v1 决策: 占位图 (placeholder=True), alt 取 image_concept
        assert image.placeholder is True
        assert image.url is None
        assert image.alt == "抛物线开口方向示意图"

    def test_prompt_constraints(self):
        """公式格式约束 + 单一视角禁令出现在 prompt (1-C-1 校验点)."""
        llm = FakeLLM([dict(_SCENE_OUTPUT)] * 2)
        SceneGenerator(llm).generate_for_outline(_outline(), _ctx())
        joined = "\n".join(m["content"] for m in llm.calls[0])
        assert "$...$" in joined and "$$...$$" in joined  # LaTeX 定界符约束
        assert "单一" in joined and "不要" in joined  # 单一讲解视角禁令
        assert "误把平移当开口方向" in joined  # 误概念针对性纠正

    def test_llm_error_propagates(self):
        llm = FakeLLM(error=ValueError("LLM 输出无法解析为 JSON"))
        with pytest.raises(ValueError, match="无法解析"):
            SceneGenerator(llm).generate_for_outline(_outline(), _ctx())


class TestParseFailures:
    def test_non_dict_rejected(self):
        llm = FakeLLM(["nope"])
        with pytest.raises(SceneGenerationError, match="不是 JSON 对象"):
            SceneGenerator(llm).generate_for_outline(_outline(), _ctx())

    def test_empty_text_rejected(self):
        llm = FakeLLM([{"title": "t", "text": "  "}])
        with pytest.raises(SceneGenerationError, match="text 为空"):
            SceneGenerator(llm).generate_for_outline(_outline(), _ctx())

    def test_missing_title_falls_back_to_step_title(self):
        llm = FakeLLM([{"text": "正文内容"}] * 2)
        scene = SceneGenerator(llm).generate_for_outline(_outline(), _ctx())[0]
        assert scene.title == "认识抛物线"


class TestImageProvider:
    def test_provider_replaces_placeholder(self):
        """注入 image_provider → 占位图被替换 (生成/检索的接口留位)."""
        llm = FakeLLM([dict(_SCENE_OUTPUT)] * 2)

        def provider(ctx, outline, step):
            return ImageBlock(url="https://example.com/img.png", alt="检索图")

        scene = SceneGenerator(llm, image_provider=provider).generate_for_outline(
            _outline(), _ctx()
        )[0]
        assert scene.blocks[1].url == "https://example.com/img.png"
        assert scene.blocks[1].placeholder is False


class TestOutlineContextRoundTrip:
    def test_outline_context_survives_json_roundtrip(self):
        """context 随 Outline 落库恢复 (第二阶段重建 prompt 的前提)."""
        outline = _outline()
        outline.context = _ctx()
        restored = Outline.model_validate_json(outline.model_dump_json())
        assert restored.context is not None
        assert restored.context.intervention_id == "int_abc123"
        assert restored.context.target_misconceptions == ["误把平移当开口方向"]

    def test_outline_generator_sets_ids(self):
        """OutlineGenerator 产出的 step_id 稳定且唯一（scene.step_id 引用一致）."""
        from cogedu.presentation.outline import OutlineGenerator as _OG

        class _LLM:
            def chat_json(self, messages, **kwargs):
                return {
                    "title": "t",
                    "steps": [{"title": "a"}, {"title": "b"}],
                }

        outline = _OG(_LLM()).generate(_ctx())
        assert outline.outline_id
        assert outline.context is None  # context 由路由层落库前设置
