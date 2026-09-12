"""Phase 1 (1-B-4 / 1-C): 呈现引擎路由.

端点:
  POST /api/presentation/outline — intervention → 大纲 (两阶段生成第一阶段)
  POST /api/presentation/scenes  — 大纲 → 场景列表 (第二阶段, 1-C)

调用链 (docs/presentation-runtime-map.md §1/§2):
  plan(student_id) → GenerationContext.from_lca_result → OutlineGenerator
  LLM client 注入 (1-A-5): 经 web.api.llm.get_llm(), 测试 patch 该模块属性。
  失败语义: 不静默 — LLM/解析失败 502 + warning 留痕, 1-D 的重试/降级
  落地后 502 路径收敛为 degraded scene。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from cogedu.presentation.outline import OutlineGenerationError, OutlineGenerator
from cogedu.presentation.types import GenerationContext, Outline, RuntimeContractError

# patch 面约定: 测试 monkeypatch 本模块命名空间的 plan
# (呈现引擎对内核的唯一入口 = cogedu.runtime.api, 见映射表 §1)
from cogedu.runtime.api import plan
from web.api import llm as llm_service

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


@router.post("/outline", response_model=Outline)
def generate_outline(req: OutlineRequest):
    """两阶段生成第一阶段: Runtime plan → GenerationContext → 大纲."""
    try:
        lca_result = plan(req.student_id, audience="student")
        ctx = GenerationContext.from_lca_result(
            lca_result,
            goal_id=req.goal_id,
            evidence_id=req.evidence_id,
        )
        generator = OutlineGenerator(llm_service.get_llm())
        return generator.generate(ctx, kb_snippets=req.kb_snippets)
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


# POST /api/presentation/scenes (两阶段第二阶段) 随 1-C 加入
