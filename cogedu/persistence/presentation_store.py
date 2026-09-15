"""1-C-3 (Phase 1, 13.4) + 3-D-4 (Phase 3): 呈现引擎持久化 — 双后端存储.

契约见 docs/presentation-runtime-map.md §4（1-A-4 定义，本文件是实现）：
  - 表 presentation_outlines / presentation_scenes, payload 全文 JSON,
    追溯列 (student_id/intervention_id/goal_id/evidence_id) 只做索引不解析
  - 表 presentation_audio (3-D-4): speech 动作预生成音频, audio_id 幂等键
  - 索引含 idx_scenes_evidence (错因→场景反查, 第 11 章可视化入口)
  - 失败语义: 写失败返回 False + warning 留痕 (不静默吞, 不抛断呈现);
    读失败返回 None/[] + warning

架构: 跟 LCAStore / DualAgentStore 同模式 — 独立表 + 独立连接 +
adapter.open_connection 双后端 (SQLite 原路径 / PG 经 DSN), schema
幂等 executescript。
"""

from __future__ import annotations

import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from cogedu.presentation.types import Outline, Scene

from .adapter import (
    BACKEND_POSTGRES,
    detect_backend,
    open_connection,
)

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioRecord:
    """presentation_audio 行 (3-D-4). duration_ms 可空 — 字节嗅探失败
    (measure_audio_duration → None) 时落 NULL, 不猜数不报错。"""

    audio_id: str
    scene_id: str
    action_id: str
    audio: bytes
    duration_ms: int | None
    format: str
    created_at: str


# ─── Schema SQL (双后端兼容: TEXT/INTEGER + ON CONFLICT, 见 adapter 约束) ────

