"""1-C (Phase 1) / 3-F (Phase 3): 呈现引擎业务服务 — 框架无关的编排层.

从路由层（web/api/routers/presentation.py）拆出，跟 belief.py / judge.py
同样的"框架无关业务模块"定位，测试 patch 面单一。

持久化失败语义（presentation-runtime-map.md §4）：save 失败返回 False
+ warning（store 层留痕），本层不因落库失败而中断呈现——生成结果仍
返回给前端，调用方可感知（save_* 布尔返回）。

TTS 异步补齐（3-F-3，v0.6 拍板"异步补齐 + 播放端降级"）：/scenes 返回
后由**进程内后台线程**逐条预生成 speech 动作音频、回填 audio_id 并更新
落库；播放端无音频时走估算计时器静音降级（3-D-5）。诚实注记：计划中
写的是 asyncio task，但 /scenes 是同步端点（线程池执行无事件循环），
daemon 线程语义等价（进程内 + 低并发逐条 + 重启丢失可接受）。
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import UTC, datetime

from cogedu.persistence.presentation_store import AudioRecord, PresentationStore
from cogedu.presentation.audio_duration import measure_audio_duration
from cogedu.presentation.outline import OutlineGenerator
from cogedu.presentation.retry import RetryPolicy
from cogedu.presentation.scene import SceneGenerator
from cogedu.presentation.tts import MiniMaxTTSClient, SupportsTTS, TTSConfig
from cogedu.presentation.types import Outline, Scene, SpeechAction
from web.api import llm as llm_service

_log = logging.getLogger(__name__)

# 跟 LCAStore / DualAgentStore 同一 db 路径口径（ECOS_DB_PATH 环境变量）
DEFAULT_DB_PATH = "web/ecos.db"

# 1-D-2: 生成层重试参数走环境变量 (COGEDU_PRESENTATION_MAX_ATTEMPTS /
# COGEDU_PRESENTATION_BACKOFF_SEC), 默认值收敛在 RetryPolicy
_RETRY_POLICY = RetryPolicy.from_env()

_store: PresentationStore | None = None

# TTS 单例 (lazy init): 未配置 key → None, speech 走静音降级 (3-D-5)
_tts_client: SupportsTTS | None = None
_tts_initialized = False


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


def get_tts() -> SupportsTTS | None:
    """TTS 客户端单例（lazy init）. 未配置 COGEDU_TTS_API_KEY → None."""
    global _tts_client, _tts_initialized
    if not _tts_initialized:
        _tts_initialized = True
        try:
            _tts_client = MiniMaxTTSClient(TTSConfig.from_env())
        except Exception as e:
            _log.info("TTS 未配置, speech 动作将静音降级 (3-D-5): %s", e)
            _tts_client = None
    return _tts_client


def reset_tts() -> None:
    """测试隔离用."""
    global _tts_client, _tts_initialized
    _tts_client = None
    _tts_initialized = False


def persist_outline(outline: Outline) -> bool:
    """保存大纲（失败 False + warning，不中断呈现）."""
    return get_store().save_outline(outline)


def backfill_scene_audio(
    scenes: list[Scene],
    store: PresentationStore,
    client: SupportsTTS,
) -> None:
    """逐条预生成 speech 动作音频并回填 audio_id（3-F-3，同步执行体）.

    audio_id = tts_{scene_id}_{action_id} 幂等键：已存在直接回填跳过
    （force 重生成留口：删表行即可）。合成/落库失败 → 该动作保持
    audio_id=None（前端静音降级），不中断其他动作。全部处理完后有
    变更的 scene 以幂等覆盖方式重新落库。
    """
    for scene in scenes:
        if not scene.actions:
            continue
        changed = False
        for action in scene.actions:
            if not isinstance(action, SpeechAction) or action.audio_id:
                continue
            audio_id = f"tts_{scene.scene_id}_{action.action_id}"
            if store.get_audio(audio_id) is not None:
                action.audio_id = audio_id
                changed = True
                continue
            try:
                result = client.generate(
                    action.text, voice=action.voice, speed=action.speed or 1.0
                )
            except Exception as e:
                _log.warning(
                    "TTS 合成失败 (audio=%s), 该段将静音降级: %s", audio_id, e
                )
                continue
            # 入库时字节嗅探测一次时长 (3-D-2); 失败 None 落 NULL 不猜数
            duration = measure_audio_duration(result.audio)
            saved = store.save_audio(AudioRecord(
                audio_id=audio_id,
                scene_id=scene.scene_id,
                action_id=action.action_id,
                audio=result.audio,
                duration_ms=duration,
                format=result.format,
                created_at=datetime.now(UTC).isoformat(),
            ))
            if not saved:
                continue  # 落库失败不回填 (warning 已在 store 层留痕)
            action.audio_id = audio_id
            changed = True
        if changed:
            # 幂等覆盖回填 audio_id (payload 全文更新; 前端拿到的旧响应
            # 不受影响——音频端点按 audio_id 独立取)
            store.save_scene(scene)


def _maybe_spawn_tts_backfill(scenes: list[Scene], store: PresentationStore) -> None:
    """有 speech 动作且 TTS 已配置时, 起后台线程补齐 (3-F-3; 请求不等它)."""
    if not any(s.actions for s in scenes):
        return
    client = get_tts()
    if client is None:
        return
    threading.Thread(
        target=backfill_scene_audio,
        args=(scenes, store, client),
        daemon=True,
        name="tts-backfill",
    ).start()


def generate_scenes_for_outline(outline_id: str) -> list[Scene]:
    """第二阶段编排: 取大纲 → 恢复生成上下文 → 逐步生成 → 落库 → TTS 后台补齐.

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
    # 3-F-3: TTS 异步补齐 (后台线程, 请求不等; 未配置/无 speech 静默跳过)
    _maybe_spawn_tts_backfill(scenes, store)
    return scenes


# OutlineGenerator 从本模块 re-export (单一 patch 面: web.api.presentation_service)
__all__ = [
    "OutlineGenerator",
    "backfill_scene_audio",
    "generate_scenes_for_outline",
    "get_store",
    "get_tts",
    "persist_outline",
    "reset_store",
    "reset_tts",
]
