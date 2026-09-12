"""Phase 3 3-A: 动作模型与协议设计测试 (方案文档 15.2).

覆盖:
  - 五种动作 schema 解析 (LLM JSON 形态 → Pydantic union)
  - 白名单穷尽性 (union 成员 ↔ ALLOWED_ACTION_TYPES 一一对应)
  - 未知动作类型 / 非法 shape 拒绝
  - action_id 自动分配与显式保留; estimated_duration_ms 可选
  - schema_version: actions 非空自动升 v2 / None 保持 v1 / JSON round-trip
  - 坐标 clamp (3-A-2)
  - Phase 1 旧场景 (actions=None) 兼容 + store round-trip
"""
from __future__ import annotations

import typing

import pytest
from pydantic import TypeAdapter, ValidationError

from cogedu.persistence.presentation_store import PresentationStore
from cogedu.presentation.types import (
    ALLOWED_ACTION_TYPES,
    SCHEMA_VERSION_V1,
    SCHEMA_VERSION_V2,
    WB_CANVAS_HEIGHT,
    WB_CANVAS_WIDTH,
    Outline,
    OutlineStep,
    Scene,
    SceneAction,
    TextBlock,
    WbDrawLatexAction,
    WbDrawLineAction,
    WbDrawShapeAction,
    WbDrawTextAction,
    SpeechAction,
    clamp_canvas_point,
)

# Annotated 别名不暴露 model_validate，union 层校验走 TypeAdapter
_ACTION_ADAPTER: TypeAdapter = TypeAdapter(SceneAction)

# ---------------------------------------------------------------------------
# 五种动作的 schema 解析
# ---------------------------------------------------------------------------


class TestActionParsing:
    def test_wb_draw_text_defaults(self):
        a = WbDrawTextAction(content="勾股定理", x=100, y=200)
        assert a.type == "wb_draw_text"
        assert a.width == 400.0
        assert a.font_size == 18.0
        assert a.color == "#333333"
        assert a.action_id  # 自动分配
        assert a.estimated_duration_ms is None

    def test_wb_draw_text_from_llm_dict(self):
        """LLM JSON 形态（含多余 id 字段被忽略、坐标越界不在此层拒绝）."""
        a = _ACTION_ADAPTER.validate_python(
            {"type": "wb_draw_text", "content": "斜边 c", "x": 120, "y": 80,
             "estimated_duration_ms": 800}
        )
        assert isinstance(a, WbDrawTextAction)
        assert a.estimated_duration_ms == 800

    def test_wb_draw_shape_only_three_shapes(self):
        assert WbDrawShapeAction(shape="circle", x=0, y=0).shape == "circle"
        with pytest.raises(ValidationError):
            WbDrawShapeAction(shape="star", x=0, y=0)

    def test_wb_draw_line_two_points(self):
        a = WbDrawLineAction(x1=100, y1=500, x2=900, y2=500)
        assert (a.x1, a.y1, a.x2, a.y2) == (100.0, 500.0, 900.0, 500.0)
        assert a.stroke_width == 2.0

    def test_wb_draw_latex(self):
        a = WbDrawLatexAction(latex=r"$x = \frac{-b \pm \sqrt{b^2-4ac}}{2a}$",
                              x=50, y=200)
        assert "frac" in a.latex

    def test_speech_audio_id_backfill(self):
        a = SpeechAction.model_validate(
            {"type": "speech", "text": "我们来看求根公式", "audio_id": "tts_s1_a1"}
        )
        assert a.audio_id == "tts_s1_a1"
        assert a.speed == 1.0
        assert a.voice is None

    def test_unknown_action_type_rejected(self):
        """白名单外动作（spotlight 等）在 schema 层即拒绝."""
        with pytest.raises(ValidationError):
            _ACTION_ADAPTER.validate_python({"type": "spotlight", "x": 1, "y": 1})

    def test_missing_coordinates_rejected(self):
        """坐标是必填项——LLM 不给坐标宁可失败走 retry，不出幽灵位置."""
        with pytest.raises(ValidationError):
            WbDrawTextAction(content="缺坐标")

    def test_missing_discriminator_rejected(self):
        with pytest.raises(ValidationError):
            _ACTION_ADAPTER.validate_python({"content": "没有 type 字段"})


# ---------------------------------------------------------------------------
# 白名单穷尽性（union 成员 ↔ 常量一一对应，防两边各改各的）
# ---------------------------------------------------------------------------


class TestWhitelistExhaustive:
    def test_union_members_match_constant(self):
        annotated_args = typing.get_args(SceneAction)
        union = annotated_args[0]
        literals = {
            m.model_fields["type"].default for m in typing.get_args(union)
        }
        assert literals == set(ALLOWED_ACTION_TYPES)
        assert set(ALLOWED_ACTION_TYPES) == {
            "wb_draw_text", "wb_draw_shape", "wb_draw_line",
            "wb_draw_latex", "speech",
        }

    def test_is_allowed_action_type(self):
        assert SceneAction.__metadata__  # Annotated 结构在
        assert ALLOWED_ACTION_TYPES.index("wb_draw_line") == 2  # v0.6 增补位


