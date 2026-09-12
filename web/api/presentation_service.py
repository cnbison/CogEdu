"""1-C (Phase 1): 呈现引擎业务服务 — 框架无关的编排层.

从路由层（web/api/routers/presentation.py）拆出，跟 belief.py / judge.py
同样的"框架无关业务模块"定位，测试 patch 面单一。

持久化失败语义（presentation-runtime-map.md §4）：save 失败返回 False
+ warning（store 层留痕），本层不因落库失败而中断呈现——生成结果仍
返回给前端，调用方可感知（save_* 布尔返回）。
"""
from __future__ import annotations

import logging
import os

from cogedu.persistence.presentation_store import PresentationStore
from cogedu.presentation.outline import OutlineGenerator
from cogedu.presentation.retry import RetryPolicy
from cogedu.presentation.scene import SceneGenerator
from cogedu.presentation.types import Outline, Scene
from web.api import llm as llm_service

_log = logging.getLogger(__name__)

# 跟 LCAStore / DualAgentStore 同一 db 路径口径（ECOS_DB_PATH 环境变量）
DEFAULT_DB_PATH = "web/ecos.db"

# 1-D-2: 生成层重试参数走环境变量 (COGEDU_PRESENTATION_MAX_ATTEMPTS /
# COGEDU_PRESENTATION_BACKOFF_SEC), 默认值收敛在 RetryPolicy
_RETRY_POLICY = RetryPolicy.from_env()

_store: PresentationStore | None = None


def get_store() -> PresentationStore:
    """PresentationStore 单例 (lazy init, 失败有日志不静默)."""
    global _store
    if _store is None:
        db_path = os.environ.get("ECOS_DB_PATH", DEFAULT_DB_PATH)
        try:
            _store = PresentationStore(db_path=db_path)
        except Exception:
            _log.warning(
                "PresentationStore 初始化失败 (db=%s), 呈现持久化不可用",
                db_path, exc_info=True,
            )
            raise
    return _store


def reset_store() -> None:
    """测试隔离用（对齐 conftest 对单例的归一化模式）."""
    global _store
    if _store is not None:
        _store.close()
    _store = None


def persist_outline(outline: Outline) -> bool:
    """保存大纲（失败 False + warning，不中断呈现）."""
    return get_store().save_outline(outline)


def generate_scenes_for_outline(outline_id: str) -> list[Scene]:
    """第二阶段编排: 取大纲 → 恢复生成上下文 → 逐步生成 → 落库.

    Raises:
        LookupError: outline_id 不存在
        ValueError: 大纲缺生成上下文（1-A 契约: /outline 落库时必带）
        SceneGenerationError / ValueError: LLM 侧失败（502 收敛）
    """
    store = get_store()
    outline = store.get_outline(outline_id)
    if outline is None:
        raise LookupError(f"大纲不存在: {outline_id}")
    ctx = outline.context
    if ctx is None:
        raise ValueError(
            f"大纲 {outline_id} 缺少生成上下文 (context)——"
            "无法为场景生成重建 pedagogy 字段"
        )
    generator = SceneGenerator(llm_service.get_llm())
    # 1-D: 重试 + 降级 (解析失败重试耗尽 → degraded scene, 学生端不空白;
    # 传输层 RuntimeError 不降级, 原样上抛由路由层 502)
    scenes = generator.generate_for_outline(outline, ctx, policy=_RETRY_POLICY)
    for scene in scenes:
        # 落库失败不中断呈现 (save_scene 内部已 warning 留痕)
        store.save_scene(scene)
    return scenes


# OutlineGenerator 从本模块 re-export (单一 patch 面: web.api.presentation_service)
__all__ = [
    "OutlineGenerator",
    "generate_scenes_for_outline",
    "get_store",
    "persist_outline",
    "reset_store",
]
