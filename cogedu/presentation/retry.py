"""1-D-2 (Phase 1, 13.5): 生成层重试策略.

职责切分（避免重复重试）：
  - 传输层失败（网络/限流/超时）：ECOSLLMClient._call_with_retry 已做
    （指数退避 max_retries=3, timeout=30s，见 cogedu/llm_client.py），
    最终失败抛 RuntimeError——生成层**不再重试**，直接上抛。
  - 解析层失败（LLM 返回了东西但 JSON 不合规 → ValueError）：这是
    换一次采样可能就好解决的问题，生成层按 RetryPolicy 重试。

参数进配置：presentation_service 从环境变量构造 RetryPolicy
（COGEDU_PRESENTATION_MAX_ATTEMPTS / _BACKOFF_SEC），默认值收敛在这里。
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

_log = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """生成层重试参数（仅针对解析失败 ValueError）."""

    max_attempts: int = 3
    backoff_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> RetryPolicy:
        """从环境变量构造（缺省用默认值；非法值 warning + 默认值兜底）."""

        def _int_env(name: str, default: int) -> int:
            raw = os.environ.get(name)
            if not raw:
                return default
            try:
                return int(raw)
            except ValueError:
                _log.warning("环境变量 %s=%r 非法, 用默认值 %d", name, raw, default)
                return default

        def _float_env(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if not raw:
                return default
            try:
                return float(raw)
            except ValueError:
                _log.warning("环境变量 %s=%r 非法, 用默认值 %s", name, raw, default)
                return default

        return cls(
            max_attempts=max(1, _int_env("COGEDU_PRESENTATION_MAX_ATTEMPTS", 3)),
            backoff_seconds=max(0.0, _float_env("COGEDU_PRESENTATION_BACKOFF_SEC", 1.0)),
        )


def call_with_retry(
    fn: Callable[[], T],
    policy: RetryPolicy,
    *,
    what: str,
    retry_on: tuple[type[Exception], ...] = (ValueError,),
) -> T:
    """带退避的重试执行（默认只捕 ValueError 解析失败）.

    每次失败 warning 留痕（不静默）；耗尽后抛最后一次的异常。
    retry_on 之外的异常（如传输层 RuntimeError）立即上抛不重试。
    """
    last_exc: Exception | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except retry_on as e:
            last_exc = e
            _log.warning(
                "%s 第 %d/%d 次尝试失败: %s",
                what, attempt, policy.max_attempts, e,
            )
            if attempt < policy.max_attempts and policy.backoff_seconds > 0:
                time.sleep(policy.backoff_seconds * attempt)
    assert last_exc is not None
    raise last_exc
