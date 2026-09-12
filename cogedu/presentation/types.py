"""1-A-1 (Phase 1, 13.2): 呈现引擎契约类型 — Outline / Scene schema.

设计要点：

- Scene 与内核对象的关联是**引用不拷贝**：intervention_id / goal_id /
  evidence_id 只存 ID 字符串，Goal/Evidence 对象本体不进 Scene。
- Phase 1 内容区块只有 ``text`` / ``image`` 两种（参考第 11 章 DeepTutor
  ``BlockType`` 的思路，但不一次性做全）；后续类型（quiz/interactive 等，
  参考 OpenMAIC scene-types.ts）按 Phase 需要扩展 discriminator union。
- 数学公式以 LaTeX 文本内嵌在 text block 里（``$...$`` 行内 /
  ``$$...$$`` 独立行），由前端 KaTeX 渲染（1-E-2），后端不做二次处理。
- Phase 3（3-A）动作序列：``Scene.actions`` 落成正式 schema（五种动作
  discriminator union，参考 OpenMAIC ``@openmaic/dsl`` action.ts 的 payload
  定义），Phase 1 存量场景 ``actions=None`` 继续合法（schema_version 区分）。
  生成侧产出动作序列在 3-F 实现，本文件只定义契约。
- schema_version（3-A-4）：v1 = Phase 1 纯翻页（无 actions）；v2 = 引入
  动作序列。Scene 上由 after-validator 在 actions 非空时自动升 v2，
  避免生成侧忘记赋值造成版本漂移。
- 为什么用 Pydantic 而不是 dataclass：schema 同时服务三处校验——
  LLM JSON 输出的结构校验（1-B-2）、HTTP 响应模型（1-B-4）、落库
  payload 的一致性检查。仓库已依赖 fastapi（连带 pydantic），
  引入无新增依赖成本。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class RuntimeContractError(Exception):
    """Runtime 返回结构与呈现引擎的契约不符（如 LCAResult 缺 intervention）.

    与 LLM 侧失败（ValueError / OutlineGenerationError）分开建模：
    前者是本服务与内核之间的契约问题（web 层按 500 处理），后者是
    上游 LLM 问题（web 层按 502 处理）。
    """


def _new_id() -> str:
    """短 ID（对齐 Intervention.intervention_id 的 uuid4 hex[:12] 口径）."""
    return uuid.uuid4().hex[:12]


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# LLM 生成输入：从 LCAResult 提炼的生成上下文
# ---------------------------------------------------------------------------


class GenerationContext(BaseModel):
    """呈现引擎的生成输入（1-A-2 映射表的落点）.

    字段来源见 ``docs/presentation-runtime-map.md``：哪些 LCAResult 字段
    进 LLM prompt、哪些只记录不进，以该映射表为准，改字段先改文档。

    本类型刻意不 import ``cogedu.lca.orchestrator.LCAResult``——呈现引擎
    对内核只读、且只通过 Runtime API；``from_lca_result`` 用 duck-typing
    getattr 读取，连类型引用都不建立（防止未来顺手开始调用其内部方法）。
    """

    student_id: str
    intervention_id: str
    intervention_type: str = "explanatory"
    target_skills: list[str] = Field(default_factory=list)
    target_misconceptions: list[str] = Field(default_factory=list)
    target_tcs: list[str] = Field(default_factory=list)
    difficulty: float = 0.5
    scaffolding_level: float = 0.5
    clt_level: int = 2
    ca_stage: str = "coaching"
    bloom_target: str = "APPLY"
    rationale: str | None = None

    # 以下为引用字段，LCAResult 本身不携带，由调用方（web 层）在知道
    # goal/evidence 上下文时显式传入；Phase 1 允许为 None（见映射表 §3）
    goal_id: str | None = None
    evidence_id: str | None = None

    @classmethod
    def from_lca_result(
        cls,
        lca_result: Any,
        goal_id: str | None = None,
        evidence_id: str | None = None,
    ) -> GenerationContext:
        """从 ``cogedu.runtime.api.plan()`` 的返回值（LCAResult）提取生成上下文.

        Duck-typing 读取：不 import LCAResult 类型。字段缺失时取
        Intervention/LCAResult 的默认值口径（而非静默吞掉——缺失字段
        有默认值属设计内，无需 warning）。
        """
        intervention = getattr(lca_result, "intervention", None)
        if intervention is None:
            raise RuntimeContractError(
                "LCAResult.intervention 缺失：呈现引擎无法在没有 intervention 的情况下生成"
            )

        def _get(obj: Any, name: str, default: Any = None) -> Any:
            value = getattr(obj, name, default)
            # Enum → value（InterventionType/CLTLevel/CAStage 都是 Enum）
            return getattr(value, "value", value)

        return cls(
            student_id=str(_get(lca_result, "student_id", "")),
            intervention_id=str(_get(intervention, "intervention_id", "")),
            intervention_type=str(
                _get(intervention, "intervention_type", "explanatory")
            ),
            target_skills=list(_get(intervention, "target_skills", []) or []),
            target_misconceptions=list(
                _get(intervention, "target_misconceptions", []) or []
            ),
            target_tcs=list(_get(intervention, "target_tcs", []) or []),
            difficulty=float(_get(intervention, "difficulty", 0.5)),
            scaffolding_level=float(_get(intervention, "scaffolding_level", 0.5)),
            clt_level=int(_get(intervention, "clt_level", 2)),
            ca_stage=str(_get(intervention, "ca_stage", "coaching")),
            bloom_target=str(_get(intervention, "bloom_target", "APPLY")),
            rationale=_get(intervention, "rationale", None)
            or _get(lca_result, "rationale", None),
            goal_id=goal_id,
            evidence_id=evidence_id,
        )


# ---------------------------------------------------------------------------
# Phase 3（3-A）：白板/语音动作模型与协议
# ---------------------------------------------------------------------------

# 白板虚拟画布（3-A-2）：固定像素坐标，原点左上，宽 1000、16:9 高 562.5。
# 非归一化/百分比——OpenMAIC whiteboard 同款语义；前端按容器等比缩放。
WB_CANVAS_WIDTH = 1000.0
WB_CANVAS_HEIGHT = 562.5

# schema 版本（3-A-4）：v1 = Phase 1 纯翻页（无 actions）；v2 = 引入动作序列
SCHEMA_VERSION_V1 = 1
SCHEMA_VERSION_V2 = 2

# 动作白名单（v0.6 范围重申：四动作 + wb_draw_line，其余 OpenMAIC 动作类型
# ——spotlight/laser/widget_*/wb_clear 等——明确排除在 v1 外）。3-F 生成侧
# 解析 LLM 输出时据此过滤：白名单外动作丢弃 + warning 留痕，不拒绝整场。
ALLOWED_ACTION_TYPES: tuple[str, ...] = (
    "wb_draw_text",
    "wb_draw_shape",
    "wb_draw_line",
    "wb_draw_latex",
    "speech",
)


def is_allowed_action_type(type_name: object) -> bool:
    """动作白名单判定（3-F 生成侧过滤 + 测试穷尽性校验用）."""
    return type_name in ALLOWED_ACTION_TYPES


def clamp_canvas_point(x: float, y: float) -> tuple[float, float]:
    """把一个画布坐标点 clamp 进虚拟画布（3-A-2）.

    生成侧（3-F）解析 LLM 动作时调用：越界值收进画布并由调用方留
    warning，不拒绝整场。纯函数，不做任何 IO/日志。
    """
    return (
        min(max(x, 0.0), WB_CANVAS_WIDTH),
        min(max(y, 0.0), WB_CANVAS_HEIGHT),
    )


class ActionBase(BaseModel):
    """动作公共字段（3-A-1/3-A-3）.

    - ``action_id`` 由生成侧统一重分配（LLM 给的 id 不可信，对齐
      Phase 1 ``step_id`` 惯例）；字段存在是为幂等键（如 TTS
      ``tts_{scene_id}_{action_id}``）与前端定位。
    - ``estimated_duration_ms`` 由生成侧按 3-E 时间常量估算回填，
      调度侧不做绝对时间轴（顺序事件驱动），预计时长只服务时间轴
      预览与未来导出。None = 尚未估算。
    """

    action_id: str = Field(default_factory=_new_id)
    estimated_duration_ms: int | None = None


class WbDrawTextAction(ActionBase):
    """白板文字：content 为纯文本（LLM 文本前端一律 textContent 渲染）."""

    type: Literal["wb_draw_text"] = "wb_draw_text"
    content: str
    x: float
    y: float
    width: float = 400.0
    font_size: float = 18.0
    color: str = "#333333"


class WbDrawShapeAction(ActionBase):
    """白板图形：v1 仅 rectangle/circle/triangle 三种（OpenMAIC 同款）."""

    type: Literal["wb_draw_shape"] = "wb_draw_shape"
    shape: Literal["rectangle", "circle", "triangle"]
    x: float
    y: float
    width: float = 200.0
    height: float = 200.0
    fill_color: str = "#5b9bd5"


class WbDrawLineAction(ActionBase):
    """白板线段（v0.6 增补）：两点式；数理化画坐标轴/数轴/辅助线的刚需."""

    type: Literal["wb_draw_line"] = "wb_draw_line"
    x1: float
    y1: float
    x2: float
    y2: float
    color: str = "#333333"
    stroke_width: float = 2.0


class WbDrawLatexAction(ActionBase):
    """白板公式：LaTeX 串，前端复用 scene 页的 KaTeX 渲染函数（3-B-2）."""

    type: Literal["wb_draw_latex"] = "wb_draw_latex"
    latex: str
    x: float
    y: float
    width: float = 400.0
    color: str = "#000000"


class SpeechAction(ActionBase):
    """语音讲解：audio_id 由 3-F 异步预生成后回填（tts_{scene_id}_{action_id}），
    播放侧无 audio_id 时走估算计时器静音降级（3-D-5）。"""

    type: Literal["speech"] = "speech"
    text: str
    voice: str | None = None
    speed: float = 1.0
    audio_id: str | None = None


# 动作 union：LLM JSON 输出 / HTTP 响应 / 落库 payload 三处共用同一校验
# （对齐 SceneBlock 的 discriminator 模式；Pydantic union 即运行时穷尽性校验）
SceneAction = Annotated[
    WbDrawTextAction
    | WbDrawShapeAction
    | WbDrawLineAction
    | WbDrawLatexAction
    | SpeechAction,
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Outline（第一阶段输出）
# ---------------------------------------------------------------------------


class OutlineStep(BaseModel):
    """大纲单步：一个讲解步骤（对应后续一个 Scene）."""

    step_id: str = Field(default_factory=_new_id)
    title: str
    key_points: list[str] = Field(default_factory=list)
    objective: str | None = None


class Outline(BaseModel):
    """两阶段生成的第一阶段输出：结构化大纲.

    参考对象：OpenMAIC outline-types.ts ``SceneOutline``（233 行体量的
    outline-generator 的输出类型），按 Phase 1 范围裁剪——无
    widget/media 概念，只有讲解步骤序列。
    """

    outline_id: str = Field(default_factory=_new_id)
    student_id: str
    intervention_id: str
    goal_id: str | None = None
    evidence_id: str | None = None
    title: str
    steps: list[OutlineStep]
    created_at: str = Field(default_factory=_utcnow_iso)
    # schema 版本（3-A-4）：随 payload 落库，前端/查询方可据此区分新旧结构
    schema_version: int = SCHEMA_VERSION_V1
    # 生成上下文随 Outline 落库：第二阶段（场景生成）从持久化层恢复
    # outline 后需要同一份 pedagogy 字段重建 prompt——不存的话
    # difficulty/clt_level 等会丢，场景与大纲的针对性就脱节了
    context: GenerationContext | None = None


# ---------------------------------------------------------------------------
# Scene（第二阶段输出）
# ---------------------------------------------------------------------------


class TextBlock(BaseModel):
    """文字区块：可含 ``$...$`` / ``$$...$$`` LaTeX 公式标记（1-E-2 渲染）."""

    type: Literal["text"] = "text"
    content: str


class ImageBlock(BaseModel):
    """图片区块.

    v1 决策（2026-09-12）：只做静态占位/示意图——``placeholder=True``
    且 ``url`` 为空或指向本地占位资源；``image_provider`` 接口留出生成/
    检索位（1-C-2），不在 Phase 1 实现。
    """

    type: Literal["image"] = "image"
    url: str | None = None
    alt: str = ""
    placeholder: bool = False


SceneBlock = Annotated[TextBlock | ImageBlock, Field(discriminator="type")]


class Scene(BaseModel):
    """场景：大纲单步的具体内容（Phase 1 = 讲解文字 + 配图）.

    参考对象：OpenMAIC scene-types.ts ``CompleteScene``（1931 行体量的
    scene-generator 的输出类型），按 Phase 1 范围裁剪为 text/image 两种
    block、单一讲解视角（多角色讨论 / AI 同学插话是 v1 范围外，
    见方案文档第 3/8 章）。
    """

    scene_id: str = Field(default_factory=_new_id)
    outline_id: str
    step_id: str
    student_id: str
    # 追溯三字段：引用不拷贝（13.4 的"现在就要带上"，第 11 章可视化的
    # 物理前提）。落库时按 evidence_id / intervention_id 建索引反查。
    intervention_id: str
    goal_id: str | None = None
    evidence_id: str | None = None

    title: str
    blocks: list[SceneBlock]

    # 1-D-3 降级标记：重试耗尽后由模板化降级内容填充，warning 留痕
    degraded: bool = False
    warnings: list[str] = Field(default_factory=list)

    created_at: str = Field(default_factory=_utcnow_iso)

    # schema 版本（3-A-4）：v1 = Phase 1 纯翻页；v2 = 含动作序列。
    # actions 非空时由 after-validator 自动升 v2——版本号是派生事实，
    # 单点维护在模型内，生成侧无需（也不能）手动指定
    schema_version: int = SCHEMA_VERSION_V1

    # Phase 3（3-A）动作序列：白板/语音动作，按数组顺序执行（顺序事件
    # 驱动调度，见 15.4 3-C）。Phase 1 存量恒 None，继续合法（纯翻页渲染）
    actions: list[SceneAction] | None = None

    @model_validator(mode="after")
    def _sync_schema_version(self) -> Scene:
        if self.actions is not None and self.schema_version < SCHEMA_VERSION_V2:
            self.schema_version = SCHEMA_VERSION_V2
        return self
