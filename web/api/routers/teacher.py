"""12.4 (0-C): 教师端 FastAPI 路由 — 自 Flask teacher.py (v0.95.1) 迁移.

迁移原则 (见 routers/__init__.py):
  - 业务逻辑不复制: 复用 web/api/teacher.py 的框架无关 helpers
    (DB 直读解析 + progress report), 该模块在 12.4-6 翻转时去掉
    Flask 路由层保留 helpers
  - 通过模块命名空间调 helpers (teacher_helpers._get_db()), 保持测试
    monkeypatch("web.api.teacher._get_db") 的patch 面不变
  - 响应 JSON 形状与 Flask 版逐字段一致 (前端零改动)
  - in-function import 模式保留 (load_tracker_for_student 等), 与
    Flask 版 patch 面一致

端点 (7, 全部只读, 不 mutate Kernel state):
  GET /api/teacher/students
  GET /api/teacher/students/{student_id}
  GET /api/teacher/students/{student_id}/evidence
  GET /api/teacher/students/{student_id}/diagnostic
  GET /api/teacher/students/{student_id}/interventions
  GET /api/teacher/students/{student_id}/calibration
  GET /api/teacher/students/{student_id}/misconceptions
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from web.api.auth import require_roles
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from web.api import teacher as teacher_helpers

_log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/teacher",
    tags=["teacher"],
    # 2-0-3 (14.2): 教师端仅 staff 可访问
    dependencies=[Depends(require_roles("teacher", "admin"))],
)


# ─── Pydantic 响应模型 (12.4: 替代 Flask 手写 JSON 的结构声明) ───────────────
# 动态字段 (plugin report / POMDP diagnostic 等) 用 Any 收纳 — 这些结构
# 由插件/内核演进, 路由层强行建模会制造虚假精度。


class RosterStudentItem(BaseModel):
    """班级列表单行 (前端渲染契约, 字段缺失=渲染破相)."""

    student_id: str
    last_active_at: Optional[str] = None
    subject: Optional[str] = None
    grade_level: Optional[str] = None
    answered_count: int
    correct_rate: float
    bloom_dominant: Optional[str] = None
    overall_confidence: float
    cold_start: Optional[bool] = None
    most_likely_state: Optional[str] = None
    risk: str
    intervention_count: int


class RosterResponse(BaseModel):
    students: List[RosterStudentItem]


class StudentDetailResponse(BaseModel):
    student_id: str
    answered_count: int
    correct_rate: float
    bloom_profile: Optional[Dict[str, Any]] = None
    theta_5d: Optional[Dict[str, float]] = None
    overall_confidence: float
    report: Optional[Dict[str, Any]] = None
    trajectory_summary: List[Dict[str, Any]]


class CalibrationCurveItem(BaseModel):
    bucket: str
    n: int
    correct: int
    predicted: float
    actual_rate: float
    correction_factor: float


class CalibrationResponse(BaseModel):
    student_id: str
    has_data: bool
    n_total: int
    n_self_assessed: int
    n_skipped: int
    curves: List[CalibrationCurveItem]


class MisconceptionItem(BaseModel):
    misc_id: str
    name: str
    description: str
    correction_strategy: str
    success_count: int
    failure_count: int
    total: int
    laplace_confidence: float
    quarantined: bool
    last_updated: str


class MisconceptionsResponse(BaseModel):
    student_id: str
    has_data: bool
    items: List[MisconceptionItem]


# ─── 路由 ────────────────────────────────────────────────────────────────────


@router.get("/students", response_model=RosterResponse)
def api_teacher_students():
    """班级列表 (roster): 教师扫全班入口."""
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

            bloom = teacher_helpers._parse_bloom_summary(row)
            report = teacher_helpers._get_progress_report(sid)

            # 风险 flag: Frustrated / Bored / Confused → 需关注
            risk = "ok"
            if report is not None:
                state = report.get("most_likely_state")
                if state in ("Frustrated", "Bored", "Confused"):
                    risk = "attention"

            students.append({
                "student_id": sid,
                "last_active_at": row.get("last_active_at"),
                "subject": row.get("subject"),
                "grade_level": row.get("grade_level"),
                "answered_count": answered_count,
                "correct_rate": correct_rate,
                "bloom_dominant": (bloom or {}).get("dominant"),
                "overall_confidence": round(float(row.get("confidence") or 0.0), 4),
                "cold_start": (report or {}).get("cold_start"),
                "most_likely_state": (report or {}).get("most_likely_state"),
                "risk": risk,
                "intervention_count": len(
                    teacher_helpers._get_intervention_history(sid)
                ),
            })

        return {"students": students}
    except Exception:
        _log.warning("teacher: /api/teacher/students 失败", exc_info=True)
        return JSONResponse(
            {"error": "班级列表获取失败", "students": []}, status_code=500
        )


@router.get("/students/{student_id}", response_model=StudentDetailResponse)
def api_teacher_student_detail(student_id: str):
    """学生详情: state 摘要 + 教学建议 (单生深潜的概览卡)."""
    try:
        row = teacher_helpers._load_student_row(student_id)
        if row is None:
            return JSONResponse({"error": "学生不存在"}, status_code=404)

        responses = teacher_helpers._parse_responses(student_id)
        answered_count = len(responses)
        correct_count = sum(1 for r in responses if r["correct"])
        correct_rate = (
            round(correct_count / answered_count, 4) if answered_count else 0.0
        )

        trajectory = teacher_helpers._json_field(row, "trajectory_summary")
        if not isinstance(trajectory, list):
            trajectory = []

        return {
            "student_id": student_id,
            "answered_count": answered_count,
            "correct_rate": correct_rate,
            "bloom_profile": teacher_helpers._parse_bloom_summary(row),
            "theta_5d": teacher_helpers._parse_theta(row),
            "overall_confidence": round(float(row.get("confidence") or 0.0), 4),
            "report": teacher_helpers._get_progress_report(student_id),
            "trajectory_summary": [
                {
                    "timestamp": t.get("timestamp"),
                    "theta_5d": t.get("theta_5d"),
                    "confidence": t.get("confidence"),
                    "bloom_dominant": t.get("bloom_dominant"),
                }
                for t in trajectory
                if isinstance(t, dict)
            ],
        }
    except Exception:
        _log.warning(
            "teacher: /api/teacher/students/%s 失败", student_id, exc_info=True
        )
        return JSONResponse({"error": "学生详情获取失败"}, status_code=500)


@router.get("/students/{student_id}/evidence")
def api_teacher_student_evidence(student_id: str):
    """证据链视图: "系统为什么这么判断" — 按 5D 维度聚合 + 可下钻.

    结构动态 (dimensions 内嵌 responses 列表), 不强行 response_model。
    """
    try:
        row = teacher_helpers._load_student_row(student_id)
        if row is None:
            return JSONResponse({"error": "学生不存在"}, status_code=404)

        responses = teacher_helpers._parse_responses(student_id)
        misconceptions = teacher_helpers._parse_misconceptions(student_id)
        tc_states = teacher_helpers._parse_tc_states(student_id)

        # theta_cov diag → SE (从 DB theta_cov 列)
        theta_cov = teacher_helpers._json_field(row, "theta_cov")
        se_map: Dict[str, float] = {}
        if isinstance(theta_cov, list) and len(theta_cov) == 5:
            import math as _math

            for i, dim in enumerate(["K", "P", "S", "C", "X"]):
                try:
                    se_map[dim] = round(
                        float(_math.sqrt(max(float(theta_cov[i][i]), 1e-6))), 4
                    )
                except Exception:
                    se_map[dim] = 1.0

        theta = teacher_helpers._parse_theta(row) or {
            d: 0.0 for d in ["K", "P", "S", "C", "X"]
        }

        # 按维度聚合证据
        dimensions: Dict[str, Dict[str, Any]] = {}
        for i, dim in enumerate(["K", "P", "S", "C", "X"]):
            dim_responses = [r for r in responses if r["dims"][i]]
            dim_count = len(dim_responses)
            dim_correct = sum(1 for r in dim_responses if r["correct"])
            mastered = (
                1.0 / (1.0 + 2.718281828459045 ** (-theta[dim])) >= 0.5
            )
            dimensions[dim] = {
                "label": teacher_helpers.DIMENSION_LABELS[dim]["label"],
                "full": teacher_helpers.DIMENSION_LABELS[dim]["full"],
                "desc": teacher_helpers.DIMENSION_LABELS[dim]["desc"],
                "theta": theta[dim],
                "se": se_map.get(dim, 1.0),
                "confidence": round(1.0 / (1.0 + se_map.get(dim, 1.0)), 4),
                "mastered": mastered,
                "response_count": dim_count,
                "correct_rate": (
                    round(dim_correct / dim_count, 4) if dim_count else 0.0
                ),
                "responses": [
                    {k: v for k, v in r.items() if k != "dims"}
                    for r in dim_responses
                ],
            }

        return {
            "student_id": student_id,
            "summary": {
                "answered_count": len(responses),
                "correct_rate": round(
                    sum(1 for r in responses if r["correct"]) / len(responses), 4
                )
                if responses
                else 0.0,
            },
            "dimensions": dimensions,
            "misconceptions": misconceptions,
            "tc_states": tc_states,
        }
    except Exception:
        _log.warning(
            "teacher: /api/teacher/students/%s/evidence 失败",
            student_id,
            exc_info=True,
        )
        return JSONResponse({"error": "证据链获取失败"}, status_code=500)


@router.get("/students/{student_id}/diagnostic")
def api_teacher_student_diagnostic(student_id: str):
    """POMDP 诊断: belief 分布 + coverage + 教学建议 (T/R 后验可视化)."""
    try:
        from web.api.lca import _get_or_create_lca_state, get_lca_engine

        _get_or_create_lca_state(student_id)
        lca_engine = get_lca_engine()

        from cogedu.runtime.api import diagnose_pomdp

        diagnostic = diagnose_pomdp(student_id=student_id, lca_engine=lca_engine)

        report = None
        plugin = teacher_helpers._get_teacher_progress_plugin()
        if diagnostic is not None:
            if plugin is not None:
                report = plugin.ingest_diagnostic(student_id, diagnostic)
            else:
                report = None

        return {
            "student_id": student_id,
            "diagnostic": diagnostic.to_dict() if diagnostic is not None else None,
            "report": report,
            "pomdp_state_names": list(teacher_helpers._POMDP_STATE_NAMES),
        }
    except Exception:
        _log.warning(
            "teacher: /api/teacher/students/%s/diagnostic 失败",
            student_id,
            exc_info=True,
        )
        return JSONResponse({"error": "POMDP 诊断获取失败"}, status_code=500)


@router.get("/students/{student_id}/interventions")
def api_teacher_student_interventions(student_id: str):
    """干预历史: LCA 每次 select_intervention 的决策记录."""
    try:
        return {
            "student_id": student_id,
            "interventions": teacher_helpers._get_intervention_history(student_id),
        }
    except Exception:
        _log.warning(
            "teacher: /api/teacher/students/%s/interventions 失败",
            student_id,
            exc_info=True,
        )
        return JSONResponse({"error": "干预历史获取失败"}, status_code=500)


@router.get(
    "/students/{student_id}/calibration", response_model=CalibrationResponse
)
def api_teacher_student_calibration(student_id: str):
    """自评校准视图 (v0.97.2): 自报 vs 实绩互校 (读时派生, 无状态)."""
    try:
        row = teacher_helpers._load_student_row(student_id)
        if row is None:
            return JSONResponse({"error": "学生不存在"}, status_code=404)

        history = teacher_helpers._json_field(row, "response_history")
        if not isinstance(history, list):
            history = []

        from cogedu.cta.calibration_view import calibration_view

        view = calibration_view([h for h in history if isinstance(h, dict)])
        return {
            "student_id": student_id,
            "has_data": view.has_data,
            "n_total": view.n_total,
            "n_self_assessed": view.n_self_assessed,
            "n_skipped": view.n_skipped,
            "curves": [
                {
                    "bucket": c.bucket,
                    "n": c.n,
                    "correct": c.correct,
                    "predicted": round(c.predicted, 4),
                    "actual_rate": round(c.actual_rate, 4),
                    "correction_factor": round(c.correction_factor, 4),
                }
                for c in view.curves
            ],
        }
    except Exception:
        _log.warning(
            "teacher: /api/teacher/students/%s/calibration 失败",
            student_id,
            exc_info=True,
        )
        return JSONResponse({"error": "校准视图获取失败"}, status_code=500)


@router.get(
    "/students/{student_id}/misconceptions",
    response_model=MisconceptionsResponse,
)
def api_teacher_student_misconceptions(student_id: str):
    """per-misconception 证据视图 (v0.97.3): A2 reconcile 校准后的检测可信度.

    A2 闭环前仅展示给教师看, 不进 BeliefState (v0.97.2 拍板纪律,
    详见 docs/cogedu-整合技术方案.md 12.3 的 A2 tripwire)。
    """
    try:
        row = teacher_helpers._load_student_row(student_id)
        if row is None:
            return JSONResponse({"error": "学生不存在"}, status_code=404)

        # in-function import (保持 Flask 版 patch 面: 测试 monkeypatch
        # misconception_reconcile.load_tracker_for_student)
        from cogedu.cta.misconception_reconcile import (
            MisconceptionEvidenceTracker,
            load_tracker_for_student,
        )
        from cogedu.cta.content import PythonBasicsMisconceptionLibrary

        tracker = load_tracker_for_student(teacher_helpers._get_db(), student_id)
        lib = PythonBasicsMisconceptionLibrary()
        items = []
        for ev_row in tracker.all_evidence():
            entry = lib.get(ev_row.misc_id)
            items.append({
                "misc_id": ev_row.misc_id,
                "name": entry.name if entry else ev_row.misc_id,
                "description": entry.description if entry else "",
                "correction_strategy": entry.correction_strategy if entry else "",
                "success_count": ev_row.success_count,
                "failure_count": ev_row.failure_count,
                "total": ev_row.total,
                "laplace_confidence": round(ev_row.laplace_confidence(), 4),
                "quarantined": tracker.quarantined(ev_row.misc_id),
                "last_updated": ev_row.last_updated,
            })

        return {
            "student_id": student_id,
            "has_data": len(items) > 0,
            "items": items,
        }
    except Exception:
        _log.warning(
            "teacher: /api/teacher/students/%s/misconceptions 失败",
            student_id,
            exc_info=True,
        )
        return JSONResponse(
            {"error": "per-misconception 证据视图获取失败"}, status_code=500
        )
