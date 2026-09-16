"""学生端 4 行为事件端点接通测试 (hint / idle / goal_change / reflection).

双轨终点 (2026-09-16): legacy app.js/index.html 已删除, 本文件改为锁
React 侧接线 (web/frontend/src/student/)。后端 /api/event/* 端点行为
已在 test_event_stub.py 覆盖。

Per discussions/2026-08-17 决策 2-1 (数据通道打通): 接通后 v0.91 human
feedback / v0.92 action history / v0.94 HintFatiguePlugin 的 Kernel
投资才有数据来源。
"""
from __future__ import annotations

from pathlib import Path

SRC_STUDENT = Path(__file__).resolve().parents[1] / "web" / "frontend" / "src" / "student"


def _read(rel: str) -> str:
    return (SRC_STUDENT / rel).read_text(encoding="utf-8")


class TestStudentEventWiring:
    """React 学生端 4 个行为事件的 api 方法与调用点存在."""

    def setup_method(self):
        self.api = _read("api.ts")
        self.answer = _read("pages/AnswerPage.tsx")

    def test_4_event_kinds_typed_in_api(self):
        """emitEvent 的 kind union 覆盖 4 个端点 (跟 event_stub.py 路由一致)."""
        assert 'kind: "hint" | "idle" | "goal_change" | "reflection"' in self.api
        assert "/api/event/${kind}" in self.api

    def test_hint_called_with_payload_matching_backend_contract(self):
        """hint body: {student_id, problem_id, hint_level} 跟 event_stub 契约一致."""
        assert '"hint"' in self.answer
        assert "hint_level: 1" in self.answer
        assert "problem_id: q.problem_id" in self.answer

    def test_idle_called_with_payload_matching_backend_contract(self):
        """idle body: {student_id, idle_seconds} 跟 event_stub 契约一致."""
        assert '"idle"' in self.answer
        assert "idle_seconds: IDLE_SECONDS" in self.answer

    def test_goal_change_called_with_payload_matching_backend_contract(self):
        """goal_change body: {student_id, old_goal_id, new_goal_id}."""
        assert '"goal_change"' in self.answer
        assert "old_goal_id: goalBaseline.current" in self.answer
        assert "new_goal_id: goalId" in self.answer

    def test_reflection_called_with_payload_matching_backend_contract(self):
        """reflection body: {student_id, reflection_text, problem_id optional}."""
        assert '"reflection"' in self.answer
        assert "reflection_text: reflection" in self.answer

    def test_best_effort_not_silent(self):
        """best-effort 遥测必须 console.warn, 不允许 silent pass."""
        assert "console.warn(" in self.api

    def test_idle_timer_ui_trigger_present(self):
        """idle 事件有真实触发点: 输入重置计时器 + 超时发射 (不能是死代码)."""
        assert "resetIdle" in self.answer
        assert "window.setTimeout" in self.answer
        assert "onAnswerChange" in self.answer
