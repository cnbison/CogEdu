"""12.4 (0-C): /api/dual_agent/debug FastAPI 路由测试 — 开关两条路径.

12.4 第 4 项要求: 迁移完成后 dual_agent 开关 (ECOS_DUAL_AGENT_ENABLED)
两条路径都要验证。本文件锁 HTTP 层行为; 函数层 (process_observation /
get_dual_agent_debug_info 的完整行为面) 由 test_dual_agent_integration.py
覆盖 (24 用例, 框架无关, 迁移零改动)。

DUAL_AGENT_ENABLED 是模块加载时读的环境变量, 测试用 monkeypatch 改
模块属性 (与 test_dual_agent_integration 同模式)。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from web.api.fastapi_app import app

    with TestClient(app) as c:
        yield c


class TestDualAgentDebugRoute:
    def test_route_registered(self):
        from web.api.fastapi_app import app

        paths = {r.path for r in app.routes}
        assert "/api/dual_agent/debug/{student_id}" in paths

    def test_flag_off_returns_disabled(self, client, monkeypatch):
        """开关关 (默认): {"enabled": False} — 现有行为完全不变 (v0.60.0 契约)."""
        import web.api.dual_agent as da

        monkeypatch.setattr(da, "DUAL_AGENT_ENABLED", False)
        resp = client.get("/api/dual_agent/debug/anyone")
        assert resp.status_code == 200
        assert resp.json() == {"enabled": False}

    def test_flag_on_new_student_no_state(self, client, monkeypatch):
        """开关开 + 学生无 dual_agent state: has_state=False + calibration_round=0."""
        import web.api.dual_agent as da

        monkeypatch.setattr(da, "DUAL_AGENT_ENABLED", True)
        resp = client.get("/api/dual_agent/debug/t_fa_da_new_001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["has_state"] is False
        assert data["calibration_round"] == 0
        assert data["warnings"] == []

    def test_flag_on_after_observation_has_state(self, client, monkeypatch):
        """开关开 + process_observation 后: has_state=True + 字段完整."""
        import web.api.dual_agent as da

        monkeypatch.setattr(da, "DUAL_AGENT_ENABLED", True)
        # 直接喂一条观测 (函数层, 同 test_dual_agent_integration 模式)
        result = da.process_observation_for_student(
            student_id="t_fa_da_dbg_001",
            problem_id="PB-Q01",
            skill_id="python.variables",
            correct=True,
            score=1.0,
            bloom_layer="L1",
        )
        assert result is not None  # 开关开 → 走 dual_agent 路径

        resp = client.get("/api/dual_agent/debug/t_fa_da_dbg_001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["has_state"] is True
        for field in (
            "calibration_round",
            "warnings",
            "belief_challenges_count",
            "strategy_challenges_count",
            "history_count",
        ):
            assert field in data, f"debug info 缺 {field}"
