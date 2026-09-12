"""12.4 (0-C): 学生端核心路由 FastAPI 迁移 — 自 Flask app.py 迁移 (最复杂的一批).

包含答题主链路 (12.4 迁移顺序的最后一项, 放最后的原因见方案文档 12.4):
  GET  /api/state/{student_id}        — 5D 信念状态
  GET  /api/question/{student_id}     — 下一道题 (探针/warmup/自适应选题)
  POST /api/judge                     — LLM 评判 (judge.py 三件套 + F-05 审计)
  POST /api/answer                    — 答题主链路 (9 字段契约, Pydantic 锁定)
  GET  /api/report/{student_id}       — 学习报告 (顺带修复 import ecos 遗留 bug)
  POST /api/intervention/{student_id} — 靶向干预 (LLM)
  GET  /api/lca_debug/{student_id}    — LCA 调试
  GET  /api/history/{student_id}      — 答题历史

迁移纪律 (docs/belief-migration-map.md 对照表 + 12.3 注记):
  - submit_answer 前的两处 engine.l2.register_item 调用在 belief.py 内部
    (DB 恢复路径 + 答题路径), 迁移不触碰 — v0.47.4 事故防线
  - /api/answer 的 9 字段响应契约由 AnswerResponse (response_model +
    exclude_none) 在框架层锁定: 多字段/少字段/改类型都会 500,
    tests/test_answer_endpoint_contract.py 在 HTTP 层再锁一遍
  - score/self_confidence/response_time 的"非数字诚实降级 + warning 留痕"
    语义必须保留 (v0.97.2/v0.99.0 拍板), 因此模型字段用 Any 而非 float —
    Pydantic 直接校验会 422 拒绝整个请求, 学生答案就丢了, 比"降级记录"
    更糟。手工解析逻辑与 Flask 版逐行一致。

patch 面约定 (测试 monkeypatch 目标):
  - web.api.routers.student.submit_answer — F-10 等测试 patch 路由层绑定
  - web.api.llm.get_llm — 单一 patch 面覆盖 belief/lca 惰性 import + 本路由
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from web.api.auth import require_student_access

from web.api import llm as llm_service
from web.api.belief import (
    _STUDENT_STATES,
    _get_or_create_student,
    get_student_state,
    submit_answer,
)
from web.api.judge import (
    _build_judge_prompt,
    _call_llm_judge_with_retry,
    _parse_judge_result,
)
from web.api.lca import get_lca_debug_info, select_intervention as lca_select
from web.api.qmatrix import (
    get_question_detail,
    normalize_problem,
    select_question_for_student,
)

_log = logging.getLogger(__name__)

router = APIRouter(
    tags=["student"],
    # 2-0-3 (14.2): 学生数据路由 — 学生本人 (路径参数或请求体的
    # student_id 与 learning_student_id 匹配) / staff 任意
    dependencies=[Depends(require_student_access)],
)


# ─── Pydantic 请求/响应模型 ──────────────────────────────────────────────────


class AnswerRequest(BaseModel):
    """POST /api/answer 请求体.

    score/self_confidence/response_time 故意用 Any: 见文件头迁移纪律
    (非数字诚实降级, 不允许 Pydantic 422 掉整份学生答案)。
    """

    student_id: str
    problem_id: str
    skill_id: str
    correct: bool
    score: Optional[Any] = None
    bloom_layer: str = "L2"
    user_answer: str = ""
    explanation_text: Optional[str] = None
    reasoning: str = ""
    correct_answer: str = ""
    self_confidence: Optional[Any] = None
    response_time: Optional[Any] = None


class AnswerResponse(BaseModel):
    """POST /api/answer 响应 — belief-migration-map.md 表 #12 的 9 字段契约.

    第 9 个字段 reasoning 是路由层回显 (v0.52.2); dual_agent 仅在
    ECOS_DUAL_AGENT_ENABLED 开启时出现 (exclude_none 时缺席)。
    """

    correct: bool
    score: float
    theta: Dict[str, float]
    misc_triggered: bool
    misc_id: str
    misc_confidence: float
    c_discount_factor: float
    persisted: bool
    reasoning: str
    dual_agent: Optional[Dict[str, Any]] = None


class JudgeRequest(BaseModel):
    student_id: str
    problem_id: str
    student_answer: str = ""


class InterventionRequest(BaseModel):
    misc_id: str = ""
    student_answer: str = ""
    problem_text: str = ""


# ─── 状态 / 选题 ────────────────────────────────────────────────────────────


@router.get("/api/state/{student_id}")
def api_get_state(student_id: str):
    """获取学生当前 5D 信念状态."""
    try:
        state = get_student_state(student_id)
        return state
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/question/{student_id}")
def api_get_question(student_id: str):
    """获取下一道题目 (探针题机制 + is_warmup + 自适应选题信息).

    v0.47.1: 兜底触发 _get_or_create_student, 保证 engine/state 已加载
    (DB → in-memory), 否则重启后选题器会重复出已答过的题。
    """
    try:
        # v0.47.1: 兜底——确保 _STUDENT_STATES[student_id] 存在
        get_student_state(student_id)

        # 获取已答题目的 ID（从 _STUDENT_STATES 历史）
        answered_ids: set[str] = set()
        if student_id in _STUDENT_STATES:
            engine = _STUDENT_STATES[student_id]["engine"]
            if (
                hasattr(engine, "_response_history")
                and student_id in engine._response_history
            ):
                # v0.49.2: response_history 改 dict 格式, 兼容老 3-tuple
                answered_ids = {
                    h["problem_id"] if isinstance(h, dict) else h[0]
                    for h in engine._response_history[student_id]
                }

        # W1: 透传 warm-up 状态 + 5D 状态给选题器
        engine = None
        state = None
        if student_id in _STUDENT_STATES:
            engine = _STUDENT_STATES[student_id]["engine"]
            state = _STUDENT_STATES[student_id]["state"]

        is_warmup = engine.is_warmup(student_id) if engine is not None else True
        theta_mean = state.theta_mean.tolist() if state is not None else None
        theta_cov_diag = (
            [float(state.theta_cov[i, i]) for i in range(5)]
            if state is not None
            else None
        )
        target_bloom = None
        if state is not None and hasattr(
            state.bloom_profile, "distance_to_next_layer"
        ):
            d = state.bloom_profile.distance_to_next_layer()
            target_bloom = d.get("next") if d.get("next") else None

        # W3: 探针题判断（最高优先级）
        should_probe = (
            engine.should_probe_now(student_id) if engine is not None else False
        )
        force_probe = should_probe
        if force_probe:
            engine.consume_probe(student_id)  # 重置 _probe_due_in

        prob = select_question_for_student(
            answered_ids=answered_ids,
            is_warmup=is_warmup,
            theta_mean=theta_mean,
            theta_cov_diag=theta_cov_diag,
            target_bloom=target_bloom,
            student_id=student_id,
            force_probe=force_probe,
        )
        if prob is None:
            return {"done": True, "message": "所有题目已完成"}

        # v0.56.0: LCA 接入 (passthrough——不改变选题行为, 仅记录干预决策)
        lca_info = None
        if state is not None:
            lca_result = lca_select(student_id, state)
            if lca_result is not None:
                lca_info = {
                    "intervention_type": lca_result.intervention.intervention_type.name,
                    "bloom_target": lca_result.bloom_target.name,
                    "clt_level": lca_result.clt_level.name,
                    "ca_stage": lca_result.ca_stage.name,
                    "expected_gain": round(lca_result.expected_gain, 3),
                    "expected_risk": round(lca_result.expected_risk, 3),
                }

        normalized = normalize_problem(prob)
        # W1: 在响应里加 is_warmup + strategy
        normalized["is_warmup"] = is_warmup
        normalized["strategy"] = prob.get("_strategy", "unknown")
        if "_warmup_group" in prob:
            normalized["warmup_group"] = prob["_warmup_group"]
        if "_adaptive_dim_star" in prob:
            normalized["adaptive_dim_star"] = prob["_adaptive_dim_star"]
        # W3: 探针题信息
        normalized["is_probe"] = force_probe
        if "_probe_dim_star" in prob:
            normalized["probe_dim_star"] = prob["_probe_dim_star"]
        # v0.56.0: LCA 决策信息 (passthrough——前端可见, 不影响题目选择)
        if lca_info is not None:
            normalized["lca_decision"] = lca_info
        return normalized
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ─── LLM 评判 ───────────────────────────────────────────────────────────────


@router.post("/api/judge")
def api_judge_answer(req: JudgeRequest):
    """LLM 充当老师，评判学生答案对错.

    v0.56.1 Bisen 原则: 失败不兜底, 3 次 retry 后显式 422, 不污染 state。
    v0.99.0 (F-05): 成功与失败路径都写 judge_audit_log (判分争议回溯)。
    """
    try:
        student_id = req.student_id
        problem_id = req.problem_id
        student_answer = (req.student_answer or "").strip()

        if not student_answer:
            return JSONResponse({"error": "答案不能为空"}, status_code=400)

        # 加载题目
        prob = get_question_detail(problem_id)
        if not prob:
            return JSONResponse({"error": "题目不存在"}, status_code=404)

        correct_answer = prob.get("correct_answer", "")
        problem_text = prob.get("problem_text", "")
        # v0.58.0: 读 partial_credit_rubric (Q 矩阵字段)
        partial_credit_rubric = prob.get("partial_credit_rubric")

        # v0.58.0: 用 _build_judge_prompt 构造 (有 rubric 时注入 4 档分)
        prompt = _build_judge_prompt(
            problem_text=problem_text,
            correct_answer=correct_answer,
            student_answer=student_answer,
            partial_credit_rubric=partial_credit_rubric,
        )

        llm = llm_service.get_llm()
        # v0.99.0 (F-05): 调用审计 (model/attempts/latency/raw_output 落库,
        # 成功与失败路径都记 — 判分争议回溯 + LLM 成本核算)
        import time as _time

        _judge_started = _time.monotonic()
        result, attempts, last_raw = _call_llm_judge_with_retry(llm, prompt)
        _judge_latency_ms = (_time.monotonic() - _judge_started) * 1000.0

        def _write_judge_audit(judged: bool, error_code: str | None) -> None:
            """审计落库 (fail-open: 写失败只 warning, 不影响判分响应)."""
            try:
                from web.api.belief import _get_db

                _get_db().save_judge_audit(
                    student_id=student_id,
                    problem_id=problem_id,
                    provider=(
                        llm.config.provider.value
                        if hasattr(llm.config.provider, "value")
                        else str(llm.config.provider)
                    ),
                    model=llm.config.model,
                    attempts=attempts,
                    latency_ms=_judge_latency_ms,
                    judged=judged,
                    error_code=error_code,
                    raw_output=last_raw,
                )
            except Exception:
                _log.warning(
                    "/api/judge: 审计落库失败 (student=%s, problem=%s)",
                    student_id, problem_id, exc_info=True,
                )

        if result is None:
            # 3 次 retry 全部失败: 显式 fail, **不污染任何 state**
            _log.warning(
                "/api/judge: LLM judge 全部 %d 次 retry 失败 (student=%s, problem=%s), "
                "返回 422 显式 fail, state 不污染",
                attempts, student_id, problem_id,
            )
            _write_judge_audit(judged=False, error_code="LLM_JUDGE_FAILED")
            return JSONResponse(
                {
                    "judged": False,
                    "error": "AI 评判服务故障，请稍后重试或跳过此题",
                    "error_code": "LLM_JUDGE_FAILED",
                    "problem_id": problem_id,
                    "student_id": student_id,
                    "retry_count": attempts,
                    "needs_rejudge": True,
                },
                status_code=422,
            )

        # v0.58.0: 用 _parse_judge_result 解析 (score 优先 correct)
        correct, score, reasoning = _parse_judge_result(result)
        # v0.99.0 (F-05): 成功路径审计落库
        _write_judge_audit(judged=True, error_code=None)
        _log.info(
            "/api/judge: LLM 评判成功 (student=%s, problem=%s, rubric=%s, "
            "score=%.2f, correct=%s)",
            student_id, problem_id, "yes" if partial_credit_rubric else "no",
            score, correct,
        )

        # v0.85.0-a: Plugin 路径 - emit judge_completed event (observability)
        # 不写 state (跟 v0.56.1 不污染 state 原则一致), 只产 event
        try:
            from cogedu.cta.event_log import LearningEvent
            from cogedu.event import get_default_bus

            event = LearningEvent.from_judge_completed(
                student_id=student_id,
                problem_id=problem_id,
                correct=correct,
                score=score,
                reasoning=reasoning,
                attempts=attempts,
                source="api_judge",
            )
            bus = get_default_bus()
            bus.publish("judge_completed", event)
        except Exception:
            _log.warning(
                "/api/judge: emit judge_completed event 失败 (sid=%s, pid=%s), "
                "judge response 仍正常返回, event 不写",
                student_id, problem_id, exc_info=True,
            )

        return {
            "judged": True,
            "problem_id": problem_id,
            "student_id": student_id,
            "correct": correct,
            "score": score,  # v0.58.0: 加 score 字段
            "reasoning": reasoning,
            "attempts": attempts,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ─── 答题主链路 ─────────────────────────────────────────────────────────────


@router.post(
    "/api/answer",
    response_model=AnswerResponse,
    response_model_exclude_none=True,  # dual_agent 关闭时不出现, 9 字段契约保持
)
def api_submit_answer(req: AnswerRequest):
    """提交答案，返回 BeliefEngine 更新结果 (v0.54.0-e partial credit 改造).

    9 字段契约由 AnswerResponse 锁定 (见类 docstring)。
    """
    try:
        student_id = req.student_id
        problem_id = req.problem_id
        correct = req.correct
        # v0.54.0-e: 接收 partial credit score 字段 (optional, 老调用方不传)
        #   优先级: score > correct (score >= 0.6 派生 correct)
        #   score 缺省时, 用 correct 派生 score (兼容老代码)
        #   非数字 fallback 到 correct 派生 (Any 字段 + 手工解析, 见文件头)
        if req.score is None:
            score = 1.0 if correct else 0.0  # 老代码兼容
        else:
            try:
                score = max(0.0, min(1.0, float(req.score)))
            except (TypeError, ValueError):
                score = 1.0 if correct else 0.0  # 非数字 fallback
        bloom_layer = req.bloom_layer
        # v0.99.0 (F-10): explanation_text 前端从不传 → 恒空 → 误解检测器
        #   21 题 0 触发. fallback 到 user_answer (学生的解释文字实际
        #   都写在这里, 如 PB-Q04 的引用语义误解解释).
        user_answer = req.user_answer  # v0.49.2
        explanation_text = req.explanation_text or user_answer
        reasoning = req.reasoning
        # v0.97.2: 提交前自评置信度 (optional, None = 未自评)
        #   非数字 → warning + 记为未自评 (诚实降级; 自评是观测数据不是 state,
        #   丢一处自评 ≠ 污染任何引擎输入, 但必须留痕不 silent)
        self_confidence = None
        if req.self_confidence is not None:
            try:
                sc = float(req.self_confidence)
            except (TypeError, ValueError):
                sc = None
                _log.warning(
                    "/api/answer: self_confidence 非数字 (%r), 记为未自评",
                    req.self_confidence,
                )
            if sc is not None and 0.0 <= sc <= 1.0:
                self_confidence = sc
        # v0.99.0 (F-09): 答题时延秒 (optional, 非数字/负数 → 0.0 + warning)
        response_time = 0.0
        if req.response_time is not None:
            try:
                response_time = max(0.0, float(req.response_time))
            except (TypeError, ValueError):
                _log.warning(
                    "/api/answer: response_time 非数字 (%r), 记为 0.0",
                    req.response_time,
                )

        result = submit_answer(
            student_id=student_id,
            problem_id=problem_id,
            skill_id=req.skill_id,
            correct=correct,
            bloom_layer=bloom_layer,
            explanation_text=explanation_text,
            user_answer=user_answer,  # v0.49.2 (v0.99.0: F-10 fallback 输入)
            correct_answer=req.correct_answer,  # v0.49.2
            # v0.52.2: AI reasoning 传给 submit_answer, 存进 response_history
            ai_reasoning=reasoning,
            # v0.54.0-e: partial credit score
            score=score,
            # v0.97.2: 提交前自评 (None = 未自评)
            self_confidence=self_confidence,
            # v0.99.0 (F-09): 答题时延落 evidence raw_response_time
            response_time_sec=response_time,
        )
        result["reasoning"] = reasoning

        # v0.56.0: LCA update (基于 updated_state + score 计算 reward)
        #   防御性: LCA 失败不影响主响应
        try:
            from web.api.lca import update_with_reward as lca_update
            from cogedu.cta.belief_state import BeliefState as _BS

            # 拿 updated_state (从 _STUDENT_STATES 读, 避免 submit_answer
            # 返回值不带 state)
            student = _STUDENT_STATES.get(student_id, {})
            updated_state_obj = student.get("state")
            if isinstance(updated_state_obj, _BS):
                lca_update(
                    student_id=student_id,
                    belief_state=updated_state_obj,
                    score=score,
                    bloom_layer=bloom_layer,
                )
        except Exception:
            _log.warning(
                "/api/answer LCA update 失败 (student=%s, problem=%s), 不影响主响应",
                student_id, problem_id, exc_info=True,
            )

        # v0.60.0: 双 Agent 互校 (CTA 假设 vs LCA 实验验证)
        #   feature flag ECOS_DUAL_AGENT_ENABLED 控制, 默认 False → 现有行为不变
        #   CLAUDE.md [6]: dual_agent 失败不污染任何 state
        try:
            from web.api.dual_agent import process_observation_for_student

            dual_result = process_observation_for_student(
                student_id=student_id,
                problem_id=problem_id,
                skill_id=req.skill_id,
                correct=correct,
                score=score,
                bloom_layer=bloom_layer,
            )
            if dual_result is not None:
                # 把 dual_agent 维度信息塞进 result, 方便前端 / 教师后台看
                result["dual_agent"] = dual_result
        except Exception:
            _log.warning(
                "/api/answer dual_agent 失败 (student=%s, problem=%s), 不影响主响应",
                student_id, problem_id, exc_info=True,
            )

        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ─── 报告 / 干预 / 调试 / 历史 ───────────────────────────────────────────────


@router.get("/api/report/{student_id}")
def api_get_report(student_id: str):
    """导出学生学习报告 (C 端接口, JSON 完整学习状态).

    12.4 顺带修复 Flask 版遗留 bug: app.py:652 `import ecos as _ecos`
    包名重命名后恒 ImportError → /api/report 一直 500。
    """
    try:
        from datetime import datetime as _dt

        import cogedu as _cogedu

        state = get_student_state(student_id)
        # 计算一些 summary
        trajectory = state.get("trajectory", [])
        answered_count = len(trajectory)
        current_bloom = state.get("bloom_profile", {}).get("dominant", "—")
        warmup_complete = not state.get("is_warmup", True)
        bloom_distance = state.get("bloom_layer_distance", {})

        # v0.47.0: 规则引擎生成自然语言解读(5D/Bloom/TC/轨迹/总评/建议)
        try:
            from web.api.interpretation import build_interpretation

            interpretation = build_interpretation(state)
        except Exception as interp_err:
            # 解读失败不阻塞主报告,降级为 None + 错误信息
            interpretation = {"error": str(interp_err)}

        report = {
            "student_id": student_id,
            "generated_at": _dt.now().isoformat(),
            "ecos_version": _cogedu.__version__,
            "summary": {
                "answered_count": answered_count,
                "current_bloom_layer": current_bloom,
                "bloom_layer_distance": bloom_distance,
                "warmup_complete": warmup_complete,
                "warmup_progress": {
                    "count": state.get("warmup_count", 0),
                    "total": state.get("warmup_total", 5),
                },
                "probe_progress": {
                    "count": state.get("probe_count", 0),
                    "interval": state.get("probe_interval", 8),
                    "due_in": state.get("probe_due_in", 0),
                },
                "overall_confidence": state.get("overall_confidence", 0.0),
                "c_discount_factor": state.get("c_discount_factor", 1.0),
            },
            "interpretation": interpretation,
            "state": state,
        }
        return report
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/intervention/{student_id}")
def api_generate_intervention(student_id: str, req: InterventionRequest):
    """生成靶向干预（LLM 充当领域专家）."""
    try:
        if not req.misc_id:
            return {"intervention": "", "type": "none"}

        # 从 misconception 库获取信息
        from cogedu.cta.content import PythonBasicsMisconceptionLibrary

        lib = PythonBasicsMisconceptionLibrary()
        entry = lib.get(req.misc_id)
        if not entry:
            return {"intervention": "", "type": "none"}

        prompt = f"""你是一位 Python 教学专家。学生的回答触发了以下 misconception：

