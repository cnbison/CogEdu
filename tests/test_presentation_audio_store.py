"""3-D-4: presentation_audio 双后端存储测试 (SQLite 恒跑 / PG 无服务器 skip).

对齐 test_presentation_store.py 的双后端奇偶模式:
  - save/get round-trip (含 duration_ms None 与有值两种形态)
  - audio_id 幂等覆盖
  - get_scene 反查 (音频归属校验的数据源)
  - 缺失 → None
"""
from __future__ import annotations

import os
import uuid

import pytest

from cogedu.persistence.adapter import BACKEND_POSTGRES, BACKEND_SQLITE
from cogedu.persistence.presentation_store import AudioRecord, PresentationStore
from cogedu.presentation.types import Outline, OutlineStep, Scene, TextBlock

PG_ADMIN_DSN = os.environ.get("COGEDU_TEST_PG_ADMIN_DSN", "postgres:///postgres")


def _pg_available() -> bool:
    try:
        import psycopg

        conn = psycopg.connect(PG_ADMIN_DSN, autocommit=True)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def pg_dsn():
    if not _pg_available():
        pytest.skip("PostgreSQL 服务器不可用 (12.5 PG 集成测试)")
    import psycopg

    dbname = f"cogedu_test_{uuid.uuid4().hex[:8]}"
    admin = psycopg.connect(PG_ADMIN_DSN, autocommit=True)
    admin.execute(f"CREATE DATABASE {dbname}")
    admin.close()
    yield f"postgres:///{dbname}"
    admin = psycopg.connect(PG_ADMIN_DSN, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {dbname}")
    admin.close()


@pytest.fixture(params=[BACKEND_SQLITE, BACKEND_POSTGRES], ids=["sqlite", "pg"])
def store(request, tmp_path, pg_dsn) -> PresentationStore:
    if request.param == BACKEND_POSTGRES:
        s = PresentationStore(db_path=pg_dsn)
    else:
        s = PresentationStore(db_path=str(tmp_path / "audio.db"))
    yield s
    s.close()


def _scene(student_id: str = "stu_1") -> Scene:
    outline = Outline(student_id=student_id, intervention_id="int_x",
                      title="t", steps=[OutlineStep(title="a")])
    return Scene(
        outline_id=outline.outline_id,
        step_id=outline.steps[0].step_id,
        student_id=student_id,
        intervention_id="int_x",
        title="t",
        blocks=[TextBlock(content="x")],
    )


def _record(audio_id: str = "tts_s1_a1", duration_ms: int | None = 1234,
            scene_id: str = "s1", audio: bytes = b"\x00\x01\x02\xff" * 64) -> AudioRecord:
    return AudioRecord(
        audio_id=audio_id, scene_id=scene_id, action_id="a1",
        audio=audio,
        duration_ms=duration_ms, format="mp3",
        created_at="2026-09-13T00:00:00+00:00",
    )


class TestAudioStore:
    def test_save_and_get(self, store: PresentationStore):
        assert store.save_audio(_record()) is True
        got = store.get_audio("tts_s1_a1")
        assert got is not None
        assert got.scene_id == "s1"
        assert got.audio == _record().audio
        assert got.duration_ms == 1234
        assert got.format == "mp3"

    def test_duration_none_survives_roundtrip(self, store: PresentationStore):
        """嗅探失败 → duration_ms=None 落 NULL, 不猜数 (3-D-2)."""
        assert store.save_audio(_record(duration_ms=None)) is True
        got = store.get_audio("tts_s1_a1")
        assert got is not None
        assert got.duration_ms is None

    def test_idempotent_overwrite(self, store: PresentationStore):
        store.save_audio(_record(duration_ms=100))
        store.save_audio(_record(duration_ms=200, audio=b"new-bytes"))
        got = store.get_audio("tts_s1_a1")
        assert got is not None
        assert got.duration_ms == 200
        assert got.audio == b"new-bytes"

    def test_get_missing(self, store: PresentationStore):
        assert store.get_audio("no_such") is None

    def test_get_scene_for_ownership(self, store: PresentationStore):
        """音频归属校验的数据链: audio.scene_id → scene.student_id (3-D)."""
        scene = _scene(student_id="stu_owner")
        store.save_scene(scene)
        got = store.get_scene(scene.scene_id)
        assert got is not None
        assert got.student_id == "stu_owner"

    def test_get_scene_missing(self, store: PresentationStore):
        assert store.get_scene("no_such_scene") is None
