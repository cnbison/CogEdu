"""Phase 1 1-B-4: POST /api/presentation/outline HTTP 契约测试.

patch 面约定 (对齐 12.4):
  - web.api.routers.presentation.plan — Runtime plan 调用
  - web.api.llm.get_llm — LLM 注入 (1-A-5: 单一 patch 面)

覆盖: 200 契约 (Outline 字段) / LLM 解析失败 502 / 结构不合规 502 /
plan 缺 intervention 500。
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


class FakeLLM:
    def __init__(self, output: Any = None, error: Exception | None = None):
        self.output = output
        self.error = error

    def chat_json(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        if self.error is not None:
            raise self.error
        return self.output


_GOOD = {
    "title": "二次函数入门",
    "steps": [
        {"title": "第一步", "key_points": ["kp1"]},
        {"title": "第二步", "key_points": ["kp2"]},
    ],
}


class _FakeIntervention:
    intervention_id = "int_http1"
    intervention_type = "explanatory"
    target_skills = ["二次函数"]
    target_misconceptions: list[str] = []
    target_tcs: list[str] = []
    difficulty = 0.5
    scaffolding_level = 0.5
    clt_level = 2
    ca_stage = "coaching"
    bloom_target = "APPLY"
    rationale = "r"


class _FakeLcaResult:
    student_id = "stu_http"
    intervention = _FakeIntervention()
    rationale = "r"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "web.api.routers.presentation.plan",
        lambda student_id, **kw: _FakeLcaResult(),
    )
    from web.api.app import app

    return TestClient(app)


class TestOutlineEndpoint:
    def test_outline_200_contract(self, client, monkeypatch):
        monkeypatch.setattr("web.api.llm.get_llm", lambda: FakeLLM(_GOOD))
        resp = client.post(
            "/api/presentation/outline",
            json={"student_id": "stu_http", "goal_id": "g1", "evidence_id": "e1"},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Outline 契约字段 (response_model=Outline 在框架层锁定)
        assert data["outline_id"]
        assert data["student_id"] == "stu_http"
        assert data["intervention_id"] == "int_http1"
        assert data["goal_id"] == "g1"
        assert data["evidence_id"] == "e1"
        assert data["title"] == "二次函数入门"
        assert len(data["steps"]) == 2
        assert data["steps"][0]["step_id"].startswith(data["outline_id"])
        assert data["created_at"]

    def test_llm_parse_error_502(self, client, monkeypatch):
        """LLM JSON 解析失败 → 502 + error (不静默吞)."""
        monkeypatch.setattr(
            "web.api.llm.get_llm",
            lambda: FakeLLM(error=ValueError("LLM 输出无法解析为 JSON")),
        )
        resp = client.post("/api/presentation/outline", json={"student_id": "stu_http"})
        assert resp.status_code == 502
        assert "大纲生成失败" in resp.json()["error"]

    def test_bad_structure_502(self, client, monkeypatch):
        """LLM 输出结构不合规 (steps 空) → 502."""
        monkeypatch.setattr(
            "web.api.llm.get_llm", lambda: FakeLLM({"title": "t", "steps": []})
        )
        resp = client.post("/api/presentation/outline", json={"student_id": "stu_http"})
        assert resp.status_code == 502
        assert "steps" in resp.json()["error"]

    def test_plan_missing_intervention_500(self, client, monkeypatch):
        class _NoIntervention:
            student_id = "stu_http"
            intervention = None

        monkeypatch.setattr(
            "web.api.routers.presentation.plan",
            lambda student_id, **kw: _NoIntervention(),
        )
        monkeypatch.setattr("web.api.llm.get_llm", lambda: FakeLLM(_GOOD))
        resp = client.post("/api/presentation/outline", json={"student_id": "stu_http"})
        assert resp.status_code == 500
        assert "intervention" in resp.json()["error"]

    def test_openapi_contract_registered(self, client):
        """路由注册进 OpenAPI (静态页宽路由兜底不能抢先匹配)."""
        assert "/api/presentation/outline" in client.get("/openapi.json").json()["paths"]


# ─── /scenes (1-C) ───────────────────────────────────────────────────────────

_SCENE_LLM_OUTPUT = {
    "title": "第一步",
    "text": "讲解正文，含公式 $x^2$。",
    "image_concept": "示意图",
}


class TestScenesEndpoint:
    def test_scenes_200_contract(self, client, monkeypatch, isolated_ecos_db):
        """/outline 落库 → /scenes 恢复 context → 每步一个 Scene."""
        monkeypatch.setattr("web.api.llm.get_llm", lambda: FakeLLM(_GOOD))
        resp = client.post("/api/presentation/outline", json={"student_id": "stu_http"})
        assert resp.status_code == 200
        outline_id = resp.json()["outline_id"]

        monkeypatch.setattr(
            "web.api.llm.get_llm",
            lambda: FakeLLM(dict(_SCENE_LLM_OUTPUT)),  # output 不消耗, 每步同款
        )
        resp = client.post("/api/presentation/scenes", json={"outline_id": outline_id})
        assert resp.status_code == 200
        scenes = resp.json()
        assert len(scenes) == 2  # 场景数 = 大纲步数
        for scene in scenes:
            assert scene["outline_id"] == outline_id
            assert scene["intervention_id"] == "int_http1"
            assert [b["type"] for b in scene["blocks"]] == ["text", "image"]
            assert scene["degraded"] is False

    def test_scenes_unknown_outline_404(self, client, monkeypatch, isolated_ecos_db):
        monkeypatch.setattr("web.api.llm.get_llm", lambda: FakeLLM(_GOOD))
        resp = client.post(
            "/api/presentation/scenes", json={"outline_id": "no_such"}
        )
        assert resp.status_code == 404
        assert "不存在" in resp.json()["error"]

    def test_scenes_llm_failure_502(self, client, monkeypatch, isolated_ecos_db):
        monkeypatch.setattr("web.api.llm.get_llm", lambda: FakeLLM(_GOOD))
        outline_id = client.post(
            "/api/presentation/outline", json={"student_id": "stu_http"}
        ).json()["outline_id"]
        monkeypatch.setattr(
            "web.api.llm.get_llm",
            lambda: FakeLLM(error=ValueError("LLM 输出无法解析为 JSON")),
        )
        resp = client.post("/api/presentation/scenes", json={"outline_id": outline_id})
        assert resp.status_code == 502
        assert "场景生成失败" in resp.json()["error"]

    def test_outline_persisted_and_replayable(self, client, monkeypatch, isolated_ecos_db):
        """/outline 落库 (含 context) — 落库失败 warning 不中断呈现的反向锚点."""
        from web.api.presentation_service import get_store

        monkeypatch.setattr("web.api.llm.get_llm", lambda: FakeLLM(_GOOD))
        data = client.post(
            "/api/presentation/outline",
            json={"student_id": "stu_http", "evidence_id": "ev_1"},
        ).json()
        stored = get_store().get_outline(data["outline_id"])
        assert stored is not None
        assert stored.context is not None  # 第二阶段恢复 pedagogy 字段的物理前提
        assert stored.evidence_id == "ev_1"
