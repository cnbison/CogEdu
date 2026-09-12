"""Phase 1 1-D: 生成健壮性测试 — 容错解析 / 重试策略 / 降级.

覆盖 (13.5):
  - parse_llm_json: 合规 JSON / think 块+围栏残留 / 尾逗号单引号等
    不合规 JSON (json-repair 修复) / 彻底修不了 → ValueError 含原文
  - RetryPolicy.from_env: 默认值 / 环境变量 / 非法值兜底 + warning
  - call_with_retry: 重试后成功 / 耗尽上抛 / 非 retry_on 异常立即上抛
  - SceneGenerator 降级: 重试耗尽 → degraded=True + warnings 留痕 +
    模板内容含 step title; 传输层 RuntimeError 不降级原样上抛
  - OutlineGenerator 带 policy 重试
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from cogedu.presentation.json_repair import parse_llm_json
from cogedu.presentation.outline import OutlineGenerator
from cogedu.presentation.retry import RetryPolicy, call_with_retry
from cogedu.presentation.scene import SceneGenerator
from cogedu.presentation.types import GenerationContext, Outline, OutlineStep


class FlakyLLM:
    """前 fail_times 次 chat 抛 error_type, 之后返回 output."""

    def __init__(
        self,
        output: Any,
        fail_times: int = 0,
        error: Exception | None = None,
    ):
        self.output = output
        self.fail_times = fail_times
        self.error = error or ValueError("解析失败")
        self.calls = 0

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        if isinstance(self.output, str):
            return self.output
        return json.dumps(self.output, ensure_ascii=False)


def _ctx() -> GenerationContext:
    return GenerationContext(
        student_id="stu_001",
        intervention_id="int_x",
        goal_id="g",
        evidence_id="e",
    )


def _outline() -> Outline:
    return Outline(
        student_id="stu_001",
        intervention_id="int_x",
        goal_id="g",
        evidence_id="e",
        title="二次函数入门",
        steps=[OutlineStep(title="第一步", key_points=["kp1"])],
    )


_FAST_POLICY = RetryPolicy(max_attempts=3, backoff_seconds=0.0)

_GOOD_SCENE = {
    "title": "第一步",
    "text": "讲解正文 $x^2$。",
    "image_concept": "示意图",
}


class TestParseLlmJson:
    def test_clean_json(self):
        assert parse_llm_json('{"a": 1}') == {"a": 1}

    def test_think_block_and_fence_stripped(self):
        raw = "<think>推理过程</think>\n```json\n{\"a\": 1}\n```"
        assert parse_llm_json(raw) == {"a": 1}

    def test_repair_trailing_comma_and_single_quotes(self):
        """不合规 JSON → json-repair 修复 (1-D-1 选型验证)."""
        raw = "{'a': [1, 2,],}"
        assert parse_llm_json(raw) == {"a": [1, 2]}

    def test_repair_with_surrounding_prose(self):
        raw = '好的，以下是结果：{"title": "t", "steps": []} 请查收。'
        assert parse_llm_json(raw) == {"title": "t", "steps": []}

    def test_unrepairable_raises_with_original(self):
        with pytest.raises(ValueError, match="原始文本"):
            parse_llm_json("这完全不是 JSON @@@ ###")


class TestRetryPolicy:
    def test_defaults(self):
        p = RetryPolicy()
        assert p.max_attempts == 3
        assert p.backoff_seconds == 1.0

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("COGEDU_PRESENTATION_MAX_ATTEMPTS", "5")
        monkeypatch.setenv("COGEDU_PRESENTATION_BACKOFF_SEC", "0.5")
        p = RetryPolicy.from_env()
        assert p.max_attempts == 5
        assert p.backoff_seconds == 0.5

    def test_from_env_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("COGEDU_PRESENTATION_MAX_ATTEMPTS", "abc")
        p = RetryPolicy.from_env()
        assert p.max_attempts == 3


class TestCallWithRetry:
    def test_succeeds_after_failures(self):
        attempts = {"n": 0}

        def fn():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ValueError("bad json")
            return "ok"

        assert call_with_retry(fn, _FAST_POLICY, what="t") == "ok"
        assert attempts["n"] == 3

    def test_exhausted_raises_last(self):
        def fn():
            raise ValueError("always bad")

        with pytest.raises(ValueError, match="always bad"):
            call_with_retry(fn, _FAST_POLICY, what="t")

    def test_non_retryable_raises_immediately(self):
        calls = {"n": 0}

        def fn():
            calls["n"] += 1
            raise RuntimeError("transport down")

        with pytest.raises(RuntimeError):
            call_with_retry(fn, _FAST_POLICY, what="t")
        assert calls["n"] == 1  # 未重试


class TestSceneDegradation:
    def test_retry_then_success_not_degraded(self):
        llm = FlakyLLM(_GOOD_SCENE, fail_times=2)
        scenes = SceneGenerator(llm).generate_for_outline(
            _outline(), _ctx(), policy=_FAST_POLICY
        )
        assert len(scenes) == 1
        assert scenes[0].degraded is False
        assert scenes[0].warnings == []
        assert llm.calls == 3

    def test_retry_exhausted_degrades(self):
        """1-D-3: 重试耗尽 → degraded scene, warnings 留痕, 学生端不空白."""
        llm = FlakyLLM(_GOOD_SCENE, fail_times=99)
        scenes = SceneGenerator(llm).generate_for_outline(
            _outline(), _ctx(), policy=_FAST_POLICY
        )
        assert llm.calls == 3  # max_attempts
        assert len(scenes) == 1
        scene = scenes[0]
        assert scene.degraded is True
        assert scene.warnings and "已降级" in scene.warnings[0]
        # 模板内容引用大纲 step 信息 (不依赖失败的 LLM 输出)
        assert "第一步" in scene.blocks[0].content
        assert "kp1" in scene.blocks[0].content
        # 追溯字段不因降级丢失
        assert scene.intervention_id == "int_x"
        assert scene.evidence_id == "e"

    def test_transport_error_not_degraded(self):
        """传输层 RuntimeError 不降级 — 网络问题不该伪装成内容生成好了."""
        llm = FlakyLLM(
            _GOOD_SCENE, fail_times=99, error=RuntimeError("LLM 调用失败")
        )
        with pytest.raises(RuntimeError):
            SceneGenerator(llm).generate_for_outline(
                _outline(), _ctx(), policy=_FAST_POLICY
            )

    def test_no_policy_strict_raises(self):
        """policy=None (1-C 基线): 严格模式, 解析失败直接上抛."""
        llm = FlakyLLM(_GOOD_SCENE, fail_times=99)
        with pytest.raises(ValueError):
            SceneGenerator(llm).generate_for_outline(_outline(), _ctx())


class TestOutlineRetry:
    def test_retry_then_success(self):
        llm = FlakyLLM(
            {"title": "t", "steps": [{"title": "a"}]}, fail_times=1
        )
        outline = OutlineGenerator(llm).generate(_ctx(), policy=_FAST_POLICY)
        assert outline.title == "t"
        assert llm.calls == 2

    def test_exhausted_raises(self):
        llm = FlakyLLM(
            {"title": "t", "steps": [{"title": "a"}]}, fail_times=99
        )
        with pytest.raises(ValueError):
            OutlineGenerator(llm).generate(_ctx(), policy=_FAST_POLICY)
        assert llm.calls == 3
