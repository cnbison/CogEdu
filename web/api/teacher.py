"""v0.95.1: 教师端 API — 班级列表 + 学生详情 (证据链 / POMDP 诊断 / 干预历史).

Teacher Dashboard 数据源 (全部只读, 不 mutate Kernel state, 防御性自检 [8] 0 mutation):
  - students 表: 班级名单 + last_active + bloom + confidence (DB 直读, 不 init BeliefEngine)
  - response_history: 答题证据链 (按 Q 矩阵 a_specialized 分配到 5D 维度)
  - misconception_history / tc_states: misconception + TC 证据
  - TeacherProgressPlugin: 教学建议 / 冷启动判断 (v0.95.1 UI 可消费)
  - Runtime.diagnose_pomdp: POMDP T/R 后验诊断 (lazy load LCA state)
  - LCAStore: 干预历史 (intervention_history)

对应 discussions/2026-08-17-v095方向审查 §决策 1 + §结论 4 (UI 是 Evidence 呈现面):
  - 班级视图优先: 教师先扫全班 (冷启动/状态 flag), 再单生深潜
  - 证据链按 5D 维度聚合 + 可下钻: "系统为什么这么判断"
  - Bisen 拍板 2026-08-17: 班级视图优先 + 单生深潜; 证据链按 5D 维度聚合可下钻

路由: 12.4 (0-C) 起由 web/api/routers/teacher.py 提供 (FastAPI),
  本文件只保留框架无关 helpers (DB 直读解析 + progress report),
  Flask Blueprint 路由层已随迁移删除。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

# v0.95.1: 5D 维度元数据 (教师端展示用)
DIMENSION_LABELS: Dict[str, Dict[str, str]] = {
    "K": {"label": "知识", "full": "Knowledge", "desc": "概念与事实性知识"},
    "P": {"label": "程序", "full": "Procedural", "desc": "步骤与流程执行"},
    "S": {"label": "策略", "full": "Strategic", "desc": "解题策略与规划"},
    "C": {"label": "置信", "full": "Confidence", "desc": "自我评估与把握度"},
    "X": {"label": "支架", "full": "Scaffolding", "desc": "外部支持依赖度"},
}

# POMDP 状态名 (跟 TeacherProgressPlugin / LCAEngine 一致)
_POMDP_STATE_NAMES = ("Engaged", "Frustrated", "Bored", "Confused")

# 维度加载阈值: a_specialized[dim] >= 0.2 才算该响应为该维度的证据
_DIM_LOADING_THRESHOLD = 0.2


# ─── DB 直读 helpers (不 init BeliefEngine) ───────────────────────────────────


def _get_db() -> Any:
    # ECOS_DB_PATH 可配置 (跟 web/api/lca.py 一致, 测试用 temp DB)
    import os
    from cogedu.persistence.db import Database
    db_path = os.environ.get("ECOS_DB_PATH", "web/ecos.db")
    return Database(db_path)


def _load_student_row(student_id: str) -> Optional[Dict[str, Any]]:
    """读 students 表单行 (DB 直读, 不 init engine).

    Returns:
        dict(row) 或 None (学生不存在).
    """
    try:
        return _get_db().load_student_state(student_id)
    except Exception:
        _log.warning(
            "teacher: load_student_row 失败 (sid=%s)", student_id, exc_info=True
        )
        return None


def _json_field(row: Dict[str, Any], key: str) -> Any:
    """安全解析 JSON 列 (失败返回 None + warning, 不 silent pass)."""
    raw = row.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        _log.warning(
            "teacher: 解析 JSON 列 %s 失败 (sid=%s), 返回 None",
            key, row.get("student_id"), exc_info=True,
        )
        return None


def _parse_responses(student_id: str) -> List[Dict[str, Any]]:
    """解析 response_history (DB 直读, 含每题的 a_specialized 维度加载).

    Returns:
        list of {problem_id, correct, score, bloom_level, timestamp,
                 user_answer, correct_answer, ai_reasoning, dims (5D bool)}
    """
    row = _load_student_row(student_id)
    if row is None:
        return []
    history = _json_field(row, "response_history")
    if not isinstance(history, list):
        return []

    from web.api.qmatrix import get_question_detail

    responses: List[Dict[str, Any]] = []
    for h in history:
        if isinstance(h, dict):
            pid = h.get("problem_id")
        else:
            # 老 3-tuple 兜底
            pid = h[0] if len(h) > 0 else None
        if not pid:
            continue

        # 维度加载向量 (从 Q 矩阵, 失败默认全 False)
        dims: List[bool] = [False] * 5
        prob = None
        try:
            prob = get_question_detail(pid)
        except Exception:
            _log.warning(
                "teacher: get_question_detail 失败 (pid=%s), 证据维度 fallback",
                pid, exc_info=True,
            )
        if prob and "a_specialized" in prob:
            try:
                a = prob["a_specialized"]
                dims = [bool(v >= _DIM_LOADING_THRESHOLD) for v in a]
            except Exception:
                _log.warning(
                    "teacher: a_specialized 解析失败 (pid=%s)", pid, exc_info=True
                )

        responses.append({
            "problem_id": pid,
            "correct": bool(h.get("correct")) if isinstance(h, dict) else bool(h[1]) if len(h) > 1 else False,
            "score": float(h.get("score", 1.0 if h.get("correct") else 0.0)) if isinstance(h, dict) else 1.0,
            "bloom_level": str(h.get("bloom_level")) if isinstance(h, dict) else str(h[2]),
            "timestamp": h.get("timestamp") if isinstance(h, dict) else None,
            "user_answer": h.get("user_answer") if isinstance(h, dict) else None,
            "correct_answer": h.get("correct_answer") if isinstance(h, dict) else None,
            "ai_reasoning": h.get("ai_reasoning") if isinstance(h, dict) else None,
            "dims": dims,
        })
    return responses


def _parse_misconceptions(student_id: str) -> List[Dict[str, Any]]:
    """解析 misconception_history (DB 直读)."""
    row = _load_student_row(student_id)
    if row is None:
        return []
    data = _json_field(row, "misconception_history")
    if not isinstance(data, list):
        return []
    return [
        {
            "misc_id": str(m.get("misc_id", "")),
            "confidence": float(m.get("confidence", 0.0)),
            "timestamp": m.get("timestamp"),
        }
        for m in data
        if isinstance(m, dict)
    ]


def _parse_tc_states(student_id: str) -> List[Dict[str, Any]]:
    """解析 TC states (DB 直读, 跨维度证据)."""
    row = _load_student_row(student_id)
    if row is None:
        return []
    data = _json_field(row, "tc_states")
    if not isinstance(data, dict):
        return []
    return [
        {
            "id": str(tc_id),
            "status": str(v.get("status", "")) if isinstance(v, dict) else "",
            "progress": float(v.get("progress", 0.0)) if isinstance(v, dict) else 0.0,
            "confidence": float(v.get("confidence", 0.0)) if isinstance(v, dict) else 0.0,
            "irreversible": bool(v.get("irreversible", False)) if isinstance(v, dict) else False,
        }
        for tc_id, v in data.items()
    ]


def _parse_bloom_summary(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """解析 current_bloom_profile → {dominant, confidence, levels}."""
    data = _json_field(row, "current_bloom_profile")
    if not isinstance(data, dict):
        return None
    return {
        "dominant": data.get("dominant_layer"),
        "confidence": float(data.get("confidence", 0.0)),
        "levels": {
            "L1": float(data.get("remember", 0.0)),
            "L2": float(data.get("understand", 0.0)),
            "L3": float(data.get("apply", 0.0)),
            "L4": float(data.get("analyze", 0.0)),
            "L5": float(data.get("evaluate", 0.0)),
            "L6": float(data.get("create", 0.0)),
        },
    }


def _parse_theta(row: Dict[str, Any]) -> Optional[Dict[str, float]]:
    """解析 current_state_5d → {K,P,S,C,X: theta}."""
    data = _json_field(row, "current_state_5d")
    if not isinstance(data, list) or len(data) != 5:
        return None
    return {dim: round(float(data[i]), 4) for i, dim in enumerate(["K", "P", "S", "C", "X"])}


# ─── TeacherProgressPlugin 接入 (v0.95.1 UI 可消费) ───────────────────────────


def _get_teacher_progress_plugin() -> Any:
    """从 PluginRegistry 拿 TeacherProgressPlugin 实例.

    Returns:
        plugin 实例或 None (registry 未注册 / 不是该 plugin).
    """
    try:
        from cogedu.plugins.registry import get_default_registry
        return get_default_registry().get("teacher_progress")
    except Exception:
        _log.warning("teacher: 拿 TeacherProgressPlugin 失败", exc_info=True)
        return None


def _get_progress_report(student_id: str) -> Optional[Dict[str, Any]]:
    """获取学生的教学建议报告 (插件缓存 → 按需诊断).

    优先级:
      1. TeacherProgressPlugin.report_for(student_id) (bus 事件已缓存)
      2. 缓存 miss → Runtime.diagnose_pomdp 按需派生 → ingest_diagnostic 喂 plugin

    Returns:
        report dict (most_likely_state / cold_start / advice / belief) 或 None
        (非 POMDP policy / 学生无 LCA 状态 / 派生失败).
    """
    plugin = _get_teacher_progress_plugin()
    if plugin is not None:
        cached = plugin.report_for(student_id)
        if cached is not None:
            return cached

    # 缓存 miss: 按需诊断 (lazy load LCA state, 跟 PluginRuntime 一致)
    try:
        from web.api.lca import _get_or_create_lca_state, get_lca_engine
        _get_or_create_lca_state(student_id)
        lca_engine = get_lca_engine()

        from cogedu.runtime.api import diagnose_pomdp
        diagnostic = diagnose_pomdp(student_id=student_id, lca_engine=lca_engine)
        if diagnostic is None:
            return None

        if plugin is not None:
            return plugin.ingest_diagnostic(student_id, diagnostic)

        # 无 plugin 时, 直接派生最小 report (不依赖 plugin)
        from cogedu.plugins.first_party.teacher_progress import (
            COLD_START_COVERAGE_THRESHOLD,
        )
        min_coverage = int(diagnostic.coverage.min())
        cold_start = min_coverage < COLD_START_COVERAGE_THRESHOLD
        most_likely_idx = diagnostic.most_likely_state
        most_likely_state = (
            _POMDP_STATE_NAMES[most_likely_idx]
            if 0 <= most_likely_idx < len(_POMDP_STATE_NAMES)
            else f"Unknown({most_likely_idx})"
        )
        return {
            "student_id": student_id,
            "most_likely_state": most_likely_state,
            "most_likely_state_index": most_likely_idx,
            "belief": diagnostic.belief.tolist(),
            "min_coverage": min_coverage,
            "cold_start": cold_start,
            "advice": (
                f"冷启动期 (min_coverage={min_coverage}), 建议保守教学"
                if cold_start
                else f"已冷启动完成 (min_coverage={min_coverage})"
            ),
            "updated_at": None,
        }
    except Exception:
        _log.warning(
            "teacher: 按需诊断失败 (sid=%s), report=None",
            student_id, exc_info=True,
        )
        return None


# ─── 干预历史 ────────────────────────────────────────────────────────────────


def _get_intervention_history(student_id: str) -> List[Dict[str, Any]]:
    """读 LCAStore 的 intervention_history (跟 lca.py 持久化同一数据源).

    Returns:
        list of Intervention.to_dict() (intervention_type / bloom_target /
        expected_gain / expected_risk / rationale / clt_level / ca_stage ...)
    """
    try:
        from web.api.lca import get_store
        store = get_store()
        if not store.has_state(student_id):
            return []
        snap = store.load_state(student_id)
        if snap is None:
            return []
        return list(snap.intervention_history)
    except Exception:
        _log.warning(
            "teacher: 读干预历史失败 (sid=%s), 返空列表",
            student_id, exc_info=True,
        )
        return []


__all__ = [
    "DIMENSION_LABELS",
]
