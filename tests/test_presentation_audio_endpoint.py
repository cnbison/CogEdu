"""3-D: GET /api/presentation/audio/{audio_id} HTTP 契约 + /scenes 归属校验.

覆盖:
  - 200 音频字节 + media type (mp3→audio/mpeg)
  - 404 音频缺失 / 孤儿音频 (所属场景缺失)
  - 403 学生访问他人音频 (real_auth: 学生 B ≠ scene.student_id)
  - 200 学生本人 (real_auth: 学生 A = scene.student_id)
  - /scenes 3-F-5: 学生请求他人 outline → 403 (real_auth)
auth_bypass (admin 放行) 下跑 200/404 契约; 归属/越权语义走 real_auth。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cogedu.persistence.presentation_store import AudioRecord
from cogedu.presentation.types import Outline, OutlineStep, Scene, TextBlock
from web.api import presentation_service as svc
from web.api.app import app


@pytest.fixture()
def client() -> TestClient:
    svc.reset_store()
    return TestClient(app)


def _seed_scene(student_id: str) -> Scene:
    """经 store 直接造 outline + scene (鉴权语义由 real_auth 测试覆盖)."""
    store = svc.get_store()
    outline = Outline(student_id=student_id, intervention_id="int_x",
                      title="求根公式", steps=[OutlineStep(title="第一步")])
    store.save_outline(outline)
    scene = Scene(
        outline_id=outline.outline_id,
        step_id=outline.steps[0].step_id,
        student_id=student_id,
        intervention_id="int_x",
        title="第一步",
        blocks=[TextBlock(content="x")],
        actions=[{"type": "speech", "text": "我们来看求根公式"}],
    )
    store.save_scene(scene)
    return scene


def _seed_audio(scene: Scene, audio_id: str = "tts_s1_a1") -> None:
    svc.get_store().save_audio(AudioRecord(
        audio_id=audio_id, scene_id=scene.scene_id, action_id="a1",
        audio=b"\xff\xfb\x90\x00" + b"\x00" * 256,
        duration_ms=1234, format="mp3",
        created_at="2026-09-13T00:00:00+00:00",
    ))


class TestAudioContract:
    def test_200_audio_bytes(self, client: TestClient):
        scene = _seed_scene("stu_a")
        _seed_audio(scene)
        resp = client.get("/api/presentation/audio/tts_s1_a1")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("audio/mpeg")
        assert resp.content.startswith(b"\xff\xfb")

    def test_404_missing_audio(self, client: TestClient):
        resp = client.get("/api/presentation/audio/no_such")
        assert resp.status_code == 404

    def test_404_orphan_audio(self, client: TestClient):
        """音频在、所属场景不在 → 404 (不按可播处理)."""
        _seed_scene("stu_a")
        store = svc.get_store()
        store.save_audio(AudioRecord(
            audio_id="tts_orphan", scene_id="ghost_scene", action_id="a1",
            audio=b"\x00" * 16, duration_ms=None, format="mp3",
            created_at="2026-09-13T00:00:00+00:00",
        ))
        resp = client.get("/api/presentation/audio/tts_orphan")
        assert resp.status_code == 404


@pytest.mark.real_auth
class TestAudioOwnership:
    def test_student_own_audio_200(self, client: TestClient, auth_factory):
        scene = _seed_scene("stu_owner")
        _seed_audio(scene, "tts_own")
        headers, _ = auth_factory(username="stu_owner_u", role="student",
                                  learning_student_id="stu_owner")
        resp = client.get("/api/presentation/audio/tts_own?student_id=stu_owner",
                          headers=headers)
        assert resp.status_code == 200

    def test_other_student_403(self, client: TestClient, auth_factory):
        """学生 B 访问学生 A 的音频 → 403 (按 audio→scene 归属权威校验)."""
        scene = _seed_scene("stu_owner")
        _seed_audio(scene, "tts_private")
        headers, _ = auth_factory(username="stu_other_u", role="student",
                                  learning_student_id="stu_other")
        resp = client.get(
            "/api/presentation/audio/tts_private?student_id=stu_other",
            headers=headers,
        )
        assert resp.status_code == 403

    def test_student_without_query_param_403(self, client: TestClient, auth_factory):
        """router 级 dependency 拿不到 target 时学生角色不放行."""
        scene = _seed_scene("stu_owner")
        _seed_audio(scene, "tts_own2")
        headers, _ = auth_factory(username="stu_owner_u2", role="student",
                                  learning_student_id="stu_owner")
        resp = client.get("/api/presentation/audio/tts_own2", headers=headers)
        assert resp.status_code == 403


@pytest.mark.real_auth
class TestScenesOwnership:
    def test_scenes_other_students_outline_403(self, client: TestClient, auth_factory):
        """3-F-5: 学生请求他人 outline 的场景生成 → 403."""
        outline = Outline(student_id="stu_owner", intervention_id="int_x",
                          title="t", steps=[OutlineStep(title="a")])
        svc.get_store().save_outline(outline)
        headers, _ = auth_factory(username="stu_other_u2", role="student",
                                  learning_student_id="stu_other")
        resp = client.post("/api/presentation/scenes", headers=headers, json={
            "student_id": "stu_other", "outline_id": outline.outline_id,
        })
        assert resp.status_code == 403

    def test_scenes_wrong_identity_header_403(self, client: TestClient, auth_factory):
        """调用者身份 (router 级) 与 body student_id 不一致 → 403."""
        outline = Outline(student_id="stu_owner", intervention_id="int_x",
                          title="t", steps=[OutlineStep(title="a")])
        svc.get_store().save_outline(outline)
        headers, _ = auth_factory(username="stu_owner_u3", role="student",
                                  learning_student_id="stu_owner")
        resp = client.post("/api/presentation/scenes", headers=headers, json={
            "student_id": "stu_other", "outline_id": outline.outline_id,
        })
        assert resp.status_code == 403


class TestReplayEndpoints:
    """只读复看端点 (2026-09-14): 生成耗时数分钟且计费, 复看走只读路径."""

    def test_get_outline_200(self, client: TestClient):
        scene = _seed_scene("stu_a")
        resp = client.get(f"/api/presentation/outline/{scene.outline_id}")
        assert resp.status_code == 200
        assert resp.json()["outline_id"] == scene.outline_id
        assert resp.json()["schema_version"] == 1

    def test_get_scenes_readonly_200(self, client: TestClient):
        """GET /scenes/{id} 只读——不触发生成, 只返回已落库场景."""
        scene = _seed_scene("stu_a")
        resp = client.get(f"/api/presentation/scenes/{scene.outline_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["scene_id"] == scene.scene_id
        assert body[0]["schema_version"] == 2   # 带 actions 的场景

    def test_get_scenes_empty_outline_200_empty_list(self, client: TestClient):
        from cogedu.presentation.types import Outline

        outline = Outline(student_id="stu_a", intervention_id="i", title="t",
                          steps=[])
        svc.get_store().save_outline(outline)
        resp = client.get(f"/api/presentation/scenes/{outline.outline_id}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_missing_404(self, client: TestClient):
        assert client.get("/api/presentation/outline/no_such").status_code == 404
        assert client.get("/api/presentation/scenes/no_such").status_code == 404

    @pytest.mark.real_auth
    def test_other_student_replay_403(self, client: TestClient, auth_factory):
        """复看他人大纲/场景 → 403 (归属权威校验)."""
        scene = _seed_scene("stu_owner")
        headers, _ = auth_factory(username="stu_other_u3", role="student",
                                  learning_student_id="stu_other")
        q = "?student_id=stu_other"
        r1 = client.get(f"/api/presentation/outline/{scene.outline_id}{q}",
                        headers=headers)
        r2 = client.get(f"/api/presentation/scenes/{scene.outline_id}{q}",
                        headers=headers)
        assert r1.status_code == 403
        assert r2.status_code == 403
