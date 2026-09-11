"""Phase 0 (12.2) 答题主链路 HTTP 级安全网补充测试.

背景: 既有测试里 /api/answer 的 HTTP 级覆盖只有 test_v0990_signal_collection
(信号采集专项, 且部分用例 mock 掉了 submit_answer), 业务逻辑层覆盖是直接
函数调用 (8 个测试文件). 0-B/0-C/0-D 三项改造 (统一入口 + Flask→FastAPI +
SQLite→PostgreSQL) 都会重写这条链路, 迁移前补两块 HTTP 级安全网:

  1. 响应字段契约 — POST /api/answer 返回的 9 个字段 (函数级 8 个 + 路由层回显的 reasoning) 一个不能丢
     (belief-migration-map.md 表 #12 的对照物, FastAPI 迁移时逐字段核对)
  2. 持久化失败可见性 — save 失败必须 persisted=false 返回给前端并记 warning
     (v0.47.5 "Bisen 反馈 4 道题没存" 真实事故的防线, 见 belief.py 注释)

这两条是"重写时最容易被无声破坏、又最难靠 review 发现"的部分.
"""

from __future__ import annotations

import logging

import pytest


@pytest.fixture
def flask_client():
    from fastapi.testclient import TestClient

    from web.api.fastapi_app import app
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """get_llm → None, 防止真实 LLM 调用 (与 test_v0990_signal_collection 同惯例)."""
    import web.api.llm as llm_mod
    monkeypatch.setattr(llm_mod, "get_llm", lambda: None)


@pytest.fixture
def tmp_db():
    """conftest isolated_ecos_db 已设 ECOS_DB_PATH; 这里确保 schema + 学生行."""
    import os
    from cogedu.persistence.db import Database
    db = Database(os.environ["ECOS_DB_PATH"])
    db.init_schema()
    db.upsert_student("stu-contract")
    return db


# ─── 1. 响应字段契约 ─────────────────────────────────────────────────────


class TestAnswerResponseContract:
    def test_response_contract_all_fields_and_types(
        self, flask_client, tmp_db
    ):
        """POST /api/answer → 200 + 9 字段契约 (含路由层 reasoning) (belief-migration-map 表 #12).

        FastAPI 迁移时逐字段核对: 任何一个字段丢失/改名都会在本测试爆.
        """
        resp = flask_client.post("/api/answer", json={
            "student_id": "stu-contract",
            "problem_id": "PB-Q04",
            "skill_id": "python.variables",
            "correct": False,
            "score": 0.0,
            "bloom_layer": "L4",
        })
        assert resp.status_code == 200
        body = resp.json()

        # 字段集合契约 (多一个少一个都算破坏) — 9 字段 =
        # belief-migration-map.md 表 #12 的 8 个字段 + 路由层回显的
        # reasoning (v0.52.2, app.py 的 result["reasoning"] = reasoning)
        assert set(body.keys()) == {
            "correct", "score", "theta",
            "misc_triggered", "misc_id", "misc_confidence",
            "c_discount_factor", "persisted", "reasoning",
        }

        # 类型契约
        assert isinstance(body["correct"], bool)
        assert isinstance(body["reasoning"], str)
        assert isinstance(body["score"], (int, float))
        assert isinstance(body["misc_triggered"], bool)
        assert isinstance(body["misc_id"], str)
        assert isinstance(body["misc_confidence"], (int, float))
        assert isinstance(body["c_discount_factor"], (int, float))
        assert isinstance(body["persisted"], bool)

        # theta: 5 维 K/P/S/C/X, 每维是 float
        assert set(body["theta"].keys()) == {"K", "P", "S", "C", "X"}
        for dim, val in body["theta"].items():
            assert isinstance(val, (int, float)), f"theta.{dim} 应为数字"

    def test_partial_credit_derivation_through_http(
        self, flask_client, tmp_db
    ):
        """score=0.7 → correct=True (>=0.6 派生), HTTP 层验证 partial credit 口径."""
        resp = flask_client.post("/api/answer", json={
            "student_id": "stu-contract",
            "problem_id": "PB-Q04",
            "skill_id": "python.variables",
            "correct": False,  # 显式传 False, 但 score 应优先生效
            "score": 0.7,
            "bloom_layer": "L4",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["score"] == 0.7
        assert body["correct"] is True, "score>=0.6 应派生 correct=True"

    def test_persisted_true_on_success(self, flask_client, tmp_db):
        """正常路径 persisted=true (契约的正向锚点)."""
        resp = flask_client.post("/api/answer", json={
            "student_id": "stu-contract",
            "problem_id": "PB-Q04",
            "skill_id": "python.variables",
            "correct": True,
            "bloom_layer": "L3",
        })
        assert resp.status_code == 200
        assert resp.json()["persisted"] is True


# ─── 2. 持久化失败可见性 (真实事故防线) ──────────────────────────────────


class TestPersistenceFailureVisibility:
    def test_save_failure_returns_persisted_false_and_warns(
        self, flask_client, tmp_db, monkeypatch, caplog
    ):
        """save_student_state 失败 → HTTP 200 + persisted=false + warning 留痕.

        v0.47.5 之前是 silent pass, 导致 Bisen 反馈 "4 道题没存" 的事故:
        前端以为成功, 数据全丢. 这条测试守住 "失败必须暴露" 的约定,
        FastAPI/PostgreSQL 迁移时此行为不允许退化.
        """
        import web.api.belief as belief_api

        class _BoomSaveDb:
            """只有 save_student_state 炸, 其余委托真实 tmp_db.

            注意: _get_db() 在 _get_or_create_student (读状态) 和 reconcile
            (防御性 try/except 里) 也会被调 — 那些路径必须能正常走通,
            模拟的是"仅落盘失败"的精准场景, 不是整个 DB 不可用.
            """

            def __init__(self, real_db):
                self._real = real_db

            def save_student_state(self, *a, **kw):
                raise RuntimeError("模拟 save 失败 (DB 满/锁死)")

            def __getattr__(self, name):
                return getattr(self._real, name)

        monkeypatch.setattr(belief_api, "_get_db", lambda: _BoomSaveDb(tmp_db))

        with caplog.at_level(logging.WARNING, logger="web.api.belief"):
            resp = flask_client.post("/api/answer", json={
                "student_id": "stu-contract",
                "problem_id": "PB-Q04",
                "skill_id": "python.variables",
                "correct": True,
                "bloom_layer": "L3",
            })

        # 主流程不阻断: 仍然 200, 学生端不白屏
        assert resp.status_code == 200
        body = resp.json()
        # 失败信号必须到达前端 (这是事故修复的核心行为)
        assert body["persisted"] is False
        # 其余字段不受影响 (引擎更新本身是成功的)
        assert body["correct"] is True
        # 必须留 warning, 不允许静默 (caplog 捕获 belief 模块 logger)
        save_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "save_student_state" in r.getMessage()
        ]
        assert save_warnings, "save 失败必须记 warning, 不允许 silent pass"
