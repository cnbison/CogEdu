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

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cogedu.presentation.outline import OutlineGenerationError, OutlineGenerator
from cogedu.presentation.scene import SceneGenerationError
from cogedu.presentation.types import GenerationContext, Outline, RuntimeContractError, Scene

# patch 面约定: 测试 monkeypatch 本模块命名空间的 plan
# (呈现引擎对内核的唯一入口 = cogedu.runtime.api, 见映射表 §1)
from cogedu.runtime.api import plan
from web.api import llm as llm_service
from web.api.presentation_service import (
    generate_scenes_for_outline,
    persist_outline,
)

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/presentation", tags=["presentation"])


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
        outline = generator.generate(ctx, kb_snippets=req.kb_snippets)
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
    except (OutlineGenerationError, ValueError) as e:
        # LLM 输出不合规/解析失败 — 上游问题, 502 + warning 留痕 (不静默吞)
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
    except (SceneGenerationError, ValueError) as e:
        _log.warning("scene generation failed (outline=%s): %s", req.outline_id, e)
        return JSONResponse({"error": f"场景生成失败: {e}"}, status_code=502)
    except Exception as e:
        _log.error(
            "scene generation unexpected error (outline=%s)",
            req.outline_id, exc_info=True,
        )
        return JSONResponse({"error": str(e)}, status_code=500)
