"""1-A-1 (Phase 1, 13.2): 呈现引擎契约类型 — Outline / Scene schema.

设计要点：

- Scene 与内核对象的关联是**引用不拷贝**：intervention_id / goal_id /
  evidence_id 只存 ID 字符串，Goal/Evidence 对象本体不进 Scene。
- Phase 1 内容区块只有 ``text`` / ``image`` 两种（参考第 11 章 DeepTutor
  ``BlockType`` 的思路，但不一次性做全）；后续类型（quiz/interactive 等，
  参考 OpenMAIC scene-types.ts）按 Phase 需要扩展 discriminator union。
- 数学公式以 LaTeX 文本内嵌在 text block 里（``$...$`` 行内 /
  ``$$...$$`` 独立行），由前端 KaTeX 渲染（1-E-2），后端不做二次处理。
- Phase 3 扩展点：``Scene.actions`` 字段已预留（白板/语音动作序列），
  Phase 1 恒为 None，不产出。
- 为什么用 Pydantic 而不是 dataclass：schema 同时服务三处校验——
  LLM JSON 输出的结构校验（1-B-2）、HTTP 响应模型（1-B-4）、落库
  payload 的一致性检查。仓库已依赖 fastapi（连带 pydantic），
  引入无新增依赖成本。
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


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
            raise ValueError(
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

    # Phase 3 扩展点（白板/语音动作序列 wb_draw_text/speech 等），
    # Phase 1 恒为 None，不产出——留字段位置只为免将来 schema 破坏性变更
    actions: list[dict[str, Any]] | None = None
