"""1-C-3 (Phase 1, 13.4): 呈现引擎持久化 — Outline/Scene 双后端存储.

契约见 docs/presentation-runtime-map.md §4（1-A-4 定义，本文件是实现）：
  - 表 presentation_outlines / presentation_scenes, payload 全文 JSON,
    追溯列 (student_id/intervention_id/goal_id/evidence_id) 只做索引不解析
  - 索引含 idx_scenes_evidence (错因→场景反查, 第 11 章可视化入口)
  - 失败语义: 写失败返回 False + warning 留痕 (不静默吞, 不抛断呈现);
    读失败返回 None/[] + warning

架构: 跟 LCAStore / DualAgentStore 同模式 — 独立表 + 独立连接 +
adapter.open_connection 双后端 (SQLite 原路径 / PG 经 DSN), schema
幂等 executescript。
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Any

from cogedu.presentation.types import Outline, Scene

from .adapter import (
    BACKEND_POSTGRES,
    detect_backend,
    open_connection,
)

_log = logging.getLogger(__name__)


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
"""


class PresentationStore:
    """Outline/Scene 持久化 (双后端, 契约见 presentation-runtime-map.md §4)."""

    def __init__(self, db_path: str = "web/ecos.db"):
        # db_path 可以是 SQLite 文件路径或 PG DSN (adapter 统一识别)
        self.db_path = db_path
        self.backend = detect_backend(db_path)
        self._conn: Any = None
        self._pg_tx_lock = threading.RLock()  # PG: 共享连接事务串行
        self._init_schema()

    @property
    def conn(self) -> Any:
        if self._conn is None:
            _backend, self._conn = open_connection(self.db_path)
        return self._conn

    @contextmanager
    def _tx(self):
        """事务上下文 (双后端, 语义同 LCAStore._tx)."""
        if self.backend == BACKEND_POSTGRES:
            with self._pg_tx_lock:
                conn = self.conn
                with conn.transaction():
                    yield conn
            return
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def _init_schema(self) -> None:
        try:
            with self._tx():
                self.conn.executescript(PRESENTATION_SCHEMA_SQL)
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


def _payload(row: Any) -> str:
    """行 → payload 字符串 (SQLite dict 行 / PG dict 行统一取列)."""
    if isinstance(row, dict):
        return row["payload"]
    return row[0]
