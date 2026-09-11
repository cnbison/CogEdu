"""12.4 (0-C): LLM 客户端单例 — 自 Flask app.py 抽出的框架无关模块.

为什么抽出来: belief.py / lca.py 原来是 `from web.api.app import get_llm`
的惰性 import (见 belief.py:137/414, lca.py:81), 这让业务逻辑层反向依赖
Flask 装配模块 — Flask 删除 (12.4-6) 时会断。get_llm 本身与 Web 框架
无关 (ECOSLLMClient.from_env("minimax")), 抽到独立模块后:

  - belief.py / lca.py 改 `from web.api.llm import get_llm` (调用点不变)
  - FastAPI judge/intervention 路由经 web.api.llm 模块命名空间调用
  - 测试统一 patch web.api.llm.get_llm (单一 patch 面覆盖全部调用方:
    惰性 import 在函数体内执行, 运行时读模块属性, patch 生效)
"""
from __future__ import annotations

import logging

from cogedu.llm_client import ECOSLLMClient

_log = logging.getLogger(__name__)

# LLM 客户端（全局单例）
_llm_client: ECOSLLMClient | None = None


def get_llm() -> ECOSLLMClient:
    """全局 LLM 客户端 (懒加载单例, MiniMax 主)."""
    global _llm_client
    if _llm_client is None:
        _llm_client = ECOSLLMClient.from_env("minimax")
    return _llm_client


def reset_llm() -> None:
    """重置单例 (测试用)."""
    global _llm_client
    _llm_client = None
