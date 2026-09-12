"""Phase 1 1-G-2: 呈现引擎端到端自动化回归 (13.8).

链路 (13.8: 答错 → CTA → LCA → 大纲 → 场景 → 行为回写 → belief 再更新):
  1. POST /api/answer 答错 → CTA 更新 belief (persisted)
  2. POST /api/presentation/outline (带 evidence_id) → Runtime plan → 大纲
  3. POST /api/presentation/scenes → 每步一个场景 (追溯字段完整)
  4. POST /api/presentation/event scene_viewed/scene_completed → 内核消费
  5. 再答题 → belief 再次更新 (theta 演化)
  6. 错因 → 场景反查 (list_scenes_by_evidence) 有数据

LLM mock (确定性): 脚本化 chat 输出序列 (第 1 次 = 大纲, 后续 = 场景)。
真实 LLM 的内容质量验证见 scripts/canary_phase1_presentation.py (1-G-1)。
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

_OUTLINE = {
    "title": "二次函数图像针对性讲解",
    "steps": [
        {"title": "先弄懂开口方向", "key_points": ["$a$ 的符号决定开口"], "objective": "纠正误概念"},
        {"title": "再看平移", "key_points": ["$c$ 是上下平移"], "objective": "补齐概念"},
    ],
}

_SCENE = {
    "title": "讲解",
    "text": "我们先看 $y=ax^2$……$$y = ax^2 + c$$ 其中 $a$ 决定开口方向。",
    "image_concept": "抛物线示意图",
}


class ScriptedLLM:
    """第 1 次调用返回大纲, 之后每次返回场景 (确定性脚本)."""

    def __init__(self):
        self.calls = 0

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls += 1
        return json.dumps(_OUTLINE if self.calls == 1 else _SCENE, ensure_ascii=False)

    def chat_json(self, messages: list[dict[str, str]], **kwargs: Any) -> Any:
        """/api/answer 链路里的 judge/critic 组件走 chat_json — 共用同一脚本."""
        return json.loads(self.chat(messages))


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("web.api.llm.get_llm", lambda: ScriptedLLM())
    from web.api.app import app

    # with 进 lifespan: ensure_started() 激活 PluginRuntime (1-F 消费走真路径)
    with TestClient(app) as c:
        yield c


def _answer(client: TestClient, sid: str, correct: bool) -> dict:
    resp = client.post("/api/answer", json={
        "student_id": sid,
        "problem_id": "MATH-Q01",
        "skill_id": "math.quadratic",
        "correct": correct,
        "score": 1.0 if correct else 0.0,
        "bloom_layer": "L3",
        "user_answer": "B" if correct else "A",
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestPresentationEndToEnd:
    def test_full_loop_answer_generate_writeback_reanswer(self, client, isolated_ecos_db):
        sid = "stu-e2e-1"

        # 1. 答错 → CTA 更新 (首答为 warmup 不更新 belief, 第 2 次起演化)
        _answer(client, sid, correct=False)
        r1 = _answer(client, sid, correct=False)
        assert r1["persisted"] is True
        assert r1["theta"]["K"] < 0.0  # 答错 → 知识维度下移

        # 2. 大纲 (带 evidence_id 追溯)
        resp = client.post("/api/presentation/outline", json={
            "student_id": sid, "evidence_id": "ev-e2e-1",
        })
        assert resp.status_code == 200, resp.text
        outline = resp.json()
        assert outline["evidence_id"] == "ev-e2e-1"
        assert len(outline["steps"]) == 2

        # 3. 场景 (追溯字段 + degraded=false)
        resp = client.post("/api/presentation/scenes", json={
            "outline_id": outline["outline_id"],
        })
        assert resp.status_code == 200, resp.text
        scenes = resp.json()
        assert len(scenes) == len(outline["steps"])
        for scene in scenes:
            assert scene["outline_id"] == outline["outline_id"]
            assert scene["evidence_id"] == "ev-e2e-1"
            assert scene["degraded"] is False

        # 4. 行为回写 → 内核 human feedback 消费 (PluginRuntime 已由 lifespan 激活)
        for scene in scenes:
            resp = client.post("/api/presentation/event", json={
                "student_id": sid,
                "outline_id": outline["outline_id"],
                "event_type": "scene_viewed",
                "scene_id": scene["scene_id"],
                "step_id": scene["step_id"],
                "dwell_sec": 15.0,
                "index": 0,
            })
            assert resp.status_code == 200, resp.text
        resp = client.post("/api/presentation/event", json={
            "student_id": sid,
            "outline_id": outline["outline_id"],
            "event_type": "scene_completed",
            "scene_count": len(scenes),
            "total_dwell_sec": 30.0,
        })
        assert resp.status_code == 200, resp.text

        # 5. 再答题 → belief 再次更新 (theta 演化; theta 是 5 维 K/P/S/C/X)
        r2 = _answer(client, sid, correct=True)
        assert r2["persisted"] is True
        # 答对后知识维度 theta 应高于答错锚点 (CTA 对作答证据的推断)
        assert r2["theta"]["K"] > r1["theta"]["K"]

        # 6. 错因 → 场景反查 (第 11 章可视化的物理前提)
        from web.api.presentation_service import get_store

        by_evidence = get_store().list_scenes_by_evidence("ev-e2e-1")
        assert len(by_evidence) == 2
        by_outline = get_store().list_scenes_by_outline(outline["outline_id"])
        assert len(by_outline) == 2
