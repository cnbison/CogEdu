"""Phase 1 1-C-3: PresentationStore 双后端测试 (SQLite 恒跑 / PG 无服务器 skip).

覆盖 (对齐 test_pg_backend.py 的双后端奇偶模式):
  - outline/scene 落库 + 回读 (payload JSON round-trip)
  - 追溯查询: by_outline / by_intervention / by_evidence (错因→场景反查)
  - 幂等覆盖 (同 id 重写)
  - degraded 标记落库
  - 双后端奇偶: 同一操作序列 SQLite 与 PG 结果一致
"""
from __future__ import annotations

import os
import uuid

import pytest

from cogedu.persistence.adapter import BACKEND_POSTGRES, BACKEND_SQLITE
from cogedu.persistence.presentation_store import PresentationStore
from cogedu.presentation.types import (
    GenerationContext,
    ImageBlock,
    Outline,
    OutlineStep,
    Scene,
    TextBlock,
)

# 默认 admin DSN: 本机 Homebrew PostgreSQL (12.5); CI 无 PG 时 skip
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


@pytest.fixture
def store(request, tmp_path, pg_dsn) -> PresentationStore:
    """参数化双后端 store (sqlite 恒跑, pg 有服务器才跑)."""
    if request.param == BACKEND_POSTGRES:
        s = PresentationStore(db_path=pg_dsn)
    else:
        s = PresentationStore(db_path=str(tmp_path / "presentation.db"))
    yield s
    s.close()


def _outline(**overrides) -> Outline:
    defaults = dict(
        student_id="stu_001",
        intervention_id="int_x",
        goal_id="goal_1",
        evidence_id="ev_9",
        title="二次函数入门",
        steps=[
            OutlineStep(title="第一步", key_points=["kp1"]),
            OutlineStep(title="第二步", key_points=["kp2"]),
        ],
    )
    defaults.update(overrides)
    outline = Outline(**defaults)
    outline.context = GenerationContext(
        student_id="stu_001",
        intervention_id="int_x",
        goal_id="goal_1",
        evidence_id="ev_9",
    )
    return outline


def _scene(outline: Outline, step: OutlineStep, **overrides) -> Scene:
    defaults = dict(
        outline_id=outline.outline_id,
        step_id=step.step_id,
        student_id=outline.student_id,
        intervention_id=outline.intervention_id,
        goal_id=outline.goal_id,
        evidence_id=outline.evidence_id,
        title=step.title,
        blocks=[TextBlock(content="讲解 $x^2$"), ImageBlock(placeholder=True)],
    )
    defaults.update(overrides)
    return Scene(**defaults)


@pytest.mark.parametrize("store", [BACKEND_SQLITE, BACKEND_POSTGRES], indirect=True)
class TestRoundTrip:
    def test_outline_save_and_get(self, store):
        outline = _outline()
        assert store.save_outline(outline) is True
        got = store.get_outline(outline.outline_id)
        assert got is not None
        assert got.title == "二次函数入门"
        assert [s.title for s in got.steps] == ["第一步", "第二步"]
        # context 随 payload 完整恢复
        assert got.context is not None
        assert got.context.intervention_id == "int_x"

    def test_scene_save_and_list_by_outline(self, store):
        outline = _outline()
        store.save_outline(outline)
        for step in outline.steps:
            assert store.save_scene(_scene(outline, step)) is True
        scenes = store.list_scenes_by_outline(outline.outline_id)
        assert len(scenes) == 2
        assert [s.title for s in scenes] == ["第一步", "第二步"]
        assert scenes[0].blocks[0].content == "讲解 $x^2$"

    def test_traceability_queries(self, store):
        """追溯查询形状 (1-A-4 契约): intervention / evidence 反查."""
        o1 = _outline(evidence_id="ev_A", intervention_id="int_A")
        o2 = _outline(evidence_id="ev_B", intervention_id="int_B")
        store.save_outline(o1)
        store.save_outline(o2)
        for o in (o1, o2):
            for step in o.steps:
                store.save_scene(_scene(o, step))

        by_int = store.list_scenes_by_intervention("int_A")
        assert {s.outline_id for s in by_int} == {o1.outline_id}
        assert len(by_int) == 2

        by_ev = store.list_scenes_by_evidence("ev_B")
        assert {s.outline_id for s in by_ev} == {o2.outline_id}

        assert store.list_scenes_by_evidence("ev_none") == []

    def test_idempotent_overwrite(self, store):
        outline = _outline()
        store.save_outline(outline)
        outline.title = "改标题"
        outline.steps = [OutlineStep(title="新步骤")]
        store.save_outline(outline)
        got = store.get_outline(outline.outline_id)
        assert got is not None
        assert got.title == "改标题"
        assert len(got.steps) == 1

    def test_degraded_flag_persisted(self, store):
        outline = _outline()
        store.save_outline(outline)
        scene = _scene(outline, outline.steps[0], degraded=True,
                       warnings=["LLM 重试耗尽, 模板降级"])
        store.save_scene(scene)
        got = store.list_scenes_by_outline(outline.outline_id)
        assert got[0].degraded is True
        assert got[0].warnings == ["LLM 重试耗尽, 模板降级"]

    def test_get_outline_missing(self, store):
        assert store.get_outline("no_such_outline") is None
