"""1-D-1 (Phase 1, 13.5): LLM 结构化输出的容错 JSON 解析.

选型（13.5 决策）：直接用 PyPI ``json-repair``（MIT，活跃维护，纯
Python 无传递依赖），不自己写——方案文档明确"Python 生态有现成的
JSON 修复库可以评估，合适直接用"。

流水线（对齐 ECOSLLMClient.chat_json 的语义，补上"格式不完全合规"
的修复层）：
  原始文本 → clean_llm_output（剥离 <think> 块 + markdown 围栏，
  复用 cogedu/llm_client.py 的既有工具）→ json.loads
  → 失败时 json_repair 修复（warning 留痕，不静默）→ 仍失败抛 ValueError

生成器（outline.py / scene.py）的 Protocol 由此从 ``chat_json`` 改为
``chat``：raw text 拿在生成层手里，才能做修复而不是从异常 message
里反解原文。
"""

from __future__ import annotations

import json
import logging

import json_repair

# 复用内核 LLM 模块的输出清理工具（同一包内的工具函数, 非状态入口）
from cogedu.llm_client import clean_llm_output

_log = logging.getLogger(__name__)


def parse_llm_json(text: str) -> object:
    """LLM 文本 → Python 对象；容错修复，最终失败抛 ValueError 含原文."""
    cleaned = clean_llm_output(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        _log.warning(
            "LLM JSON 解析失败, 尝试 json-repair 修复: %s", e,
        )
    try:
        repaired = json_repair.repair_json(cleaned, return_objects=True)
    except Exception:
        _log.warning("json-repair 自身异常, 视为修复失败", exc_info=True)
        repaired = None
    if repaired is not None and repaired != "":
        if isinstance(repaired, str):
            # repair_json 在彻底修不了时会返回空串/原样字符串——按失败处理
            _log.warning("json-repair 未得到结构化结果 (返回 %s)", type(repaired).__name__)
        else:
            _log.info("json-repair 修复成功 (type=%s)", type(repaired).__name__)
            return repaired
    raise ValueError(
        f"LLM 输出无法解析为 JSON（含容错修复后）。\n原始文本：\n{text}"
    )
