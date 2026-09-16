"""Phase 1 1-F: 场景行为回写闭环测试 (13.7).

覆盖:
  - LearningEvent.from_scene_behavior factory (viewed / completed / 非法类型)
  - HumanFeedbackEntry.from_event 接受 scene 事件 (内核白名单 additive 扩展)
  - PluginRuntime subscriber 注册 (scene_viewed / scene_completed)
  - 全链路: HTTP POST /api/presentation/event → bus → subscriber →
    LCAEngine.append_human_feedback (twin 计数断言) + event_log 落库

语义决策 (vs 13.7 字面 "update_belief"): 行为事件走 v0.91.0-b 确立的
human feedback 通道 — 伪造作答 Observation 会污染 CTA 推断。
见 docs/presentation-runtime-map.md §6。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cogedu.cta.belief_engine import BeliefEngine
from cogedu.cta.cognitive_twin import HumanFeedbackEntry
from cogedu.cta.event_log import LearningEvent
from cogedu.event import get_default_bus, reset_default_bus
from cogedu.lca.orchestrator import LCAEngine, LCAEngineConfig
from web.api.plugin_runtime import PluginRuntime, reset_plugin_runtime


# ─── Factory ────────────────────────────────────────────────────────────────


class TestSceneBehaviorFactory:
    def test_scene_viewed_payload(self):
        event = LearningEvent.from_scene_behavior(
            event_type="scene_viewed",
            student_id="stu_001",
            payload={
                "outline_id": "o1",
                "scene_id": "s1",
                "step_id": "o1_step1",
                "dwell_sec": 12.5,
                "index": 0,
            },
        )
        assert event.event_type == "scene_viewed"
        assert event.payload["dwell_sec"] == 12.5
        assert event.source == "frontend_scene"

    def test_scene_completed_payload(self):
        event = LearningEvent.from_scene_behavior(
            event_type="scene_completed",
            student_id="stu_001",
            payload={"outline_id": "o1", "scene_count": 4, "total_dwell_sec": 96.0},
        )
        assert event.event_type == "scene_completed"
        assert event.payload["scene_count"] == 4

    def test_invalid_type_rejected(self):
        with pytest.raises(ValueError, match="scene_viewed / scene_completed"):
            LearningEvent.from_scene_behavior(
                event_type="response_submitted",  # 不允许借道伪造作答事件
                student_id="stu_001",
                payload={},
            )

    def test_non_dict_payload_rejected(self):
        with pytest.raises(ValueError, match="payload"):
            LearningEvent.from_scene_behavior(
                event_type="scene_viewed", student_id="s", payload="oops",
            )


class TestHumanFeedbackAcceptance:
    def test_from_event_accepts_scene_types(self):
        """内核 HUMAN_FEEDBACK_EVENT_TYPES 白名单已扩展 (additive)."""
        for et in ("scene_viewed", "scene_completed"):
            event = LearningEvent.from_scene_behavior(
                event_type=et, student_id="s", payload={"outline_id": "o1"},
            )
            entry = HumanFeedbackEntry.from_event(event)
            assert entry.event_type == et


# ─── PluginRuntime subscriber ───────────────────────────────────────────────


class TestSubscriberRegistration:
    def test_scene_topics_have_subscribers(self):
        reset_default_bus()
        reset_plugin_runtime()
        bus = get_default_bus()
        runtime = PluginRuntime(
            bus=bus,
            state_factory=lambda sid: (None, None),
            lca_engine_factory=lambda: None,
        )
        runtime.start()
        assert bus.get_topic_count("scene_viewed") == 1
        assert bus.get_topic_count("scene_completed") == 1
        runtime.stop()


# ─── HTTP 全链路 (1-F-2 + 1-F-3 + 1-F-4) ────────────────────────────────────


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ECOS_DB_PATH", "/tmp/cogedu_scene_event_test.db")
    from web.api.app import app

    return TestClient(app)


class TestSceneEventEndpoint:
    def test_scene_viewed_full_chain(self, client, isolated_ecos_db):
        """埋点 → bus → subscriber → twin 计数 + event_log 落库."""
        reset_default_bus()
        reset_plugin_runtime()

        # 真实 LCAEngine + state (subscriber 内部调 append_human_feedback)
        lca = LCAEngine(config=LCAEngineConfig(use_llm_rationale=False))
        state = BeliefEngine().create_initial_state("stu_scene")

        bus = get_default_bus()
        runtime = PluginRuntime(
            bus=bus,
            state_factory=lambda sid: (BeliefEngine(), state),
            lca_engine_factory=lambda: lca,
        )
        runtime.start()

        resp = client.post(
            "/api/presentation/event",
            json={
                "student_id": "stu_scene",
                "outline_id": "o_chain",
                "event_type": "scene_viewed",
                "scene_id": "sc_1",
                "step_id": "o_chain_step1",
                "dwell_sec": 8.3,
                "index": 0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "logged"
        assert data["event_id"]

        # 内核侧消费断言: twin 已记 human_feedback
        assert "stu_scene" in lca._cognitive_twin
        twin = lca._cognitive_twin["stu_scene"]
        assert twin.human_feedback.count_by_type("scene_viewed") == 1

        # event_log 落库断言 (1-F-3)
        from web.api.belief import _get_web_event_log

        events = _get_web_event_log().load_events("stu_scene")
        assert any(e.event_type == "scene_viewed" for e in events)
        runtime.stop()

    def test_scene_completed_chain(self, client, isolated_ecos_db):
        reset_default_bus()
        reset_plugin_runtime()
        lca = LCAEngine(config=LCAEngineConfig(use_llm_rationale=False))
        state = BeliefEngine().create_initial_state("stu_done")
        runtime = PluginRuntime(
            bus=get_default_bus(),
            state_factory=lambda sid: (BeliefEngine(), state),
            lca_engine_factory=lambda: lca,
        )
        runtime.start()
        resp = client.post(
            "/api/presentation/event",
            json={
                "student_id": "stu_done",
                "outline_id": "o_done",
                "event_type": "scene_completed",
                "scene_count": 3,
                "total_dwell_sec": 71.2,
            },
        )
        assert resp.status_code == 200
        assert lca._cognitive_twin["stu_done"].human_feedback.count_by_type(
            "scene_completed"
        ) == 1
        runtime.stop()

    def test_invalid_event_type_400(self, client, isolated_ecos_db):
        resp = client.post(
            "/api/presentation/event",
            json={
                "student_id": "s",
                "outline_id": "o",
                "event_type": "scene_question",  # 未注册类型, 拒绝
            },
        )
        assert resp.status_code == 400
        assert "scene_viewed" in resp.json()["error"]

    def test_endpoint_registered_in_openapi(self, client):
        assert "/api/presentation/event" in client.get("/openapi.json").json()["paths"]

