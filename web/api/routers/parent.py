"""12.4 (0-C): 家长端 FastAPI 路由 — 自 Flask parent.py (v0.98.0 a-b) 迁移.

迁移原则同 routers/teacher.py: 复用 web/api/parent.py + web/api/teacher.py
的框架无关 helpers, 通过模块命名空间调用 (保持测试 patch 面)。

设计决策 (自 Flask 版原样继承, 见 parent.py 文件头):
  - **严禁 _get_or_create_student** (v0.96.9 幽灵学生教训): 家长端只读,
    学生不存在直接 404, 不产生任何 DB 行
  - 单聚合端点 /overview: 一次请求拿全部四卡数据
  - 不放校准视图 / misconceptions (教师专业视图, Bisen 拍板 2026-09-06)

端点 (2, 只读):
  GET /api/parent/students
  GET /api/parent/students/{student_id}/overview
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from web.api import parent as parent_helpers
from web.api import teacher as teacher_helpers

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/parent", tags=["parent"])


# ─── Pydantic 响应模型 ────────────────────────────────────────────────────────


class ParentRosterItem(BaseModel):
    """家长端 roster 单行 (比教师端少: 无 risk/无 bloom 细节, 家长视角)."""

    student_id: str
    subject: Optional[str] = None
    grade_level: Optional[str] = None
    last_active_at: Optional[str] = None
    answered_count: int
    correct_rate: float
    current_state: Optional[str] = None


class ParentRosterResponse(BaseModel):
    students: List[ParentRosterItem]


class ParentOverviewResponse(BaseModel):
    student_id: str
    subject: Optional[str] = None
    engagement: Optional[Dict[str, Any]] = None
    five_d: Dict[str, Any]
    interventions: List[Dict[str, Any]]


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.get("/students", response_model=ParentRosterResponse)
def api_parent_students():
    """学生列表 (roster, 只读) — 家长端入口.

    严禁 _get_or_create_student (v0.96.9 幽灵学生教训):
    只读 students 表, 空表返回空列表, 不产生任何 DB 行.
    """
    try:
        db = teacher_helpers._get_db()
        sids = db.load_student_ids(limit=100)

        students: List[Dict[str, Any]] = []
        for sid in sids:
            row = teacher_helpers._load_student_row(sid)
            if row is None:
                continue
            responses = teacher_helpers._parse_responses(sid)
            answered_count = len(responses)
            correct_count = sum(1 for r in responses if r["correct"])
            correct_rate = (
                round(correct_count / answered_count, 4) if answered_count else 0.0
            )
            report = parent_helpers._get_engagement_report(sid)

            students.append({
                "student_id": sid,
                "subject": row.get("subject"),
                "grade_level": row.get("grade_level"),
                "last_active_at": row.get("last_active_at"),
                "answered_count": answered_count,
                "correct_rate": correct_rate,
                "current_state": (report or {}).get("current_state"),
            })

        return {"students": students}
    except Exception:
        _log.warning("parent: /api/parent/students 失败", exc_info=True)
        return JSONResponse(
            {"error": "学生列表获取失败", "students": []}, status_code=500
        )


@router.get(
    "/students/{student_id}/overview", response_model=ParentOverviewResponse
)
def api_parent_student_overview(student_id: str):
    """单聚合 overview: engagement + advice + five_d + interventions (四卡数据).

    只读: 学生不存在 → 404 (不创建; 防幽灵学生).
    """
    try:
        row = teacher_helpers._load_student_row(student_id)
        if row is None:
            return JSONResponse(
                {"error": "学生不存在", "student_id": student_id}, status_code=404
            )

        engagement = parent_helpers._get_engagement_report(student_id)
        interventions = teacher_helpers._get_intervention_history(student_id)
        bloom = teacher_helpers._parse_bloom_summary(row)
        theta = teacher_helpers._parse_theta(row)

        return {
            "student_id": student_id,
            "subject": row.get("subject"),
            "engagement": engagement,
            "five_d": {
                "mastery": theta,
                "bloom": bloom,
                "overall_confidence": round(
                    float(row.get("confidence") or 0.0), 4
                ),
            },
            "interventions": interventions,
        }
    except Exception:
        _log.warning(
            "parent: /overview 失败 (sid=%s)", student_id, exc_info=True
        )
        return JSONResponse(
            {"error": "概览获取失败", "student_id": student_id}, status_code=500
        )
