"""12.4 (0-C): 前端事件端点 FastAPI 路由 — 自 Flask event_stub.py (v0.85.0-d) 迁移.

4 个端点供 frontend 调用, emit 4 个 event_type:
  - POST /api/event/hint         -> HINT_REQUESTED (+ v0.96.7 规则 hint 内容)
  - POST /api/event/idle         -> IDLE_DETECTED
  - POST /api/event/goal_change  -> GOAL_CHANGED
  - POST /api/event/reflection   -> REFLECTION_COMPLETED

Plugin SDK 原则: endpoint 不写 state, 只产生 event (subscriber 处理)。

迁移差异说明 (有意为之, 非 bug):
  - 请求校验改由 Pydantic 模型承担: 缺字段/类型错 → 422 (Flask 版是
    手工 KeyError 捕获 → 400)。422 是 FastAPI 的标准校验失败码,
    响应体结构也不同 (detail 数组) — 前端现有调用均为合法请求,
    无测试断言 400 响应体, 此变更可接受。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from web.api.auth import require_student_access

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/event",
    tags=["events"],
    # 2-0-3 (14.2): 行为回写需学生本人 (student_id 在请求体, dependency
    # 从 body 取; staff 可代操作)
    dependencies=[Depends(require_student_access)],
)

# 复用 Flask 版模块里的框架无关 helpers (hint 规则生成 + emit + 落库),
# 12.4-6 翻转时该模块去掉 Flask 路由层保留 helpers
from web.api import event_stub as event_helpers  # noqa: E402


# ─── Pydantic 请求模型 (替代 Flask 手写 JSON 解析/校验) ──────────────────────


class HintRequest(BaseModel):
    student_id: str
    problem_id: str
    hint_level: int = Field(default=1, ge=1, le=3)


class IdleRequest(BaseModel):
    student_id: str
    idle_seconds: float = Field(ge=0)


class GoalChangeRequest(BaseModel):
    student_id: str
    old_goal_id: str
    new_goal_id: str


class ReflectionRequest(BaseModel):
    student_id: str
    reflection_text: str
    problem_id: Optional[str] = None


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.post("/hint")
def api_event_hint(req: HintRequest) -> Dict[str, Any]:
    """frontend 学生请求提示.

    v0.96.7: 除埋点外, 基于题目元数据返回规则生成的 hint 内容（不泄漏答案）。
    """
    try:
        from cogedu.cta.event_log import LearningEvent

        event = LearningEvent.from_hint_requested(
            student_id=req.student_id,
            problem_id=req.problem_id,
            hint_level=req.hint_level,
        )
        result = event_helpers._emit_event(req.student_id, event)

        from web.api.qmatrix import get_question_detail

        problem = get_question_detail(req.problem_id)
        if problem is None:
            _log.warning(
                "events: hint 请求 problem_id=%r 不在 Q 矩阵, 返回兜底提示",
                req.problem_id,
            )
            result["hint"] = (
                "这道题暂时没有针对性的提示。先通读题目、回顾相关概念，"
                "把思路写出来再作答。"
            )
        else:
            result["hint"] = event_helpers._build_hint(problem)
        return result
    except Exception as e:
        _log.warning("/api/event/hint 失败: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/idle")
def api_event_idle(req: IdleRequest):
    """frontend 检测学生 idle."""
    try:
        from cogedu.cta.event_log import LearningEvent

        event = LearningEvent.from_idle_detected(
            student_id=req.student_id,
            idle_seconds=req.idle_seconds,
        )
        return event_helpers._emit_event(req.student_id, event)
    except Exception as e:
        _log.warning("/api/event/idle 失败: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/goal_change")
def api_event_goal_change(req: GoalChangeRequest):
    """frontend 学生切换学习目标."""
    try:
        from cogedu.cta.event_log import LearningEvent

        event = LearningEvent.from_goal_changed(
            student_id=req.student_id,
            old_goal_id=req.old_goal_id,
            new_goal_id=req.new_goal_id,
        )
        return event_helpers._emit_event(req.student_id, event)
    except Exception as e:
        _log.warning("/api/event/goal_change 失败: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/reflection")
def api_event_reflection(req: ReflectionRequest):
    """frontend 学生完成反思."""
    try:
        from cogedu.cta.event_log import LearningEvent

        event = LearningEvent.from_reflection_completed(
            student_id=req.student_id,
            reflection_text=req.reflection_text,
            problem_id=req.problem_id,
        )
        return event_helpers._emit_event(req.student_id, event)
    except Exception as e:
        _log.warning("/api/event/reflection 失败: %s", e, exc_info=True)
        return JSONResponse({"error": str(e)}, status_code=500)
