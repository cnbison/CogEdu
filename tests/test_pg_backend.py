"""12.5 (0-D): PostgreSQL 后端集成测试 — 双后端奇偶 / 事务 / 并发 / 连接池.

覆盖 (方案文档 12.5 第 4 项):
  - 双后端 CRUD 奇偶校验: 同一操作序列在 SQLite 与 PostgreSQL 上结果一致
    (parametrize, SQLite 分支即使无 PG 服务器也跑 — 守护适配层不破坏原路径)
  - 事务边界: rollback / commit / 事务内异常不落库
  - 并发: 多线程同时写 (PG 共享连接 tx 串行语义, 对齐 SQLite 单写者)
  - 连接池: psycopg_pool + 本仓库 schema/tx 模式的并发验证

PG 用例在无 PG 服务器时 skip (环境变量 COGEDU_TEST_PG_ADMIN_DSN 可覆盖
admin DSN, 默认本机 postgres:///postgres)。
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest

from cogedu.persistence.adapter import BACKEND_POSTGRES, BACKEND_SQLITE
from cogedu.persistence.db import Database, DatabaseConfig

# 默认 admin DSN: 本机 Homebrew PostgreSQL (12.5 安装); CI 无 PG 时 skip
PG_ADMIN_DSN = os.environ.get("COGEDU_TEST_PG_ADMIN_DSN", "postgres:///postgres")

SQLITE_DSN = "postgres:///__never__"  # 占位, sqlite 分支不用


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
    """每模块一个独立 PG 测试库 (创建 → 测试 → 删除), 无 PG 时 skip 整组."""
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


@pytest.fixture
def pg_db(pg_dsn):
    db = Database(DatabaseConfig(dsn=pg_dsn))
    db.init_schema()
    yield db
    db.close()


@pytest.fixture
def sqlite_db(tmp_path):
    db = Database(DatabaseConfig(db_path=str(tmp_path / "parity.db")))
    db.init_schema()
    yield db
    db.close()


# ─── 双后端奇偶校验 (同一操作序列, 断言一致) ─────────────────────────────────


def _run_crud_sequence(db: Database) -> dict:
    """跨后端统一的 CRUD 操作序列, 返回全部读结果供比对."""
    out: dict = {}

    # 学生 upsert ×2 (幂等) + 状态写入
    db.upsert_student("stu-p", subject="python")
    db.upsert_student("stu-p", subject="python")
    out["student_row"] = db.load_student_state("stu-p")
    out["student_ids"] = db.load_student_ids(limit=10)

    # judge audit (RETURNING id)
    id1 = db.save_judge_audit("stu-p", "PB-Q01", "minimax", "m1", 1, 10.0, True)
    id2 = db.save_judge_audit("stu-p", "PB-Q02", "moonshot", "m2", 3, 20.0, False,
                              "LLM_JUDGE_FAILED", "raw output")
    out["audit_ids_ordered"] = id1 < id2
    out["audit_count"] = len(db.conn.execute(
        "SELECT id FROM judge_audit_log WHERE student_id = :s", dict(s="stu-p")
    ).fetchall())

    # calibration (RETURNING id) + actual_outcome 回写
    cid = db.save_calibration("stu-p", {"calibration_round": 1, "message_payload": {"k": "v"}})
    assert cid > 0
    db.update_calibration_actual_outcome("stu-p", 1, 0.8)
    hist = db.load_calibration_history("stu-p")
    import json as _json

    out["cal_payload"] = _json.loads(hist[0]["message_payload"])

    # event 去重 (ON CONFLICT DO NOTHING)
    db.save_event("evt-1", "stu-p", "2026-09-12T00:00:00", "t", "observation", '{"a": 1}')
    db.save_event("evt-1", "stu-p", "2026-09-12T00:00:00", "t", "observation", '{"a": 1}')
    out["event_count"] = db.count_events("stu-p")
    out["event_history_len"] = len(db.load_event_history("stu-p"))

    # misconception upsert + 计数覆盖
    db.save_misconception_evidence("stu-p", [
        {"misc_id": "M1", "success_count": 1, "failure_count": 0, "last_updated": "t1"},
    ])
    db.save_misconception_evidence("stu-p", [
        {"misc_id": "M1", "success_count": 3, "failure_count": 2, "last_updated": "t2"},
    ])
    out["misc"] = db.load_misconception_evidence("stu-p")

    # trajectory snapshot (bytes / BYTEA)
    db.save_trajectory_snapshot("stu-p", "session_end", 3,
                                state_snapshot=b"\x00\x01bin", grade_level=5)
    snaps = db.load_trajectory_snapshots("stu-p")
    out["snapshot_bytes"] = bytes(snaps[0]["state_snapshot"])
    out["snapshot_id_int"] = isinstance(snaps[0]["snapshot_id"], int)

    # bloom goal upsert
    db.save_bloom_goal("g1", {"subject": "math", "skill_id": "s1", "bloom_layer": 2,
                              "description": "d1", "cognitive_objectives": ["c1"]})
    db.save_bloom_goal("g1", {"subject": "math", "skill_id": "s1", "bloom_layer": 2,
                              "description": "d2", "assessment_criteria": ["a1"]})
    goals = db.load_bloom_goals("math")
    out["goal_desc"] = goals[0]["description"]

    # intervention
    db.save_intervention("iv-1", "stu-p", {
        "intervention_type": "EXPLANATORY", "bloom_target": "APPLY",
        "target_skills": ["s1"], "expected_gain": 0.3,
    })
    ivs = db.load_intervention_history("stu-p")
    out["iv_count"] = len(ivs)

    return out


class TestDualBackendParity:
    """同一 CRUD 序列在两种后端上结果一致 (12.5 适配层正确性核心防线)."""

    def test_sqlite_sequence(self, sqlite_db):
        out = _run_crud_sequence(sqlite_db)
        assert out["student_row"] is not None
        assert out["event_count"] == 1

    def test_parity_with_pg(self, sqlite_db, pg_db):
        sqlite_out = _run_crud_sequence(sqlite_db)
        pg_out = _run_crud_sequence(pg_db)
        assert set(sqlite_out.keys()) == set(pg_out.keys())
        # 易变字段 (写入口的 datetime.now()) 不参与奇偶比对
        VOLATILE = {"created_at", "last_active_at"}
        for key in sqlite_out:
            a, b = sqlite_out[key], pg_out[key]
            if key == "student_row" and a and b:
                a = {k: v for k, v in a.items() if k not in VOLATILE}
                b = {k: v for k, v in b.items() if k not in VOLATILE}
            assert a == b, f"奇偶破坏: {key}"


# ─── 事务边界 ────────────────────────────────────────────────────────────────


class TestTransactionBoundary:
    def test_pg_rollback_on_exception(self, pg_db):
        pg_db.upsert_student("stu-tx")
        with pytest.raises(RuntimeError):
            with pg_db.tx():
                pg_db.conn.execute(
                    "INSERT INTO judge_audit_log (student_id, created_at) VALUES (:s, :t)",
                    dict(s="stu-tx", t="rollback-marker"),
                )
                raise RuntimeError("rollback me")
        row = pg_db.conn.execute(
            "SELECT COUNT(*) AS cnt FROM judge_audit_log WHERE created_at = 'rollback-marker'"
        ).fetchone()
        assert row["cnt"] == 0

    def test_pg_commit_on_success(self, pg_db):
        pg_db.upsert_student("stu-tx2")
        with pg_db.tx():
            pg_db.conn.execute(
                "INSERT INTO judge_audit_log (student_id, created_at) VALUES (:s, :t)",
                dict(s="stu-tx2", t="commit-marker"),
            )
        row = pg_db.conn.execute(
            "SELECT COUNT(*) AS cnt FROM judge_audit_log WHERE created_at = 'commit-marker'"
        ).fetchone()
        assert row["cnt"] == 1

    def test_sqlite_rollback_unchanged(self, sqlite_db):
        """SQLite 原有事务语义零改动 (适配层不回归既有行为)."""
        sqlite_db.upsert_student("stu-tx3")
        with pytest.raises(RuntimeError):
            with sqlite_db.tx():
                sqlite_db.conn.execute(
                    "INSERT INTO judge_audit_log (student_id, created_at) VALUES (:s, :t)",
                    dict(s="stu-tx3", t="rollback-marker"),
                )
                raise RuntimeError("rollback me")
        row = sqlite_db.conn.execute(
            "SELECT COUNT(*) AS cnt FROM judge_audit_log WHERE created_at = 'rollback-marker'"
        ).fetchone()
        assert row["cnt"] == 0


# ─── 并发 (12.5 第 4 项: PG 引入的并发行为) ──────────────────────────────────


class TestConcurrency:
    def test_pg_concurrent_event_writes(self, pg_db):
        """多线程并发写 event_log: 共享连接 tx 串行语义下不丢不重."""
        import threading

        pg_db.upsert_student("stu-conc")

        def worker(i: int):
            pg_db.save_event(
                f"evt-conc-{i}", "stu-conc", "2026-09-12T00:00:00",
                "t", "observation", '{"n": %d}' % i,
            )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert pg_db.count_events("stu-conc") == 20

    def test_pg_concurrent_mixed_read_write(self, pg_db):
        """读 (autocommit) 与写 (tx) 并发: 读不阻塞、不读半提交数据."""
        import threading

        pg_db.upsert_student("stu-mix")
        errors: list[Exception] = []

        def writer():
            try:
                for i in range(10):
                    pg_db.save_event(
                        f"evt-mix-{i}", "stu-mix", "2026-09-12T00:00:00",
                        "t", "observation", "{}",
                    )
            except Exception as e:  # pragma: no cover
                errors.append(e)

        def reader():
            try:
                for _ in range(30):
                    pg_db.load_event_history("stu-mix")
            except Exception as e:  # pragma: no cover
                errors.append(e)

        wt = threading.Thread(target=writer)
        rts = [threading.Thread(target=reader) for _ in range(3)]
        wt.start()
        for t in rts:
            t.start()
        wt.join()
        for t in rts:
            t.join()
        assert not errors, errors
        assert pg_db.count_events("stu-mix") == 10


# ─── 连接池 (12.5 第 4 项) ───────────────────────────────────────────────────


class TestConnectionPool:
    def test_pool_concurrent_writes(self, pg_dsn):
        """psycopg_pool + 本仓库 schema/tx 模式: 多连接并发写不丢数据."""
        pool = pytest.importorskip("psycopg_pool").ConnectionPool(
            pg_dsn, min_size=1, max_size=4, open=True,
            kwargs={"autocommit": True, "row_factory": None},
        )
        try:
            from cogedu.persistence.adapter import translate_sql

            def worker(i: int):
                with pool.connection() as conn:
                    conn.execute(
                        translate_sql(
                            "INSERT INTO judge_audit_log (student_id, created_at) "
                            "VALUES (:s, :t)", BACKEND_POSTGRES,
                        ),
                        dict(s="stu-pool", t=f"pool-{i}"),
                    )

            # 需要先有 students 行 (FK) — 用主 Database 建
            db = Database(DatabaseConfig(dsn=pg_dsn))
            db.init_schema()
            db.upsert_student("stu-pool")
            db.close()

            import threading

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            db = Database(DatabaseConfig(dsn=pg_dsn))
            row = db.conn.execute(
                "SELECT COUNT(*) AS cnt FROM judge_audit_log WHERE student_id = :s",
                dict(s="stu-pool"),
            ).fetchone()
            assert row["cnt"] == 16
            db.close()
        finally:
            pool.close()


# ─── EventLog / stores 双后端 (12.5-3 接入面) ────────────────────────────────


class TestEventLogAndStoresPG:
    def test_event_log_pg_roundtrip_and_dedup(self, pg_db, pg_dsn):
        from cogedu.cta.event_log import EventLog, LearningEvent

        pg_db.upsert_student("stu-ev")
        log = EventLog.from_sqlite(pg_dsn)
        try:
            ev = LearningEvent.from_hint_requested("stu-ev", "PB-Q01", 1)
            log.log_event(ev)
            log.log_event(ev)  # event_id 去重
            assert log.count_events("stu-ev") == 1
            got = log.load_events("stu-ev")
            assert got[0].event_id == ev.event_id
            assert got[0].payload["problem_id"] == "PB-Q01"
        finally:
            log._conn.close()

    def test_dual_agent_and_lca_store_pg(self, pg_db, pg_dsn):
        from cogedu.persistence.dual_agent_store import DualAgentStore
        from cogedu.persistence.lca_store import LCAStore

        pg_db.upsert_student("stu-stores")

        da = DualAgentStore(db_path=pg_dsn)
        try:
            da.save_state("stu-stores", state_snapshot={"theta": [1, 2]},
                          intervention_history=[{"a": 1}], state_trajectory=[{"t": 1}],
                          calibration_round=2, warnings=["w"], belief_challenges=[],
                          strategy_challenges=[], consecutive_ineffective=0)
            snap = da.load_state("stu-stores")
            assert snap.state_snapshot == {"theta": [1, 2]}
            assert snap.calibration_round == 2
            assert da.has_state("stu-stores") and not da.has_state("ghost")
        finally:
            da.close()

        ls = LCAStore(db_path=pg_dsn)
        try:
            ls.save_state("stu-stores", intervention_history=[],
                          bandit_a=[[[0.1] * 2]], bandit_b=[[0.1] * 2],
                          arm_pull_counts=[1, 0], last_intervention=None,
                          update_count=3, select_count=5)
            l = ls.load_state("stu-stores")
            assert l.update_count == 3 and l.arm_pull_counts == [1, 0]
        finally:
            ls.close()

    def test_evidence_engine_pg_write(self, pg_db):
        """evidence_engine 直写 SQL 经 db.conn 代理在 PG 上走通 (RETURNING)."""
        from cogedu.evidence.evidence_engine import EvidenceEngine
        from cogedu.evidence.evidence import Evidence, EvidenceSource

        pg_db.upsert_student("stu-ev-eng")
        engine = EvidenceEngine(db=pg_db)
        ev_id = engine.add(Evidence(
            source=EvidenceSource.RESPONSE_HISTORY,
            student_id="stu-ev-eng",
            timestamp=datetime.now(),
            payload={"skill_id": "python.variables", "correct": True, "score": 1.0},
            confidence=0.9,
            problem_id="PB-Q01",
        ))
        assert ev_id > 0
        rows = pg_db.load_evidence("stu-ev-eng")
        assert len(rows) == 1
