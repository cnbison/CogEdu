"""3-F-1/2/4: 场景生成侧动作序列测试 — prompt 扩展 + 解析管线 + max_tokens.

覆盖 (方案文档 15.7):
  - prompt 含 actions 输出段 / 坐标系口径 / 白名单五动作 / 禁输出字段
  - 动作解析管线: 白名单外丢弃 + warning / 校验失败丢弃 / 坐标 clamp /
    action_id 重分配 / estimated_duration_ms 估算 (timing.py 权威源) /
    超长 speech 三级拆分
  - schema_version 自动升 v2; 无 actions 保持 Phase 1 形态 (v1)
  - GENERATION_MAX_TOKENS 拆分 (scene 独立 env 可配)
  - 降级场景不带动作 (模板降级路径不受影响)
"""
from __future__ import annotations

import pytest

from cogedu.presentation import prompts
from cogedu.presentation.outline import GENERATION_MAX_TOKENS
from cogedu.presentation.scene import (
    SceneGenerationError,
    SceneGenerator,
    _degraded_scene,
    _parse_actions,
    _scene_max_tokens,
)
from cogedu.presentation.types import (
    GenerationContext,
    Outline,
    OutlineStep,
    SpeechAction,
    WbDrawLatexAction,
    WbDrawLineAction,
    WbDrawShapeAction,
    WbDrawTextAction,
)


def _outline() -> Outline:
    return Outline(student_id="stu_1", intervention_id="int_1", title="二次函数",
                   steps=[OutlineStep(title="第一步", key_points=["kp1"])])


def _ctx() -> GenerationContext:
    return GenerationContext(student_id="stu_1", intervention_id="int_1")


def _step(outline: Outline) -> OutlineStep:
    return outline.steps[0]


def _raw(**actions_override) -> dict:
    return {
        "title": "求根公式",
        "text": "讲解正文，含公式 $x^2$。",
        "image_concept": "示意图",
        **actions_override,
    }


class TestPromptExtension:
    def test_scene_prompt_contains_actions_spec(self):
        messages = prompts.build_scene_messages(_ctx(), "二次函数", _step(_outline()))
        system = messages[0]["content"]
        assert '"actions"' in system
        assert "宽 1000" in system and "562.5" in system          # 坐标口径
        for action_type in ("speech", "wb_draw_text", "wb_draw_shape",
                            "wb_draw_line", "wb_draw_latex"):
            assert action_type in system
        assert "不要输出 action_id" in system                      # 生成侧统管字段
        assert "wb_draw_latex" in system and "frac" in system      # few-shot 示例
        assert "含 actions 动作序列" in messages[1]["content"]