Misconception ID: {entry.misc_id}
名称: {entry.name}
描述: {entry.description}

学生回答证据: {req.student_answer}

请生成一段针对该 misconception 的靶向干预（100-200字），要求：
1. 用学生能理解的类比或解释
2. 直接指出学生理解的错误所在
3. 给出正确的理解

干预内容："""

        llm = llm_service.get_llm()
        response = llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            strip_think=True,
        )

        return {
            "intervention": response,
            "type": "EXPLANATORY",
            "misc_id": req.misc_id,
            "misc_name": entry.name,
            "correction_strategy": entry.correction_strategy,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/lca_debug/{student_id}")
def api_lca_debug(student_id: str):
    """v0.56.0: LCA 调试接口 (教师后台 / 开发自检用)."""
    try:
        info = get_lca_debug_info(student_id)
        return info
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/history/{student_id}")
def api_get_history(student_id: str):
    """返回学生完整答题历史（按时间倒序）.

    每条 item: problem_id, correct(bool), bloom_level, user_answer,
    correct_answer, timestamp; 顶层: total, correct_rate.
    """
    try:
        student = _get_or_create_student(student_id)
        engine = student["engine"]
        history = engine._response_history.get(student_id, [])

        # 按时间倒序（老数据 timestamp=None 排最后）
        def _ts_key(h):
            ts = h.get("timestamp") if isinstance(h, dict) else None
            return ts or ""

        items = sorted(history, key=_ts_key, reverse=True)

        # 去掉内部字段 _bloom_level_enum
        clean_items = []
        for h in items:
            if isinstance(h, dict):
                clean = {k: v for k, v in h.items() if not k.startswith("_")}
            else:
                # 老 3-tuple 数据兜底
                pid, correct, bl = h
                clean = {
                    "problem_id": pid,
                    "correct": int(correct),
                    "bloom_level": str(bl.name if hasattr(bl, "name") else bl),
                    "user_answer": None,
                    "correct_answer": None,
                    "timestamp": None,
                }
            clean_items.append(clean)

        total = len(clean_items)
        correct_count = sum(1 for x in clean_items if x.get("correct"))
        correct_rate = round(correct_count / total, 4) if total else 0.0
        return {
            "items": clean_items,
            "total": total,
            "correct_rate": correct_rate,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
