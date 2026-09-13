"""3-F-3: TTS 异步补齐编排测试（同步执行体 + 单例 + 端到端集成）.

覆盖:
  - backfill_scene_audio: 合成成功 → audio 落库（时长字节嗅探）+ scene
    幂等覆盖回填 audio_id / 幂等键已存在 → 跳过合成直接回填 / 合成失败
    → audio_id 保持 None 不中断 / wb_* 动作不触碰
  - get_tts 单例: 未配置 → None（静音降级）; 配置 → MiniMax 客户端
  - 端到端: POST /scenes 返回后后台线程补齐（轮询等待）
"""
from __future__ import annotations

import json
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cogedu.presentation.tts import TTSResult
from cogedu.presentation.types import (
    Outline,
    OutlineStep,
    Scene,
    SpeechAction,
    TextBlock,
)
from tests.test_audio_duration import make_wav
from web.api import presentation_service as svc
from web.api.app import app


class FakeTTS:
    """合成假体: 返回合法 WAV（时长可嗅探），记录调用。"""

    def __init__(self, error: Exception | None = None):
        self.calls: list[tuple[str, float]] = []
        self.error = error

    def generate(self, text: str, *, voice: str | None = None, speed: float = 1.0) -> TTSResult:
        self.calls.append((text, speed))
        if self.error is not None:
            raise self.error
        return TTSResult(audio=make_wav(800), format="wav")


def _scene_with_speech(text: str = "先看求根公式") -> Scene:
    outline = Outline(student_id="stu_1", intervention_id="int_1",
                      title="t", steps=[OutlineStep(title="a")])
    return Scene(
        outline_id=outline.outline_id,
        step_id=outline.steps[0].step_id,
        student_id="stu_1",
        intervention_id="int_1",
        title="t",
        blocks=[TextBlock(content="x")],
        actions=[
            {"type": "wb_draw_text", "content": "标注", "x": 100, "y": 100},
            {"type": "speech", "text": text},
        ],
    )


class TestBackfillWorker:
    def test_success_backfills_and_persists(self, tmp_path):
        store = svc.PresentationStore(db_path=str(tmp_path / "p.db"))
        fake = FakeTTS()
        try:
            scenes = [_scene_with_speech()]
            store.save_scene(scenes[0])
            svc.backfill_scene_audio(scenes, store, fake)

            scene = scenes[0]
            speech = scene.actions[1]
            assert speech.audio_id == f"tts_{scene.scene_id}_{speech.action_id}"
            record = store.get_audio(speech.audio_id)
            assert record is not None
            assert record.format == "wav"
            assert record.duration_ms == 800   # 字节嗅探 (3-D-2)
            assert fake.calls == [("先看求根公式", 1.0)]
            # scene 已幂等覆盖落库 (audio_id 回填进 payload)
            stored = store.get_scene(scene.scene_id)
            assert stored is not None
            assert stored.actions[1].audio_id == speech.audio_id
        finally:
            store.close()

    def test_existing_audio_skips_synthesis(self, tmp_path):
        """幂等键已存在 → 不再合成, 直接回填 (force 重生成 = 删行)."""
        store = svc.PresentationStore(db_path=str(tmp_path / "p.db"))
        fake = FakeTTS()
        try:
            scenes = [_scene_with_speech()]
            store.save_scene(scenes[0])
            speech = scenes[0].actions[1]
            audio_id = f"tts_{scenes[0].scene_id}_{speech.action_id}"
            from cogedu.persistence.presentation_store import AudioRecord

            store.save_audio(AudioRecord(
                audio_id=audio_id, scene_id=scenes[0].scene_id,
                action_id=speech.action_id, audio=b"old",
                duration_ms=1, format="mp3", created_at="2026-09-13T00:00:00+00:00",
            ))
            svc.backfill_scene_audio(scenes, store, fake)
            assert fake.calls == []                       # 未合成
            assert scenes[0].actions[1].audio_id == audio_id
            assert store.get_audio(audio_id).audio == b"old"  # 未覆盖
        finally:
            store.close()

    def test_synthesis_failure_degrades(self, tmp_path):
        """合成失败 → audio_id 保持 None + audio 不落库, 不中断不抛."""
        store = svc.PresentationStore(db_path=str(tmp_path / "p.db"))
        fake = FakeTTS(error=RuntimeError("minimax 502"))
        try:
            scenes = [_scene_with_speech()]
            store.save_scene(scenes[0])
            svc.backfill_scene_audio(scenes, store, fake)   # 不抛
            assert scenes[0].actions[1].audio_id is None
        finally:
            store.close()

    def test_wb_actions_untouched(self, tmp_path):
        store = svc.PresentationStore(db_path=str(tmp_path / "p.db"))
        fake = FakeTTS()
        try:
            scenes = [_scene_with_speech()]
            store.save_scene(scenes[0])
            svc.backfill_scene_audio(scenes, store, fake)
            assert scenes[0].actions[0].type == "wb_draw_text"
            assert not hasattr(scenes[0].actions[0], "audio_id") or \
                scenes[0].actions[0].audio_id is None
        finally:
            store.close()