class TestParseActions:
    def test_full_valid_pipeline(self):
        raw = _raw(actions=[
            {"type": "speech", "text": "先看求根公式"},
            {"type": "wb_draw_latex", "latex": "$x$", "x": 120, "y": 200},
            {"type": "wb_draw_line", "x1": 0, "y1": 500, "x2": 1000, "y2": 500},
            {"type": "wb_draw_text", "content": "标注", "x": 100, "y": 80},
            {"type": "wb_draw_shape", "shape": "circle", "x": 600, "y": 100,
             "width": 200, "height": 200},
        ])
        actions, warnings = _parse_actions(raw["actions"], scene_id="s1")
        assert warnings == []
        assert [type(a) for a in actions] == [
            SpeechAction, WbDrawLatexAction, WbDrawLineAction,
            WbDrawTextAction, WbDrawShapeAction,
        ]
        # action_id 统一重分配 (LLM 给的不可信)
        assert [a.action_id for a in actions] == [
            "s1_a1", "s1_a2", "s1_a3", "s1_a4", "s1_a5",
        ]
        # estimated_duration_ms 由 timing.py 权威源估算
        assert actions[0].estimated_duration_ms == 2000   # speech 下限
        assert actions[1].estimated_duration_ms == 800    # wb_draw

    def test_whitelist_filtered_with_warning(self):
        actions, warnings = _parse_actions(
            [{"type": "spotlight", "x": 1, "y": 1},
             {"type": "speech", "text": "讲解"}],
            scene_id="s1",
        )
        assert len(actions) == 1
        assert any("不在白名单" in w for w in warnings)

    def test_invalid_action_dropped_with_warning(self):
        actions, warnings = _parse_actions(
            [{"type": "wb_draw_text", "content": "缺坐标"},   # x/y 必填
             {"type": "speech", "text": "讲解"}],
            scene_id="s1",
        )
        assert len(actions) == 1
        assert any("校验失败" in w for w in warnings)

    def test_out_of_range_coords_clamped_with_warning(self):
        actions, warnings = _parse_actions(
            [{"type": "wb_draw_text", "content": "c", "x": 1500, "y": -5}],
            scene_id="s1",
        )
        assert actions[0].x == 1000
        assert actions[0].y == 0
        assert any("越界" in w for w in warnings)

    def test_line_endpoints_clamped(self):
        actions, warnings = _parse_actions(
            [{"type": "wb_draw_line", "x1": -10, "y1": 500, "x2": 1200, "y2": 500}],
            scene_id="s1",
        )
        line = actions[0]
        assert (line.x1, line.x2) == (0, 1000)
        assert any("越界" in w for w in warnings)

    def test_non_list_actions_ignored_with_warning(self):
        actions, warnings = _parse_actions("不是数组", scene_id="s1")
        assert actions == []
        assert any("不是数组" in w for w in warnings)

    def test_speech_split_over_limit(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("COGEDU_TTS_MAX_TEXT_CHARS", "100")
        actions, warnings = _parse_actions(
            [{"type": "speech", "text": "字" * 250}],   # 无标点 → 硬切
            scene_id="s1",
        )
        assert warnings == []
        assert [a.action_id for a in actions] == ["s1_a1_0", "s1_a1_1", "s1_a1_2"]
        assert all(isinstance(a, SpeechAction) for a in actions)
        assert [a.estimated_duration_ms for a in actions] == [15000, 15000, 7500]


class TestSceneWithActions:
    def test_parse_scene_version_2_and_ids_scoped(self):
        outline = _outline()
        raw = _raw(actions=[{"type": "speech", "text": "讲解"}])
        scene = SceneGenerator._parse_scene(raw, outline=outline,
                                            ctx=_ctx(), step=outline.steps[0])
        assert scene.schema_version == 2
        assert scene.actions is not None
        assert scene.actions[0].action_id == f"{scene.scene_id}_a1"
        assert scene.warnings == []

    def test_no_actions_keeps_phase1_shape(self):
        outline = _outline()
        scene = SceneGenerator._parse_scene(_raw(), outline=outline,
                                            ctx=_ctx(), step=outline.steps[0])
        assert scene.actions is None
        assert scene.schema_version == 1
        assert scene.warnings == []

    def test_empty_actions_list_is_none(self):
        outline = _outline()
        scene = SceneGenerator._parse_scene(_raw(actions=[]), outline=outline,
                                            ctx=_ctx(), step=outline.steps[0])
        assert scene.actions is None       # 空 → None (不产空数组)
        assert scene.schema_version == 1

    def test_action_warnings_landed_in_scene(self):
        outline = _outline()
        scene = SceneGenerator._parse_scene(
            _raw(actions=[{"type": "wb_nope"}, {"type": "speech", "text": "ok"}]),
            outline=outline, ctx=_ctx(), step=outline.steps[0],
        )
        assert scene.warnings and "不在白名单" in scene.warnings[0]

    def test_degraded_scene_has_no_actions(self):
        """降级路径不受 3-F 影响: 模板场景无动作 (v1 形态)."""
        scene = _degraded_scene(_outline(), _ctx(), _outline().steps[0], "原因")
        assert scene.actions is None
        assert scene.degraded is True
        assert scene.schema_version == 1

    def test_text_empty_still_fails_whole(self):
        """整体 parse 失败路径不变: text 为空 → SceneGenerationError (走 retry)."""
        with pytest.raises(SceneGenerationError):
            SceneGenerator._parse_scene({"title": "t", "text": ""},
                                        outline=_outline(), ctx=_ctx(),
                                        step=_outline().steps[0])


class TestSceneMaxTokens:
    def test_default_falls_back_to_global(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("COGEDU_PRESENTATION_SCENE_MAX_TOKENS", raising=False)
        assert _scene_max_tokens() == GENERATION_MAX_TOKENS

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("COGEDU_PRESENTATION_SCENE_MAX_TOKENS", "8192")
        assert _scene_max_tokens() == 8192

    def test_bogus_value_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("COGEDU_PRESENTATION_SCENE_MAX_TOKENS", "bogus")
        assert _scene_max_tokens() == GENERATION_MAX_TOKENS
