"""12.4 (0-C): FastAPI 应用骨架测试 — 基础端点 + SSE 流式 + PluginRuntime 激活.

覆盖:
  - /api/version 返回 cogedu.__version__ (Flask 版遗留 import ecos bug 的回归防线)
  - /api/students/recent 空库返回空列表 (不 500)
  - SSE /api/events/stream: 订阅 → 收事件 → max_events 收满自动结束 + 不泄漏订阅
  - lifespan: with TestClient 启动 → PluginRuntime 激活 (12.4-2 plugin_runtime
    在 FastAPI 装配下的接入验证; /api/answer 全链路验证随 12.4-5 补)
"""
from __future__ import annotations

import threading

from fastapi.testclient import TestClient


def _client() -> TestClient:
    from web.api.app import app

    return TestClient(app)


# ─── 基础端点 ────────────────────────────────────────────────────────────────


class TestBasicEndpoints:
    def test_version_returns_cogedu_version(self):
        """版本号来自 cogedu 包 (Flask 版 import ecos bug 的回归防线)."""
        resp = _client().get("/api/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] != "unknown"
        assert data["version"]  # 非空

    def test_recent_students_empty_db(self, isolated_ecos_db):
        """有 schema 无数据 → 200 + 空列表.

        注: 无 schema 的全新 DB 会 no such table → 500, 这是 Flask 版
        就有的行为 (生产 DB 始终有 schema), 迁移保持一致不"顺手修"。
        """
        from cogedu.persistence.db import Database

        Database(isolated_ecos_db).init_schema()
        resp = _client().get("/api/students/recent")
        assert resp.status_code == 200
        assert resp.json() == {"students": []}

    def test_openapi_available(self):
        """FastAPI 自带 /docs + /openapi.json (Pydantic 契约可查)."""
        resp = _client().get("/openapi.json")
        assert resp.status_code == 200
        assert "/api/version" in resp.json()["paths"]


# ─── SSE 流式 (12.4 第 3 项: 框架层流式能力打通) ─────────────────────────────


class TestSSEStream:
    def test_stream_receives_bus_event(self):
        """订阅 hint_requested → publish 一条事件 → SSE 收到 → max_events=1 结束."""
        from cogedu.cta.event_log import LearningEvent
        from cogedu.event import get_default_bus

        bus = get_default_bus()
        event = LearningEvent.from_hint_requested(
            student_id="sse-test-1", problem_id="PB-Q01", hint_level=1
        )

        # 流打开后由后台线程 publish (TestClient 同步流读取会阻塞当前线程)
        timer = threading.Timer(
            0.2, lambda: bus.publish("hint_requested", event)
        )
        timer.start()

        client = _client()
        with client.stream(
            "GET",
            "/api/events/stream",
            params={"topics": "hint_requested", "max_events": 1},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            received = []
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    received.append(line[len("data: "):])
                    break  # max_events=1, 收到即结束

        assert len(received) == 1
        import json

        payload = json.loads(received[0])
        assert payload["event_id"] == event.event_id
        assert payload["student_id"] == "sse-test-1"
        assert payload["event_type"] == "hint_requested"
        timer.join()

    def test_stream_unsubscribes_on_finish(self):
        """流结束 (max_events 收满) 后自动 unsubscribe, 不泄漏订阅."""
        from cogedu.cta.event_log import LearningEvent
        from cogedu.event import get_default_bus

        bus = get_default_bus()
        before = len(bus.get_subscribers("goal_changed"))

        event = LearningEvent.from_goal_changed(
            student_id="sse-test-2", old_goal_id="g1", new_goal_id="g2"
        )
        timer = threading.Timer(0.2, lambda: bus.publish("goal_changed", event))
        timer.start()

        client = _client()
        with client.stream(
            "GET",
            "/api/events/stream",
            params={"topics": "goal_changed", "max_events": 1},
        ) as resp:
            for _ in resp.iter_lines():
                pass  # 消费完整流

        timer.join()
        after = len(bus.get_subscribers("goal_changed"))
        assert after == before  # 订阅已清理

    def test_stream_idle_timeout_terminates(self):
        """无事件时 idle_timeout_seconds 到点结束流 (不永挂)."""
        import time

        client = _client()
        started = time.monotonic()
        with client.stream(
            "GET",
            "/api/events/stream",
            params={
                "topics": "reflection_completed",
                "idle_timeout_seconds": 0.3,
            },
        ) as resp:
            body = b"".join(resp.iter_bytes())
        elapsed = time.monotonic() - started
        assert elapsed < 5.0  # 0.3s 超时 + 轮询余量, 不应挂到 5s
        assert b"event:" not in body  # 没收到任何事件, 直接超时关闭


# ─── PluginRuntime 激活 (12.4-2) ────────────────────────────────────────────


class TestPluginRuntimeAnswerChain:
    """12.4-2 收尾: lifespan 激活 PluginRuntime 后, /api/answer 全链路
    走事件总线 (publish response_submitted → PluginRuntime subscriber →
    Runtime.update_belief → engine.update), 状态真实更新。

    这条链路是 CLAUDE.md 架构红线 1 的主路径 (状态只经 Runtime 变更),
    FastAPI 迁移 (12.4-5) 后在此锁定。
    """

    def test_answer_updates_state_via_plugin_path(self, monkeypatch):
        import os

        from fastapi.testclient import TestClient

        from web.api.app import app
        from web.api.plugin_runtime import (
            get_plugin_runtime,
            reset_plugin_runtime,
        )

        # 无 LLM 惯例 (belief 的 misconception/perception critic 会调 LLM)
        import web.api.llm as llm_mod

        monkeypatch.setattr(llm_mod, "get_llm", lambda: None)

        # 隔离 DB + schema + 学生行 (conftest autouse 已设 ECOS_DB_PATH)
        from cogedu.persistence.db import Database

        db = Database(os.environ["ECOS_DB_PATH"])
        db.init_schema()
        db.upsert_student("stu-plugin-chain")

        reset_plugin_runtime()
        try:
            with TestClient(app) as client:
                assert get_plugin_runtime().is_started
                resp = client.post("/api/answer", json={
                    "student_id": "stu-plugin-chain",
                    "problem_id": "PB-Q01",
                    "skill_id": "python.variables",
                    "correct": True,
                    "score": 1.0,
                    "bloom_layer": "L1",
                    "user_answer": "5",
                })
                assert resp.status_code == 200
                body = resp.json()
                # 9 字段契约 (Plugin 路径下同样成立)
                assert set(body.keys()) == {
                    "correct", "score", "theta", "misc_triggered",
                    "misc_id", "misc_confidence", "c_discount_factor",
                    "persisted", "reasoning",
                }
                assert body["persisted"] is True

                # 状态真实更新 = subscriber 确实跑了 Runtime.update_belief
                # (Plugin 路径返回的 state 对象由 subscriber 原地 mutate;
                #  若 subscriber 没跑, history 不会有这条答题记录)
                from web.api.belief import _STUDENT_STATES

                engine = _STUDENT_STATES["stu-plugin-chain"]["engine"]
                history = engine._response_history.get(
                    "stu-plugin-chain", []
                )
                assert any(
                    h.get("problem_id") == "PB-Q01" for h in history
                ), "Plugin 路径下 response_history 未更新 — subscriber 未跑"
        finally:
            reset_plugin_runtime()


class TestPluginRuntimeLifespan:
    def test_lifespan_starts_plugin_runtime(self):
        """with TestClient (触发 lifespan) → PluginRuntime 激活 + bus 有 subscriber."""
        from web.api.app import app
        from web.api.plugin_runtime import (
            get_plugin_runtime,
            reset_plugin_runtime,
        )

        # 干净起点 (上一测试可能已激活)
        reset_plugin_runtime()
        try:
            with TestClient(app) as client:
                resp = client.get("/api/version")
                assert resp.status_code == 200
                runtime = get_plugin_runtime()
                assert runtime.is_started  # property, 不是方法
                assert runtime.subscription_count >= 8  # 8 个核心 subscriber
        finally:
            # 还原现场, 不影响后续测试 (belief.py 等走 legacy fallback)
            reset_plugin_runtime()

    def test_no_lifespan_keeps_legacy_path(self):
        """裸 TestClient (不进 with) → 不触发 lifespan → PluginRuntime 未启动
        (legacy fallback 路径, 对齐 Flask test_client 行为)."""
        from web.api.plugin_runtime import (
            get_plugin_runtime,
            reset_plugin_runtime,
        )

        reset_plugin_runtime()
        try:
            client = _client()
            client.get("/api/version")
            assert not get_plugin_runtime().is_started
        finally:
            reset_plugin_runtime()