PRESENTATION_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS presentation_outlines (
    outline_id      TEXT PRIMARY KEY,
    student_id      TEXT NOT NULL,
    intervention_id TEXT NOT NULL,
    goal_id         TEXT,
    evidence_id     TEXT,
    payload         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_outlines_student
    ON presentation_outlines(student_id);
CREATE INDEX IF NOT EXISTS idx_outlines_intervention
    ON presentation_outlines(intervention_id);

CREATE TABLE IF NOT EXISTS presentation_scenes (
    scene_id        TEXT PRIMARY KEY,
    outline_id      TEXT NOT NULL,
    step_id         TEXT NOT NULL,
    student_id      TEXT NOT NULL,
    intervention_id TEXT NOT NULL,
    goal_id         TEXT,
    evidence_id     TEXT,
    payload         TEXT NOT NULL,
    degraded        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_scenes_student
    ON presentation_scenes(student_id);
CREATE INDEX IF NOT EXISTS idx_scenes_outline
    ON presentation_scenes(outline_id);
CREATE INDEX IF NOT EXISTS idx_scenes_intervention
    ON presentation_scenes(intervention_id);
CREATE INDEX IF NOT EXISTS idx_scenes_evidence
    ON presentation_scenes(evidence_id);
CREATE INDEX IF NOT EXISTS idx_scenes_degraded
    ON presentation_scenes(student_id, degraded);

-- Phase 3 (3-D-4): speech 动作的预生成音频。audio_id = tts_{scene_id}_{action_id}
-- 幂等键 (split 长文本拆出的子动作各有独立 audio)。BLOB 直存双后端
-- (SQLite BLOB / PG bytea, adapter 统一); 单条几百 KB 量级可接受。
CREATE TABLE IF NOT EXISTS presentation_audio (
    audio_id    TEXT PRIMARY KEY,
    scene_id    TEXT NOT NULL,
    action_id   TEXT NOT NULL,
    audio       BLOB NOT NULL,
    duration_ms INTEGER,
    format      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audio_scene
    ON presentation_audio(scene_id);
"""


def _schema_sql(backend: str) -> str:
    """按后端翻译 BLOB 列类型 (SQLite BLOB / PG BYTEA); 其余两方言通用."""
    blob_type = "BYTEA" if backend == BACKEND_POSTGRES else "BLOB"
    return PRESENTATION_SCHEMA_SQL.replace("BLOB NOT NULL", f"{blob_type} NOT NULL")


class PresentationStore:
    """Outline/Scene 持久化 (双后端, 契约见 presentation-runtime-map.md §4)."""

    def __init__(self, db_path: str = "web/ecos.db"):
        # db_path 可以是 SQLite 文件路径或 PG DSN (adapter 统一识别)
        self.db_path = db_path
        self.backend = detect_backend(db_path)
        self._conn: Any = None
        self._pg_tx_lock = threading.RLock()  # PG: 共享连接事务串行
        self._sqlite_tx_lock = threading.RLock()  # SQLite: 同上（写线程间串行）
        self._init_schema()

    @property
    def conn(self) -> Any:
        if self._conn is None:
            _backend, self._conn = open_connection(self.db_path)
        return self._conn

    @contextmanager
    def _tx(self):
        """事务上下文 (双后端, 语义同 LCAStore._tx).

        双后端都持锁串行：SQLite 分支原本无锁——回填线程与生成线程共用
        同一连接（check_same_thread=False + WAL）时交错事务会触发
        "cannot start a transaction within a transaction"（2026-09-15
        逐场景 TTS 回填引入并发后暴露）。
        """
        if self.backend == BACKEND_POSTGRES:
            with self._pg_tx_lock:
                conn = self.conn
                with conn.transaction():
                    yield conn
            return
        with self._sqlite_tx_lock:
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

    def _init_schema(self) -> None:
        try:
            with self._tx():
                self.conn.executescript(_schema_sql(self.backend))
        except Exception:
            # 防御性自检 [1]: schema init 失败必须 warning, 不能 silent pass
            _log.warning(
                "PresentationStore schema init 失败 (db=%s), 持久化不可用",
                self.db_path, exc_info=True,
            )
            raise

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                _log.warning("PresentationStore.close 失败", exc_info=True)
            finally:
                self._conn = None

    # ─── 写 ───────────────────────────────────────────────────────────────

    def save_outline(self, outline: Outline) -> bool:
        """保存 Outline (同 outline_id 幂等覆盖). 失败 False + warning."""
        try:
            with self._tx():
                self.conn.execute(
                    """
                    INSERT INTO presentation_outlines
                        (outline_id, student_id, intervention_id, goal_id,
                         evidence_id, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(outline_id) DO UPDATE SET
                        payload = excluded.payload
                    """,
                    (
                        outline.outline_id,
                        outline.student_id,
                        outline.intervention_id,
                        outline.goal_id,
                        outline.evidence_id,
                        outline.model_dump_json(),
                        outline.created_at,
                    ),
                )
            return True
        except Exception:
            _log.warning(
                "save_outline 失败 (outline=%s, db=%s)",
                outline.outline_id, self.db_path, exc_info=True,
            )
            return False

    def save_scene(self, scene: Scene) -> bool:
        """保存 Scene (同 scene_id 幂等覆盖). 失败 False + warning."""
        try:
            with self._tx():
                self.conn.execute(
                    """
                    INSERT INTO presentation_scenes
                        (scene_id, outline_id, step_id, student_id,
                         intervention_id, goal_id, evidence_id,
                         payload, degraded, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(scene_id) DO UPDATE SET
                        payload = excluded.payload,
                        degraded = excluded.degraded
                    """,
                    (
                        scene.scene_id,
                        scene.outline_id,
                        scene.step_id,
                        scene.student_id,
                        scene.intervention_id,
                        scene.goal_id,
                        scene.evidence_id,
                        scene.model_dump_json(),
                        1 if scene.degraded else 0,
                        scene.created_at,
                    ),
                )
            return True
        except Exception:
            _log.warning(
                "save_scene 失败 (scene=%s, db=%s)",
                scene.scene_id, self.db_path, exc_info=True,
            )
            return False

    # ─── 读 ───────────────────────────────────────────────────────────────

    def get_outline(self, outline_id: str) -> Outline | None:
        """按 ID 取 Outline. 失败/不存在 → None + warning."""
        try:
            row = self.conn.execute(
                "SELECT payload FROM presentation_outlines WHERE outline_id = ?",
                (outline_id,),
            ).fetchone()
            if row is None:
                return None
            return Outline.model_validate_json(_payload(row))
        except Exception:
            _log.warning(
                "get_outline 失败 (outline=%s)", outline_id, exc_info=True
            )
            return None

    def list_outline_summaries_by_student(self, student_id: str) -> list[dict[str, Any]]:
        """学生的大纲列表（讲解记录入口页数据源, UI 现代化 9-G 补）.

        返回摘要形状（不反序列化完整 payload 的 steps）:
        {outline_id, title, created_at, scene_count}，按创建时间倒序。
        失败 → [] + warning（调用方显示空列表，不阻塞入口页）。
        """
        try:
            rows = self.conn.execute(
                "SELECT o.outline_id, o.created_at, o.payload, "
                "(SELECT COUNT(*) FROM presentation_scenes s "
                " WHERE s.outline_id = o.outline_id) AS scene_count "
                "FROM presentation_outlines o WHERE o.student_id = ? "
                "ORDER BY o.created_at DESC",
                (student_id,),
            ).fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                payload = json.loads(_col(row, "payload", 2))
                out.append(
                    {
                        "outline_id": _col(row, "outline_id", 0),
                        "created_at": _col(row, "created_at", 1),
                        "title": payload.get("title") or "",
                        "scene_count": _col(row, "scene_count", 3),
                    }
                )
            return out
        except Exception:
            _log.warning(
                "list_outline_summaries_by_student 失败 (sid=%s)", student_id,
                exc_info=True,
            )
            return []

    def list_scenes_by_outline(self, outline_id: str) -> list[Scene]:
        return self._list_scenes(
            "SELECT payload FROM presentation_scenes WHERE outline_id = ? "
            "ORDER BY created_at, scene_id",
            (outline_id,),
        )

    def list_scenes_by_intervention(self, intervention_id: str) -> list[Scene]:
        return self._list_scenes(
            "SELECT payload FROM presentation_scenes WHERE intervention_id = ? "
            "ORDER BY created_at, scene_id",
            (intervention_id,),
        )

    def list_scenes_by_evidence(self, evidence_id: str) -> list[Scene]:
        """错因 → 场景反查 (第 11 章"错因诊断可视化"的物理前提)."""
        return self._list_scenes(
            "SELECT payload FROM presentation_scenes WHERE evidence_id = ? "
            "ORDER BY created_at, scene_id",
            (evidence_id,),
        )

    def _list_scenes(self, sql: str, params: tuple) -> list[Scene]:
        try:
            rows = self.conn.execute(sql, params).fetchall()
            return [Scene.model_validate_json(_payload(r)) for r in rows]
        except Exception:
            _log.warning("list_scenes 失败 (db=%s)", self.db_path, exc_info=True)
            return []

    def get_scene(self, scene_id: str) -> Scene | None:
        """按 ID 取单个 Scene (3-D 音频归属校验 / 反查用)."""
        try:
            row = self.conn.execute(
                "SELECT payload FROM presentation_scenes WHERE scene_id = ?",
                (scene_id,),
            ).fetchone()
            if row is None:
                return None
            return Scene.model_validate_json(_payload(row))
        except Exception:
            _log.warning(
                "get_scene 失败 (scene=%s)", scene_id, exc_info=True
            )
            return None

    # ─── 音频 (3-D-4): presentation_audio 读写 ────────────────────────────

    def save_audio(self, record: AudioRecord) -> bool:
        """保存音频 (audio_id 幂等键, 重复写入覆盖 — 对齐 save_scene 口径).
        失败 False + warning。"""
        try:
            with self._tx():
                self.conn.execute(
                    """
                    INSERT INTO presentation_audio
                        (audio_id, scene_id, action_id, audio,
                         duration_ms, format, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(audio_id) DO UPDATE SET
                        audio = excluded.audio,
                        duration_ms = excluded.duration_ms,
                        format = excluded.format
                    """,
                    (
                        record.audio_id,
                        record.scene_id,
                        record.action_id,
                        record.audio,
                        record.duration_ms,
                        record.format,
                        record.created_at,
                    ),
                )
            return True
        except Exception:
            _log.warning(
                "save_audio 失败 (audio=%s, db=%s)",
                record.audio_id, self.db_path, exc_info=True,
            )
            return False

    def get_audio(self, audio_id: str) -> AudioRecord | None:
        """按 ID 取音频 (含 bytes)。不存在/失败 → None + warning."""
        try:
            row = self.conn.execute(
                """
                SELECT audio_id, scene_id, action_id, audio,
                       duration_ms, format, created_at
                FROM presentation_audio WHERE audio_id = ?
                """,
                (audio_id,),
            ).fetchone()
            if row is None:
                return None
            # 行为 adapter 归一的 dict (memoryview → bytes 已在 normalize_value)
            return AudioRecord(
                audio_id=row["audio_id"],
                scene_id=row["scene_id"],
                action_id=row["action_id"],
                audio=bytes(row["audio"]),
                duration_ms=row["duration_ms"],
                format=row["format"],
                created_at=row["created_at"],
            )
        except Exception:
            _log.warning(
                "get_audio 失败 (audio=%s)", audio_id, exc_info=True
            )
            return None


def _payload(row: Any) -> str:
    """行 → payload 字符串 (SQLite dict 行 / PG dict 行统一取列)."""
    if isinstance(row, dict):
        return row["payload"]
    return row[0]


def _col(row: Any, key: str, idx: int) -> Any:
    """多列查询取列 (SQLite dict 行 / PG dict 行统一)."""
    if isinstance(row, dict):
        return row[key]
    return row[idx]
