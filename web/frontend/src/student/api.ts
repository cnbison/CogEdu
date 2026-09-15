// 学生端 API 客户端（移植自 ECOS v0.99.5 前端）。
// CogEdu 适配：① getJson/postJson 换共享 auth 基座（Bearer + 401 跳登录）；
// ② /api/judge 失败契约是 HTTP 422 + 结构化降级体（{judged:false, error_code,
// needs_rejudge}）而非 ECOS 的 200 内 judged:false —— 此处把 422 body 还原成
// JudgeResult，页面层逻辑（alert + 可重试）不变；③ /api/answer 返回 CogEdu
// 9 字段契约（AnswerResponse，exclude_none），页面按 persisted===false 告警。
import { ApiError, getJson, postJson } from "../shared/auth";
import type { AnswerResponse } from "./types";
import type { JudgeResult, Question, Report, StudentState } from "./types";

export function fetchState(sid: string): Promise<StudentState> {
  return getJson<StudentState>(`/api/state/${encodeURIComponent(sid)}`);
}

export function fetchReport(sid: string): Promise<Report> {
  return getJson<Report>(`/api/report/${encodeURIComponent(sid)}`);
}

export function fetchQuestion(sid: string): Promise<Question> {
  return getJson<Question>(`/api/question/${encodeURIComponent(sid)}`);
}

export interface HistoryItem {
  problem_id: string;
  correct: boolean;
  bloom_level?: string;
  user_answer?: string | null;
  correct_answer?: string | null;
  timestamp?: string | null;
}

export function fetchHistory(sid: string): Promise<{
  items: HistoryItem[];
  total: number;
  correct_rate: number;
}> {
  return getJson<{ items: HistoryItem[]; total: number; correct_rate: number }>(
    `/api/history/${encodeURIComponent(sid)}`,
  );
}

export async function judgeAnswer(body: {
  student_id: string;
  problem_id: string;
  student_answer: string;
}): Promise<JudgeResult> {
  try {
    return await postJson<JudgeResult>("/api/judge", body);
  } catch (e) {
    // 422 = LLM 判分 3 次重试后失败的结构化降级（不是传输层错误）
    if (e instanceof ApiError && e.status === 422) {
      return e.body as unknown as JudgeResult;
    }
    throw e;
  }
}

export function submitAnswer(body: {
  student_id: string;
  problem_id: string;
  skill_id: string;
  correct: boolean;
  score: number;
  bloom_layer: string;
  user_answer: string;
  correct_answer: string;
  reasoning: string;
  // 提交前自评 (4 档语义化映射, 强制无默认; 未选不允许提交)
  // 映射锚点与校准桶 0.1 宽两侧同步 (cogedu/cta/calibration_view.py)
  self_confidence: number;
  // 答题时延秒 (题目加载→提交, evidence raw_response_time)
  response_time: number;
}): Promise<AnswerResponse> {
  return postJson<AnswerResponse>("/api/answer", body);
}

// 4 行为事件 (best-effort 遥测, 失败 console.warn 不打断答题 — 不 silent pass)
// hint 端点响应体携带规则生成的提示内容
export async function emitEvent(
  kind: "hint" | "idle" | "goal_change" | "reflection",
  payload: Record<string, unknown>,
): Promise<Record<string, unknown> | undefined> {
  try {
    return await postJson(`/api/event/${kind}`, payload);
  } catch (e) {
    console.warn(`emitEvent ${kind} 失败:`, e);
    return undefined;
  }
}
