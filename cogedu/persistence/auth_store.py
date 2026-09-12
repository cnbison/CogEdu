"""2-0-1 (Phase 2, 14.2): 账号体系持久化 — users/sessions 双后端存储.

CogEdu 首个账号表（此前仓库无任何身份体系，见方案文档 14.2 细化记录）：
  - users: username + bcrypt password_hash + role
    (guardian/student/teacher/admin) + disabled_at（禁用即登录/会话全失效）
    学生角色经 learning_student_id 关联 students 表学习记录（1:1；
    students 行是懒创建的，故此处不加 FK——账号可先于学习记录存在）
  - sessions: 服务端会话（token 明文不落库，只存 SHA-256 哈希），
    expires_at + revoked_at 支持过期与即时撤销——刻意不用 JWT（无状态
    token 做不到"撤销立即生效"，那是 2-A 的验收点，见方案文档 14.2 2-0-2）

失败语义对齐仓库约定（宁可明确失败信号不静默）：写失败上抛由调用方
决定（登录/建号必须显式失败），读失败返回 None + warning 留痕。

架构: 跟 LCAStore / DualAgentStore / PresentationStore 同模式 —
独立表 + 独立连接 + adapter.open_connection 双后端, schema 幂等 executescript。
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from contextlib import contextmanager
from typing import Any

from .adapter import (
    BACKEND_POSTGRES,
    detect_backend,
    open_connection,
)

_log = logging.getLogger(__name__)

# 默认 db 路径口径（ECOS_DB_PATH 环境变量）与 LCAStore 等一致
DEFAULT_DB_PATH = "web/ecos.db"

# ─── Schema SQL (双后端兼容: TEXT/INTEGER + ON CONFLICT, 见 adapter 约束) ────

AUTH_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id             TEXT PRIMARY KEY,
    username            TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,
    role                TEXT NOT NULL,
    display_name        TEXT,
    learning_student_id TEXT,
    created_at          TEXT NOT NULL,
    disabled_at         TEXT
);

CREATE INDEX IF NOT EXISTS idx_users_learning_student
    ON users(learning_student_id);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


def hash_token(token: str) -> str:
    """会话 token 摘要（落库只用哈希, 明文 token 只存在于客户端）."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthStore:
    """users/sessions 持久化 (双后端).

    SQL 全部走 adapter 翻译（占位符 ?/:name 双后端通用, 12.5 约定）。
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
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
                self.conn.executescript(AUTH_SCHEMA_SQL)
        except Exception:
            # 防御性自检 [1]: schema init 失败必须 warning, 不能 silent pass
            _log.warning(
                "AuthStore schema init 失败 (db=%s), 账号体系不可用",
                self.db_path, exc_info=True,
            )
            raise

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                _log.warning("AuthStore.close 失败", exc_info=True)
            finally:
                self._conn = None

    # ─── users ───────────────────────────────────────────────────────────────

    def create_user(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        role: str,
        display_name: str | None,
        learning_student_id: str | None,
        created_at: str,
    ) -> None:
        """创建账号. username 冲突上抛 IntegrityError 由调用方转 409."""
        with self._tx():
            self.conn.execute(
                """
                INSERT INTO users (
                    user_id, username, password_hash, role, display_name,
                    learning_student_id, created_at, disabled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                """,
                (
                    user_id,
                    username,
                    password_hash,
                    role,
                    display_name,
                    learning_student_id,
                    created_at,
                ),
            )

    def get_user_by_username(self, username: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row is not None else None

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def set_disabled(self, user_id: str, disabled_at: str | None) -> int:
        """禁用/解禁账号. disabled_at=None 表示解禁."""
        with self._tx():
            cur = self.conn.execute(
                "UPDATE users SET disabled_at = ? WHERE user_id = ?",
                (disabled_at, user_id),
            )
            return cur.rowcount or 0

    def list_users(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ─── sessions ────────────────────────────────────────────────────────────

    def create_session(
        self,
        token_hash: str,
        user_id: str,
        created_at: str,
        expires_at: str,
    ) -> None:
        with self._tx():
            self.conn.execute(
                """
                INSERT INTO sessions (token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash, user_id, created_at, expires_at),
            )

    def get_session(self, token_hash: str) -> dict[str, Any] | None:
        """取未撤销未过期的会话 (过期判断由调用方做时间比较, 这里只取行)."""
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        return dict(row) if row is not None else None

    def revoke_session(self, token_hash: str, revoked_at: str) -> int:
        """撤销单个会话 (幂等: 已撤销再撤 rowcount=0 不报错)."""
        with self._tx():
            cur = self.conn.execute(
                "UPDATE sessions SET revoked_at = ? "
                "WHERE token_hash = ? AND revoked_at IS NULL",
                (revoked_at, token_hash),
            )
            return cur.rowcount or 0

    def revoke_user_sessions(self, user_id: str, revoked_at: str) -> int:
        """撤销某用户全部活跃会话 (禁用账号/改密时调用, 撤销立即生效)."""
        with self._tx():
            cur = self.conn.execute(
                "UPDATE sessions SET revoked_at = ? "
                "WHERE user_id = ? AND revoked_at IS NULL",
                (revoked_at, user_id),
            )
            return cur.rowcount or 0

    def purge_expired_sessions(self, now_iso: str) -> int:
        """清理已过期会话行 (登录时顺带调用, 防表无限增长)."""
        with self._tx():
            cur = self.conn.execute(
                "DELETE FROM sessions WHERE expires_at < ?", (now_iso,)
            )
            return cur.rowcount or 0


# ─── Singleton accessor (同 presentation_store 口径) ─────────────────────────

_store: AuthStore | None = None


def get_auth_store(db_path: str | None = None) -> AuthStore:
    """获取 AuthStore 全局单例 (lazy init; ECOS_DB_PATH 可覆盖)."""
    global _store
    if _store is None:
        db_path = db_path or os.environ.get("ECOS_DB_PATH", DEFAULT_DB_PATH)
        _store = AuthStore(db_path)
    return _store


def reset_auth_store() -> None:
    """重置单例 (测试隔离用; 与 conftest 重置 db 单例同款)."""
    global _store
    if _store is not None and _store._conn is not None:
        _store.close()
    _store = None