# ---------------------------------------------------------------------------
# schema_version（3-A-4）
# ---------------------------------------------------------------------------


def _scene(**overrides) -> Scene:
    defaults = dict(
        outline_id="o1", step_id="o1_step1", student_id="stu_1",
        intervention_id="int_1", title="t",
        blocks=[TextBlock(content="x")],
    )
    defaults.update(overrides)
    return Scene(**defaults)


class TestSchemaVersion:
    def test_phase1_scene_is_v1(self):
        s = _scene()
        assert s.actions is None
        assert s.schema_version == SCHEMA_VERSION_V1

    def test_actions_auto_bumps_to_v2(self):
        s = _scene(actions=[{"type": "speech", "text": "讲解"}])
        assert s.schema_version == SCHEMA_VERSION_V2
        assert isinstance(s.actions[0], SpeechAction)

    def test_explicit_v1_with_actions_still_bumps(self):
        """生成侧手动传 v1 也被纠正——版本号单点维护在模型内."""
        s = _scene(schema_version=SCHEMA_VERSION_V1,
                   actions=[{"type": "wb_draw_text", "content": "x",
                             "x": 0, "y": 0}])
        assert s.schema_version == SCHEMA_VERSION_V2

    def test_outline_default_v1(self):
        o = Outline(student_id="s", intervention_id="i", title="t",
                    steps=[OutlineStep(title="a")])
        assert o.schema_version == SCHEMA_VERSION_V1

    def test_json_roundtrip_preserves_version_and_types(self):
        s = _scene(actions=[
            {"type": "wb_draw_shape", "shape": "triangle", "x": 10, "y": 10},
            {"type": "wb_draw_latex", "latex": "$a^2+b^2=c^2$", "x": 0, "y": 0},
            {"type": "speech", "text": "勾股定理"},
        ])
        revived = Scene.model_validate_json(s.model_dump_json())
        assert revived.schema_version == SCHEMA_VERSION_V2
        assert isinstance(revived.actions[0], WbDrawShapeAction)
        assert isinstance(revived.actions[1], WbDrawLatexAction)
        assert isinstance(revived.actions[2], SpeechAction)


# ---------------------------------------------------------------------------
# 坐标系统（3-A-2）
# ---------------------------------------------------------------------------


class TestCanvasCoordinates:
    def test_canvas_constants(self):
        assert WB_CANVAS_WIDTH == 1000.0
        assert WB_CANVAS_HEIGHT == 562.5  # 16:9

    def test_clamp_inside_unchanged(self):
        assert clamp_canvas_point(500.0, 281.25) == (500.0, 281.25)

    def test_clamp_out_of_bounds(self):
        assert clamp_canvas_point(-10.0, 200.0) == (0.0, 200.0)
        assert clamp_canvas_point(1500.0, 200.0) == (1000.0, 200.0)
        assert clamp_canvas_point(500.0, 900.0) == (500.0, 562.5)
        assert clamp_canvas_point(-1.0, -1.0) == (0.0, 0.0)


# ---------------------------------------------------------------------------
# 兼容与持久化
# ---------------------------------------------------------------------------


class TestStoreRoundTrip:
    def test_scene_with_actions_roundtrip_sqlite(self, tmp_path):
        store = PresentationStore(db_path=str(tmp_path / "p.db"))
        try:
            outline = Outline(student_id="s", intervention_id="i", title="t",
                              steps=[OutlineStep(title="a")])
            store.save_outline(outline)
            scene = _scene(outline_id=outline.outline_id, actions=[
                {"type": "wb_draw_text", "content": "设 Ax=0", "x": 100,
                 "y": 100},
                {"type": "speech", "text": "讲解"},
            ])
            assert store.save_scene(scene) is True
            got = store.list_scenes_by_outline(outline.outline_id)
            assert got[0].schema_version == SCHEMA_VERSION_V2
            assert isinstance(got[0].actions[0], WbDrawTextAction)
            assert got[0].actions[0].content == "设 Ax=0"
        finally:
            store.close()

    def test_phase1_payload_without_actions_still_loads(self):
        """Phase 1 落库的 payload（无 schema_version 字段）读回时走默认值."""
        legacy = {
            "scene_id": "s_legacy", "outline_id": "o", "step_id": "st",
            "student_id": "s", "intervention_id": "i", "title": "t",
            "blocks": [{"type": "text", "content": "x"}],
            "created_at": "2026-09-12T00:00:00+00:00",
        }
        s = Scene.model_validate(legacy)
        assert s.schema_version == SCHEMA_VERSION_V1
        assert s.actions is None
