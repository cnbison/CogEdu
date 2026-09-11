"""12.4 (0-C): dual_agent 调试端点 FastAPI 路由 — 自 Flask app.py (v0.65.0) 迁移.

web/api/dual_agent.py 本身框架无关 (12.3 评估时已确认), 无需迁移;
这里只迁 /api/dual_agent/debug 这一条路由。

dual_agent 开关 (ECOS_DUAL_AGENT_ENABLED) 两条路径的行为差异由
tests/test_fastapi_dual_agent.py 在 HTTP 层验证 (12.4 第 4 项)。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dual_agent", tags=["dual_agent"])


@router.get("/debug/{student_id}")
def api_dual_agent_debug(student_id: str):
    """双 Agent 互校调试接口 (教师后台 / 开发自检用).

    返回 dual_agent 内部 state (calibration_round / warnings / belief_challenges /
    strategy_challenges / history_count). 不暴露学生个人隐私字段。

    v0.65.0 修复注记: 路由原本漏注册 (v0.60.0 commit 漏的), FastAPI 版
    从迁移第一天就带上 (路由表检查在 tests 里锁定)。
    """
    try:
        from web.api.dual_agent import get_dual_agent_debug_info

        info = get_dual_agent_debug_info(student_id)
        return info
    except Exception as e:
        _log.warning(
            "dual_agent: /api/dual_agent/debug/%s 失败", student_id, exc_info=True
        )
        return JSONResponse({"error": str(e)}, status_code=500)
