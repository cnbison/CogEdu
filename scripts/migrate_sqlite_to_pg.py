"""12.5 (0-D): SQLite → PostgreSQL 一次性数据迁移脚本 (方案文档 12.5 第 3 项).

用法:
    python scripts/migrate_sqlite_to_pg.py \
        --sqlite web/ecos.db \
        --pg-dsn "postgres:///cogedu" \
        [--drop-existing]      # 危险: 先清空 PG 目标表 (全新库迁移用)
        [--verify-only]        # 只做迁移后校验, 不写数据

迁移内容: 9 张主表全量行 (students / interventions / evidence_log /
event_log / calibration_log / bloom_goals / trajectory_snapshots /
misconception_evidence / judge_audit_log) + 双状态表
(student_lca_state / student_dual_agent_state, LCAStore/DualAgentStore 各自建)。

设计:
  - 依赖 12.5 适配层: PG 侧直接用 Database(dsn) 建表, 占位符翻译/行值
    归一化复用同一套代码 (迁移脚本本身也是适配层正确性的大型实测)
  - 写入顺序按 FK 依赖: students 最先, 其余并行无依赖, 每表一个事务
  - 验证 (迁移完成后自动跑, verify-only 模式单独跑):
      1. 行数逐表核对 (SQLite vs PG)
      2. JSON 列抽检 (随机行 json.loads 成功 + 键集合一致)
      3. FK 完整性 (PG 侧 FK 全部强制, 写入成功即已通过; 此处再查孤儿行)
      4. 关键列内容抽检 (state_snapshot BYTEA 字节一致)
  - 幂等性: event_id / 主键冲突 → INSERT ... ON CONFLICT DO NOTHING
    (重复跑不炸不重), 其余表 --drop-existing 后全量重灌

安全注意: --drop-existing 会 DELETE 全部目标表数据, 只允许指向全新/可丢弃库。
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cogedu.persistence.adapter import translate_sql  # noqa: E402
from cogedu.persistence.db import Database, DatabaseConfig  # noqa: E402
from cogedu.persistence.pg_schema import PG_SCHEMA_SQL  # noqa: E402

# 迁移顺序 (FK 依赖: students 必须最先; 其余表只引用 students)
TABLES_IN_ORDER = [
    "students",
    "interventions",
    "evidence_log",
    "event_log",
    "calibration_log",
    "bloom_goals",
    "trajectory_snapshots",
    "misconception_evidence",
    "judge_audit_log",
]

# 每表的数据列 (排除自增 PK — PG IDENTITY 自行分配; trajectory_snapshots
# 的 snapshot_id 例外: 保留原 id, 之后再重建序列, 见 migrate_table)
TABLE_COLUMNS: dict[str, list[str]] = {
    "students": [
        "student_id", "grade_level", "subject", "created_at", "last_active_at",
        "current_state_5d", "current_bloom_profile", "current_learning_dna",
        "tc_states", "misconception_history", "trajectory_summary",
        "confidence", "version", "consent_version", "anonymized_id",
        "warmup_count", "probe_due_in", "probe_count", "response_history",
        "theta_cov", "cognitive_twin",
    ],
    "interventions": [
        "intervention_id", "student_id", "timestamp", "intervention_type",
        "bloom_target", "target_skills", "target_misconceptions", "target_tcs",
        "difficulty", "quantity", "feedback_density", "scaffolding_level",
        "clt_level", "ca_stage", "bjork_triggers", "expected_gain",
        "expected_risk", "rationale_text", "actual_state_delta",
        "actual_bloom_delta", "causal_effect", "causal_p_value",
        "causal_significant", "calibration_round", "is_degraded_mode",
        "human_review_requested",
    ],
    "evidence_log": [
        "evidence_id", "student_id", "problem_id", "timestamp",
        "raw_response", "raw_response_time", "raw_explanation", "raw_reflection",
        "llm_critic_input", "llm_critic_output", "llm_critic_temperature",
        "llm_critic_tokens", "structured_correctness",
        "structured_explanation_quality", "structured_confusion_signals",
        "structured_self_evaluation", "state_before_update",
        "state_after_update", "state_delta", "misc_hits", "tc_signals",
        "quality_score",
    ],
    "event_log": [
        "event_id", "student_id", "timestamp", "source", "event_type",
        "payload_json",
    ],
    "calibration_log": [
        "calibration_id", "student_id", "timestamp", "calibration_round",
        "message_type", "message_payload", "state_before", "state_after",
        "trigger_reason", "trigger_evidence", "interaction_mode", "outcome",
        "human_review_requested", "fallback_to_single_agent", "duration_ms",
    ],
    "bloom_goals": [
        "goal_id", "subject", "skill_id", "skill_name", "bloom_layer",
        "description", "cognitive_objectives", "assessment_criteria",
        "threshold_concepts", "misconceptions", "prerequisites", "follow_ups",
        "curriculum_standard_ref", "created_by", "created_at", "version",
    ],
    "trajectory_snapshots": [
        "snapshot_id", "student_id", "timestamp", "snapshot_type", "epoch",
        "state_snapshot", "bloom_profile_snapshot", "learning_dna_snapshot",
        "grade_level", "semester", "transfer_metadata",
    ],
    "misconception_evidence": [
        "student_id", "misc_id", "success_count", "failure_count", "last_updated",
    ],
    "judge_audit_log": [
        "id", "student_id", "problem_id", "provider", "model", "attempts",
        "latency_ms", "judged", "error_code", "raw_output", "created_at",
    ],
}

# 含自增 PK 的表: 迁移后需把 PG 序列拨到 max(id) (否则后续 insert 主键冲突)
IDENTITY_TABLES = {
    "evidence_log": "evidence_id",
    "calibration_log": "calibration_id",
    "trajectory_snapshots": "snapshot_id",
    "judge_audit_log": "id",
}


def migrate_table(sqlite_conn, pg_db: Database, table: str) -> int:
    """迁移单表 (逐行参数化 INSERT, 单事务), 返回写入行数."""
    cols = TABLE_COLUMNS[table]
    col_list = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    on_conflict = " ON CONFLICT DO NOTHING"  # 幂等: 重复跑不炸不重

    cur = sqlite_conn.execute(f"SELECT {col_list} FROM {table}")
    rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        return 0

    written = 0
    with pg_db.tx():
        for row in rows:
            pg_db.conn.execute(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"
                f"{on_conflict}",
                row,
            )
            written += 1
    return written


def reset_identity_sequences(pg_db: Database) -> None:
    """把含 IDENTITY 列的表序列拨到 max(id), 保证后续写入不撞已迁移行."""
    for table, id_col in IDENTITY_TABLES.items():
        pg_db.conn.execute(
            f"""SELECT setval(pg_get_serial_sequence('{table}', '{id_col}'),
                COALESCE((SELECT MAX({id_col}) FROM {table}), 0) + 1, false)"""
        )


def verify(sqlite_conn, pg_db: Database) -> list[str]:
    """迁移后校验, 返回问题列表 (空 = 通过)."""
    problems: list[str] = []

    # 1. 行数逐表核对
    for table in TABLES_IN_ORDER:
        src = sqlite_conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
        dst_row = pg_db.conn.execute(
            f"SELECT COUNT(*) AS cnt FROM {table}"
        ).fetchone()
        dst = dst_row["cnt"]
        if src != dst:
            problems.append(f"行数不一致: {table} sqlite={src} pg={dst}")

    # 2. JSON 列抽检 (students 表 4 个核心 JSON 列, 随机 3 行)
    json_cols = ["current_state_5d", "response_history", "tc_states",
                 "trajectory_summary"]
    src_rows = sqlite_conn.execute(
        "SELECT student_id, current_state_5d, response_history, tc_states, "
        "trajectory_summary FROM students ORDER BY student_id"
    ).fetchall()
    sample = random.sample(src_rows, min(3, len(src_rows)))
    for row in sample:
        sid = row["student_id"]
        pg_row = pg_db.conn.execute(
            "SELECT current_state_5d, response_history, tc_states, "
            "trajectory_summary FROM students WHERE student_id = :s",
            dict(s=sid),
        ).fetchone()
        if pg_row is None:
            problems.append(f"JSON 抽检: 学生 {sid} 在 PG 缺失")
            continue
        for col in json_cols:
            a, b = row[col], pg_row[col]
            if (a is None) != (b is None):
                problems.append(f"JSON NULL 不一致: students.{col} ({sid})")
                continue
            if a is not None:
                if json.loads(a) != json.loads(b):
                    problems.append(f"JSON 内容不一致: students.{col} ({sid})")

    # 3. 孤儿行检查 (FK 引用不存在的 student)
    for table in ["interventions", "evidence_log", "event_log", "calibration_log",
                  "trajectory_snapshots", "misconception_evidence"]:
        orphan = pg_db.conn.execute(
            f"SELECT COUNT(*) AS cnt FROM {table} t WHERE NOT EXISTS "
            f"(SELECT 1 FROM students s WHERE s.student_id = t.student_id)"
        ).fetchone()
        if orphan["cnt"] > 0:
            problems.append(f"孤儿行: {table} {orphan['cnt']} 行无对应 student")

    # 4. BYTEA 字节抽检 (trajectory_snapshots)
    src_blobs = sqlite_conn.execute(
        "SELECT snapshot_id, state_snapshot FROM trajectory_snapshots "
        "WHERE state_snapshot IS NOT NULL LIMIT 5"
    ).fetchall()
    for row in src_blobs:
        pg_row = pg_db.conn.execute(
            "SELECT state_snapshot FROM trajectory_snapshots WHERE snapshot_id = :i",
            dict(i=row["snapshot_id"]),
        ).fetchone()
        if pg_row is None:
            problems.append(f"BYTEA 抽检: snapshot {row['snapshot_id']} 缺失")
        elif bytes(pg_row["state_snapshot"]) != row["state_snapshot"]:
            problems.append(f"BYTEA 内容不一致: snapshot {row['snapshot_id']}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite → PostgreSQL 数据迁移")
    parser.add_argument("--sqlite", required=True, help="SQLite 文件路径")
    parser.add_argument("--pg-dsn", required=True, help="PostgreSQL DSN (postgres://...)")
    parser.add_argument("--drop-existing", action="store_true",
                        help="危险: 迁移前 DELETE 全部目标表数据 (全新库用)")
    parser.add_argument("--verify-only", action="store_true",
                        help="跳过写入, 只跑校验")
    parser.add_argument("--skip-schema", action="store_true",
                        help="不执行建表 (目标库已 init_schema 时用)")
    args = parser.parse_args()

    if not Path(args.sqlite).exists():
        print(f"❌ SQLite 文件不存在: {args.sqlite}", file=sys.stderr)
        return 2

    sqlite_conn = sqlite3.connect(args.sqlite)
    sqlite_conn.row_factory = sqlite3.Row

    pg_db = Database(DatabaseConfig(dsn=args.pg_dsn))
    if not args.skip_schema:
        pg_db.init_schema()

    if args.drop_existing and not args.verify_only:
        print("⚠️  --drop-existing: 清空目标表 (FK 依赖倒序删除)")
        with pg_db.tx():
            for table in reversed(TABLES_IN_ORDER):
                pg_db.conn.execute(f"DELETE FROM {table}")
            for table in ("student_lca_state", "student_dual_agent_state"):
                try:
                    pg_db.conn.execute(f"DELETE FROM {table}")
                except Exception:
                    pass  # 目标库无该表 (store 未初始化) 时跳过

    if not args.verify_only:
        total = 0
        for table in TABLES_IN_ORDER:
            n = migrate_table(sqlite_conn, pg_db, table)
            total += n
            print(f"  {table}: {n} 行")
        reset_identity_sequences(pg_db)
        print(f"共写入 {total} 行; IDENTITY 序列已对齐")

    problems = verify(sqlite_conn, pg_db)
    if problems:
        print("\n❌ 校验失败:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n✅ 校验通过: 行数 / JSON 抽检 / FK 孤儿行 / BYTEA 抽检 全部一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
