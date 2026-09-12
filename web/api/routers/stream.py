"""12.4 (0-C): SSE 流式端点 — FastAPI 迁移时打通的流式能力.

为什么 Phase 0 就要这个 (方案文档 12.4 第 3 项):
  Phase 1 呈现引擎需要流式生成 (干预内容逐 token 推给前端), Phase 0 框架
  迁移时先把 SSE 这条能力打通, 之后 Phase 1 直接复用模式, 不用再动框架层.

设计:
  GET /api/events/stream?topics=hint_requested,response_submitted
                         &max_events=10&idle_timeout_seconds=10

  订阅进程内事件总线 (cogedu.event.get_default_bus, 与 PluginRuntime 同一
  bus), 把收到的事件实时转成 SSE 推给前端。默认订阅全部已知 topic。

  事件总线是同步回调模型 (publish 在任意线程调 handler), SSE 生成器跑在
  事件循环线程 — 用线程安全的 queue.Queue 做桥, 生成器轮询取件。

  终止条件 (三选一先到): 收满 max_events / 空闲 idle_timeout_seconds /
  客户端断开。结束后自动 unsubscribe, 不泄漏订阅。

  未来扩展 (Phase 1+): 同一模式包 LLM 生成器的 token 流
  (LLM client 的 chat_stream → SSE), 或干预生成的阶段进度流。
"""
from __future__ import annotations

import asyncio
import json
import logging
import queue
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from web.api.auth import require_authenticated

_log = logging.getLogger(__name__)

router = APIRouter(
    tags=["stream"],
    # 2-0-3 (14.2): 事件流需已登录 (任意角色)
    dependencies=[Depends(require_authenticated)],
)

# 已知 topic (跟 PluginRuntime.start 注册的 subscriber 对齐 + 通用 observation)
KNOWN_TOPICS = [
    "observation",
    "response_submitted",
    "judge_completed",
    "request_calibration",
    "request_intervention",
    "hint_requested",
    "idle_detected",
    "goal_changed",
    "reflection_completed",
    "pomdp_diagnostic_updated",
]

# 生成器轮询间隔 (秒): 上限即 SSE 首 token 延迟 + keepalive 间隔的粒度
_POLL_INTERVAL = 0.05


def _serialize_event(event: Any) -> Dict[str, Any]:
    """LearningEvent → JSON 可序列化 dict (payload 原样透传)."""
    ts = getattr(event, "timestamp", None)
    if isinstance(ts, datetime):
        ts = ts.isoformat()
    return {
        "event_id": getattr(event, "event_id", None),
        "student_id": getattr(event, "student_id", None),
        "timestamp": ts,
        "source": getattr(event, "source", None),
        "event_type": getattr(event, "event_type", None),
        "payload": getattr(event, "payload", None),
    }


@router.get("/api/events/stream")
async def stream_events(
    topics: Optional[str] = Query(
        None, description="逗号分隔的 topic 列表; 缺省订阅全部已知 topic"
    ),
    max_events: int = Query(
        0, ge=0, description="收满 N 条后结束流; 0 = 不限 (直到空闲超时或断开)"
    ),
    idle_timeout_seconds: float = Query(
        30.0, gt=0, description="连续空闲 N 秒无事件则结束流 (0 不允许, 防永挂)"
    ),
) -> StreamingResponse:
    """SSE: 实时推送事件总线上的 LearningEvent."""
    from cogedu.event import get_default_bus

    topic_list: List[str] = (
        [t.strip() for t in topics.split(",") if t.strip()] if topics else KNOWN_TOPICS
    )
    bus = get_default_bus()

    # 线程安全桥: bus handler (可能在任意线程被 publish 调) → SSE 生成器 (事件循环)
    q: "queue.Queue[tuple[str, Any]]" = queue.Queue()
    sub_ids: List[str] = []

    def _on_event(event: Any, _topic: str = "") -> None:
        # handler 收到的只有 event; topic 由 event.event_type 自带,
        # 这里闭包变量 _topic 由 subscribe 时的 partial 绑定 (见下)
        q.put((_topic or getattr(event, "event_type", "unknown"), event))

    import functools

    for topic in topic_list:
        sub_ids.append(
            bus.subscribe(topic, functools.partial(_on_event, _topic=topic))
        )

    async def _gen():
        import time as _time

        received = 0
        last_event_at = _time.monotonic()
        try:
            while True:
                try:
                    topic, event = q.get_nowait()
                except queue.Empty:
                    if _time.monotonic() - last_event_at >= idle_timeout_seconds:
                        break
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue
                last_event_at = _time.monotonic()
                received += 1
                data = json.dumps(_serialize_event(event), ensure_ascii=False, default=str)
                yield f"event: {topic}\ndata: {data}\n\n"
                if max_events > 0 and received >= max_events:
                    break
        finally:
            for sid in sub_ids:
                bus.unsubscribe(sid)

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # nginx 代理不缓冲, 保流式语义
        },
    )
