"""12.4 (0-C): 家长端 FastAPI 路由 — 自 Flask parent.py (v0.98.0 a-b) 迁移.

迁移原则同 routers/teacher.py: 复用 web/api/parent.py + web/api/teacher.py
的框架无关 helpers, 通过模块命名空间调用 (保持测试 patch 面)。

设计决策 (自 Flask 版原样继承, 见 parent.py 文件头):
  - **严禁 _get_or_create_student** (v0.96.9 幽灵学生教训): 家长端只读,
    学生不存在直接 404, 不产生任何 DB 行
  - 单聚合端点 /overview: 一次请求拿全部四卡数据
  - 不放校准视图 / misconceptions (教师专业视图, Bisen 拍板 2026-09-06)

端点 (3, 只读):
  GET /api/parent/students
  GET /api/parent/students/{student_id}/overview
  GET /api/parent/students/{student_id}/report   (2-C-4: Word 报告下载)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from web.api import guardian as guardian_service
from web.api import parent as parent_helpers
from web.api import teacher as teacher_helpers
from web.api.auth import require_roles
from web.api.report import PERIODS

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/parent",
    tags=["parent"],
    # 2-0-3 (14.2): 家长端需 guardian 角色 (staff 兜底可看)。
    # 注: per-student 的 guardian_learner_link 关系校验在 2-A 落地,
    # 本 Phase 只做到"已认证 + 角色正确"粒度 — 遗留缺口已记录在
    # 方案文档 14.3, 不算权限模型完成态。
    dependencies=[Depends(require_roles("guardian", "teacher", "admin"))],
)


# ─── Pydantic 响应模型 ────────────────────────────────────────────────────────


class ParentRosterItem(BaseModel):
    """家长端 roster 单行 (比教师端少: 无 risk/无 bloom 细节, 家长视角)."""

    student_id: str
    subject: str | None = None
    grade_level: str | None = None
    last_active_at: str | None = None
    answered_count: int
    correct_rate: float
    current_state: str | None = None


class ParentRosterResponse(BaseModel):
    students: list[ParentRosterItem]


class ParentOverviewResponse(BaseModel):
    student_id: str
    subject: str | None = None
    engagement: dict[str, Any] | None = None
    five_d: dict[str, Any]
    interventions: list[dict[str, Any]]


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.get("/students", response_model=ParentRosterResponse)
def api_parent_students(
    user: dict = Depends(require_roles("guardian", "teacher", "admin")),  # noqa: B008 (FastAPI 惯用)
):
    """学生列表 (roster, 只读) — 家长端入口.

    严禁 _get_or_create_student (v0.96.9 幽灵学生教训):
    只读 students 表, 空表返回空列表, 不产生任何 DB 行.

    2-A-4 (14.3): guardian 只看到经 guardian_learner_link active 关联的
    学生 (申请 pending 不可见); staff 保持原有全量视图。
    """
    try:
        db = teacher_helpers._get_db()
        if user["role"] == "guardian":
            sids = guardian_service.list_active_linked_student_ids(user["user_id"])
        else:
            sids = db.load_student_ids(limit=100)

        students: list[dict[str, Any]] = []
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
def api_parent_student_overview(
    student_id: str,
    user: dict = Depends(require_roles("guardian", "teacher", "admin")),  # noqa: B008 (FastAPI 惯用)
):
    """单聚合 overview: engagement + advice + five_d + interventions (四卡数据).

    只读: 学生不存在 → 404 (不创建; 防幽灵学生).

    2-A-4 (14.3): guardian 须持有对该学生的 active view_progress 授权,
    未关联/权限不足 → 403 (每次现查 guardian_learner_link, 撤销立即生效);
    staff 不受限。
    """
    try:
        if user["role"] == "guardian" and not guardian_service.guardian_can_access_student(
            user["user_id"], student_id, "view_progress"
        ):
            return JSONResponse(
                {"error": "无权访问该学生的数据", "student_id": student_id},
                status_code=403,
            )
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


# ─── 学习报告下载 (2-C-4, Phase 2) ───────────────────────────────────────────


@router.get("/students/{student_id}/report")
def api_parent_student_report(
    student_id: str,
    period: str = "week",
    user: dict = Depends(require_roles("guardian", "teacher", "admin")),  # noqa: B008 (FastAPI 惯用)
):
    """学习报告下载 (Word/docx, 2-C)。

    权限: guardian 须持有对该学生的 active `download_report` 授权
    (2-A-4 单一入口, 每次现查 — 撤销下一请求即失效); staff 不受限。
    错误: period 非法 400 / 学生不存在 404 / 无权限 403。
    """
    try:
        from web.api.docx_renderer import render_report_docx
        from web.api.report import build_report_document

        if user["role"] == "guardian" and not guardian_service.guardian_can_access_student(
            user["user_id"], student_id, "download_report"
        ):
            return JSONResponse(
                {"error": "无权下载该学生的学习报告", "student_id": student_id},
                status_code=403,
            )
        if period not in PERIODS:
            return JSONResponse(
                {"error": f"period 需为 {'/'.join(PERIODS)}", "period": period},
                status_code=400,
            )
        report = build_report_document(student_id, period)
        docx_bytes = render_report_docx(report)
    except LookupError:
        return JSONResponse(
            {"error": "学生不存在", "student_id": student_id}, status_code=404
        )
    except Exception:
        _log.warning(
            "parent: /report 失败 (sid=%s, period=%s)", student_id, period, exc_info=True
        )
        return JSONResponse({"error": "报告生成失败"}, status_code=500)

    from datetime import datetime as _dt

    filename = f"report_{student_id}_{period}_{_dt.now():%Y%m%d}.docx"
    return Response(
        content=docx_bytes,
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
