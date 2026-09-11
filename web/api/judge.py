"""12.4 (0-C): LLM Judge 评判逻辑 — 自 Flask app.py 抽出的框架无关模块.

三个函数原样迁移 (v0.56.1 / v0.58.0 / v0.99.0 的行为注释全部保留,
这是 belief-migration-map.md 对照表的一部分, 不允许语义漂移):

  - _call_llm_judge_with_retry: retry loop (Bisen 原则: 失败不兜底, 显式 fail)
  - _build_judge_prompt:        prompt 构造 (含 partial credit rubric 注入)
  - _parse_judge_result:        结果解析 (score 优先 correct)

为什么抽出来: 测试 (test_judge_rubric / test_judge_retry) 原来
`from web.api.app import _build_judge_prompt` — 依赖 Flask 装配模块。
抽到独立模块后测试改 import 本模块, Flask 删除 (12.4-6) 不受影响。
"""
from __future__ import annotations

import json
import logging
import time

from cogedu.llm_client import ECOSLLMClient

_log = logging.getLogger(__name__)


def _call_llm_judge_with_retry(llm: ECOSLLMClient, prompt: str):
    """LLM judge retry loop (v0.56.1 修 BUG, v0.58.0 扩展支持 partial credit).

    Bisen 原则 (2026-07-24): LLM judge 失败时**不**启发式兜底, **不**字符串匹配兜底.
    任何 fallback 都是 silent degradation 变种, 失败就显式 fail.

    v0.58.0 扩展: 支持 LLM 输出 {correct, score} 二者之一.
      - 老 prompt 只要求 correct, 兼容
      - 新 prompt (有 rubric 时) 要求 score, 验证字段时改

    Args:
        llm: ECOSLLMClient 实例
        prompt: 评判 prompt

    Returns:
        (result_dict, attempt_count, last_raw_response) 成功
        (None, attempt_count, last_raw_response) 全部失败
        v0.99.0 (F-05): 第三元素 = 最后一次 LLM 原始返回 (审计落库用),
        全部 chat 异常时为 None

    防御性自检 [1]: 每次重试失败必须 _log.warning(..., exc_info=True), 不能 silent pass.
    防御性自检 [6] (v0.56.1 新增): 不写启发式 fallback 替代 AI 评判.
    防御性自检 [8] (v0.58.0 新增): result 必须有 correct 或 score 之一, 不能两者都缺.
    """
    delays = [0.1, 0.5, 2.0]  # 短-中-长 (s), Bisen 拍板 2026-07-24
    max_attempts = 3
    last_raw: str | None = None  # v0.99.0 (F-05): 审计用

    for attempt in range(1, max_attempts + 1):
        try:
            raw = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                strip_think=True,
            )
            last_raw = raw

            # 解析 JSON
            try:
                result = json.loads(raw)
                # v0.58.0: 验证 result 至少有 correct 或 score 之一 (防御性自检 [8])
                if "correct" not in result and "score" not in result:
                    raise ValueError(
                        f"LLM response missing both 'correct' and 'score' fields: {(raw or '')[:100]}"
                    )
                return result, attempt, last_raw
            except (json.JSONDecodeError, ValueError) as parse_err:
                _log.warning(
                    "/api/judge: LLM JSON parse 失败 (attempt %d/%d): %s, raw_truncated=%s",
                    attempt, max_attempts, parse_err, (raw or "")[:200],
                )
                if attempt < max_attempts:
                    time.sleep(delays[attempt - 1])
                continue
        except Exception as llm_err:
            _log.warning(
                "/api/judge: LLM chat 调用失败 (attempt %d/%d): %s",
                attempt, max_attempts, llm_err, exc_info=True,
            )
            if attempt < max_attempts:
                time.sleep(delays[attempt - 1])
            continue

    return None, max_attempts, last_raw


def _build_judge_prompt(
    problem_text: str,
    correct_answer: str,
    student_answer: str,
    partial_credit_rubric: dict | None = None,
) -> str:
    """v0.58.0: 构造 LLM judge prompt (支持 partial_credit_rubric 注入).

    Args:
        problem_text: 题目
        correct_answer: 标准答案
        student_answer: 学生答案
        partial_credit_rubric: Q 矩阵里的 4 档分 rubric (可选, None 时走老 prompt)

    Returns:
        完整 prompt string
    """
    if partial_credit_rubric:
        # v0.58.0: 有 rubric 时, 要求 LLM 按 4 档分输出 score (不再用 correct 二元)
        rubric_lines = "\n".join(
            f"  {k} 分: {v}" for k, v in sorted(partial_credit_rubric.items())
        )
        return f"""你是一位严格的 Python 老师。请评判学生答案, **必须按 partial credit rubric 4 档分**。

题目：
{problem_text}

正确答案：
{correct_answer}

学生答案：
{student_answer}

**评分标准 (按 4 档分, 必须严格按此给分)**：
{rubric_lines}

请以 JSON 格式返回评判结果（只返回 JSON，不要其他内容）：
{{"score": 0.0/0.3/0.6/1.0, "correct": true/false, "reasoning": "按 rubric 哪一档, 简短说明（1-2句话）"}}

注 1: correct 派生自 score (score >= 0.6 → correct=true, 否则 false), 但 score 是核心字段, 优先按 score 评分.
注 2: reasoning 中指出学生错误时, **必须引用学生答案原文中的对应内容**作为依据, 不得凭空声称学生答案中不存在的错误 (v0.98.8 F-06: 防幻觉, 事后可对照原文审计).
"""
    else:
        # 老 prompt (无 rubric): 二元 correct
        return f"""你是一位严格的 Python 老师。请评判学生答案是否正确。

题目：
{problem_text}

正确答案：
{correct_answer}

学生答案：
{student_answer}

请以 JSON 格式返回评判结果（只返回 JSON，不要其他内容）：
{{"correct": true/false, "reasoning": "简短说明为什么对或错（1-2句话）"}}

注: reasoning 中指出学生错误时, **必须引用学生答案原文中的对应内容**作为依据, 不得凭空声称学生答案中不存在的错误 (v0.98.8 F-06: 防幻觉, 事后可对照原文审计).
"""


def _parse_judge_result(result: dict) -> tuple[bool, float, str]:
    """v0.58.0: 解析 LLM judge 输出, 提取 (correct, score, reasoning).

    优先级: score > correct (v0.58.0 偏好).
    老 prompt 只有 correct 时: score 从 correct 派生 (1.0 或 0.0).

    Args:
        result: LLM 返回的 dict

    Returns:
        (correct: bool, score: float in [0, 1], reasoning: str)
    """
    # 优先 score (v0.58.0 partial credit 评分)
    if "score" in result:
        try:
            score = float(result["score"])
        except (TypeError, ValueError):
            # score 字段存在但解析失败, 视为 0.0 + log warning
            _log.warning(
                "/api/judge: LLM 返回 score 字段但解析失败: %r, fallback 到 correct",
                result.get("score"),
            )
            score = 0.0
        score = max(0.0, min(1.0, score))  # clamp [0, 1]
        correct = score >= 0.6
    else:
        # 老数据: 只有 correct, 派生 score
        correct = bool(result.get("correct", False))
        score = 1.0 if correct else 0.0

    reasoning = str(result.get("reasoning", ""))
    return correct, score, reasoning