class TestGetTts:
    def setup_method(self):
        svc.reset_tts()

    def teardown_method(self):
        svc.reset_tts()

    def test_unconfigured_returns_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("COGEDU_TTS_API_KEY", raising=False)
        assert svc.get_tts() is None

    def test_configured_returns_client(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("COGEDU_TTS_API_KEY", "k-test")
        client = svc.get_tts()
        assert client is not None
        assert svc.get_tts() is client   # 单例


# ─── 端到端: POST /scenes 返回后后台线程补齐 ────────────────────────────────

class _FakeIntervention:
    intervention_id = "int_tts"
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
    student_id = "stu_tts"
    intervention = _FakeIntervention()
    rationale = "r"


class FakeLLM:
    def __init__(self, outputs: list[Any]):
        self.outputs = list(outputs)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        return json.dumps(self.outputs.pop(0), ensure_ascii=False)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    svc.reset_store()
    svc.reset_tts()
    return TestClient(app)


@pytest.fixture()
def fake_tts(monkeypatch: pytest.MonkeyPatch) -> FakeTTS:
    fake = FakeTTS()
    monkeypatch.setattr(svc, "get_tts", lambda: fake)
    return fake


def _poll(fn, timeout: float = 3.0):
    """轮询等待后台线程落库 (daemon 线程, 请求已返回)."""
    deadline = time.monotonic() + timeout
    result = None
    while time.monotonic() < deadline:
        result = fn()
        if result is not None:
            return result
        time.sleep(0.05)
    return None


@pytest.mark.usefixtures("isolated_ecos_db")
class TestScenesBackfillIntegration:
    def test_scenes_response_then_audio_backfilled(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_tts: FakeTTS,
    ):
        monkeypatch.setattr("web.api.routers.presentation.plan", lambda *a, **k: _FakeLcaResult())
        outline_out = {"title": "二次函数", "steps": [{"title": "第一步", "key_points": ["kp"]}]}

        scene_out = {
            "title": "第一步", "text": "讲解正文",
            "image_concept": "图",
            "actions": [
                {"type": "speech", "text": "先看求根公式"},
                {"type": "wb_draw_line", "x1": 0, "y1": 500, "x2": 1000, "y2": 500},
            ],
        }
        # 共享单个 FakeLLM 实例 (get_llm 每次调用必须返回同一对象,
        # 否则每次都拿到满配输出列表 → 消费错位)
        llm = FakeLLM([outline_out, dict(scene_out), dict(scene_out)])
        monkeypatch.setattr("web.api.llm.get_llm", lambda: llm)
        resp = client.post("/api/presentation/outline", json={"student_id": "stu_tts"})
        assert resp.status_code == 200
        outline_id = resp.json()["outline_id"]
        resp = client.post("/api/presentation/scenes", json={
            "student_id": "stu_tts", "outline_id": outline_id,
        })
        assert resp.status_code == 200
        scenes = resp.json()
        assert scenes[0]["schema_version"] == 2
        speech_action = next(a for a in scenes[0]["actions"] if a["type"] == "speech")

        # 后台线程补齐: audio 落库 + scene payload 回填
        audio_id = f"tts_{scenes[0]['scene_id']}_{speech_action['action_id']}"
        record = _poll(lambda: svc.get_store().get_audio(audio_id))
        assert record is not None
        assert record.duration_ms == 800

        def _stored_speech_audio_id() -> str | None:
            stored = svc.get_store().get_scene(scenes[0]["scene_id"])
            if stored is None or not stored.actions:
                return None
            a = next((x for x in stored.actions if x.type == "speech"), None)
            return a.audio_id if a else None

        assert _poll(_stored_speech_audio_id) == audio_id
