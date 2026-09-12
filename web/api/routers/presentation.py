"""Phase 1 (1-B-4 / 1-C): 呈现引擎路由.

端点:
  POST /api/presentation/outline — intervention → 大纲 (两阶段生成第一阶段, 落库)
  POST /api/presentation/scenes  — outline_id → 场景列表 (第二阶段, 落库)

调用链 (docs/presentation-runtime-map.md §1/§2):
  plan(student_id) → GenerationContext.from_lca_result → OutlineGenerator
  → 落库 (context 随 Outline 保存, 供第二阶段恢复) → scenes
  LLM client 注入 (1-A-5): 经 web.api.llm.get_llm(), 测试 patch 该模块属性。
  失败语义: 不静默 — LLM/解析失败 502 + warning 留痕; 落库失败不中断
  呈现 (1-D 的重试/降级落地后 502 路径收敛为 degraded scene)。
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from cogedu.presentation.outline import OutlineGenerationError, OutlineGenerator
from cogedu.presentation.scene import SceneGenerationError
from cogedu.presentation.types import GenerationContext, Outline, RuntimeContractError, Scene

# patch 面约定: 测试 monkeypatch 本模块命名空间的 plan
# (呈现引擎对内核的唯一入口 = cogedu.runtime.api, 见映射表 §1)
from cogedu.runtime.api import plan
from web.api import llm as llm_service
from web.api.auth import require_student_access
from web.api.presentation_service import (
    _RETRY_POLICY,
    generate_scenes_for_outline,
    persist_outline,
)

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/presentation",
    tags=["presentation"],
    # 2-0-3 (14.2): 场景生成/行为回写需学生本人 (student_id 在请求体,
    # dependency 从 body 取; staff 可代操作)
    dependencies=[Depends(require_student_access)],
)


class OutlineRequest(BaseModel):
    """POST /api/presentation/outline 请求体.

    goal_id/evidence_id 由调用方在知道上下文时显式传入（映射表 §3:
    从答错链路进入时带上该次答题的 evidence_id; Phase 1 允许 None）。
    """

    student_id: str
    goal_id: str | None = None
    evidence_id: str | None = None
    kb_snippets: list[str] | None = None


class ScenesRequest(BaseModel):
    """POST /api/presentation/scenes 请求体."""

    outline_id: str


class SceneEventRequest(BaseModel):
    """POST /api/presentation/event 请求体 (1-F 场景行为回写)."""

    student_id: str
    outline_id: str
    event_type: str  # "scene_viewed" | "scene_completed"
    scene_id: str | None = None
    step_id: str | None = None
    dwell_sec: float = Field(default=0.0, ge=0)
    index: int = Field(default=0, ge=0)
    scene_count: int = Field(default=0, ge=0)
    total_dwell_sec: float = Field(default=0.0, ge=0)


@router.post("/outline", response_model=Outline)
def generate_outline(req: OutlineRequest):
    """两阶段生成第一阶段: Runtime plan → GenerationContext → 大纲 → 落库."""
    try:
        lca_result = plan(req.student_id, audience="student")
        ctx = GenerationContext.from_lca_result(
            lca_result,
            goal_id=req.goal_id,
            evidence_id=req.evidence_id,
        )
        generator = OutlineGenerator(llm_service.get_llm())
        outline = generator.generate(
            ctx, kb_snippets=req.kb_snippets, policy=_RETRY_POLICY
        )
        # 生成上下文随大纲落库: 第二阶段 (/scenes) 从持久化层恢复后
        # 需要同一份 pedagogy 字段重建 prompt (见 Outline.context 注记)
        outline.context = ctx
        if not persist_outline(outline):
            # 落库失败不中断呈现, 但必须可感知 (save_outline 已 warning)
            _log.warning(
                "outline 落库失败 (outline=%s, sid=%s), 本次会话内不可回放",
                outline.outline_id, req.student_id,
            )
        return outline
    except RuntimeContractError as e:
        # 与内核的契约不符 — 本服务侧问题, 500 (区别于上游 LLM 的 502)
        _log.error("outline runtime contract error (sid=%s): %s", req.student_id, e)
        return JSONResponse({"error": str(e)}, status_code=500)
    except (OutlineGenerationError, ValueError, RuntimeError) as e:
        # LLM 输出不合规/解析失败/传输层耗尽 — 上游问题, 502 + warning 留痕 (不静默吞)
        _log.warning(
            "outline generation failed (sid=%s): %s", req.student_id, e
        )
        return JSONResponse({"error": f"大纲生成失败: {e}"}, status_code=502)
    except Exception as e:
        _log.error(
            "outline generation unexpected error (sid=%s)", req.student_id, exc_info=True
        )
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/scenes", response_model=list[Scene])
def generate_scenes(req: ScenesRequest):
    """两阶段生成第二阶段: outline_id → 每步一个 Scene → 落库 → 返回."""
    try:
        return generate_scenes_for_outline(req.outline_id)
    except LookupError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except (SceneGenerationError, ValueError, RuntimeError) as e:
        # 解析失败 (重试耗尽也不该到这——service 层已降级) / 传输层耗尽:
        # 均为上游问题, 502 + warning 留痕 (不静默吞)
        _log.warning("scene generation failed (outline=%s): %s", req.outline_id, e)
        return JSONResponse({"error": f"场景生成失败: {e}"}, status_code=502)
    except Exception as e:
        _log.error(
            "scene generation unexpected error (outline=%s)",
            req.outline_id, exc_info=True,
        )
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/event")
def scene_event(req: SceneEventRequest) -> dict[str, Any]:
    """1-F (13.7): 场景行为回写 — 埋点 → LearningEvent → bus + event_log.

    Plugin SDK 原则: 端点不写 state, 只产生 event (PluginRuntime subscriber
    → human feedback 通道消费, 见映射表 §6)。emit/落库复用 event_stub 的
    _emit_event (fail-open + warning 留痕, 与 hint/reflection 端点同语义)。
    """
    from cogedu.cta.event_log import LearningEvent

    if req.event_type == "scene_viewed":
        payload: dict[str, Any] = {
            "outline_id": req.outline_id,
            "scene_id": req.scene_id,
            "step_id": req.step_id,
            "dwell_sec": req.dwell_sec,
            "index": req.index,
        }
    elif req.event_type == "scene_completed":
        payload = {
            "outline_id": req.outline_id,
            "scene_count": req.scene_count,
            "total_dwell_sec": req.total_dwell_sec,
        }
    else:
        return JSONResponse(
            {"error": "event_type 必须是 scene_viewed / scene_completed"},
            status_code=400,
        )

    event = LearningEvent.from_scene_behavior(
        event_type=req.event_type,
        student_id=req.student_id,
        payload=payload,
    )
    # 复用 event_stub 的 emit + 落库 helper (bus publish + event_log 持久化)
    from web.api.event_stub import _emit_event

    return _emit_event(req.student_id, event)
