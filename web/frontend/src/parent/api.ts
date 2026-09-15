// 家长端 API 客户端（移植自 ECOS v0.99.5 前端 + CogEdu 扩展）。
// CogEdu 适配：① getJson/postJson 换共享 auth 基座（Bearer + 401 跳登录）；
// ② 新增 guardian-links 授权管理（2-A：pending→active 状态机、学生确认制）
//    与 Word 报告下载（2-C：download_report 授权，撤销下一请求即失效）。
// 响应字段类型与 web/api/routers/parent.py / guardian.py 契约对齐。
import { ApiError, authFetch, getJson, postJson } from "../shared/auth";

export type PomdpStateName = "Engaged" | "Frustrated" | "Bored" | "Confused" | string;

export interface AdviceEntry {
  trigger: string;
  severity: "info" | "warning" | "attention";
  message: string;
}

export interface EngagementReport {
  student_id: string;
  current_state: PomdpStateName;
  current_state_index: number;
  recent_states: PomdpStateName[];
  evolution_count: number;
  state_changed: boolean;
  cold_start: boolean;
  advice: AdviceEntry[];
  updated_at: string;
}

export interface ParentRosterStudent {
  student_id: string;
  subject: string | null;
  grade_level: string | null;
  last_active_at: string | null;
  answered_count: number;
  correct_rate: number;
  current_state: PomdpStateName | null;
}

export interface ParentRosterResponse {
  students: ParentRosterStudent[];
}

export interface FiveDOverview {
  mastery: Record<string, number> | null;
  bloom: {
    dominant: string | null;
    confidence: number;
    levels: Record<string, number>;
  } | null;
  overall_confidence: number;
}

export interface InterventionItem {
  intervention_id: string;
  /** 对齐 Intervention.to_dict() 字段名（ECOS F-12 教训：字段名错配 UI 错位）。
   *  created_at 仅新记录有值; 历史持久化记录无此字段 → null (UI 显示 "—")。 */
  created_at?: string | null;
  intervention_type?: string;
  rationale?: string | null;
  [key: string]: unknown;
}

export interface ParentOverviewResponse {
  student_id: string;
  subject: string | null;
  engagement: EngagementReport | null;
  five_d: FiveDOverview;
  interventions: InterventionItem[];
}

export function fetchParentRoster(): Promise<ParentRosterResponse> {
  return getJson<ParentRosterResponse>("/api/parent/students");
}

export function fetchParentOverview(id: string): Promise<ParentOverviewResponse> {
  return getJson<ParentOverviewResponse>(
    `/api/parent/students/${encodeURIComponent(id)}/overview`,
  );
}

// ─── 2-C: Word 学习报告下载 ─────────────────────────────────────────────

export const REPORT_PERIODS = ["week", "month", "all"] as const;
export type ReportPeriod = (typeof REPORT_PERIODS)[number];

/** 下载 docx（guardian 须有 download_report 授权；403 = 无权/已撤销）。 */
export async function downloadStudentReport(sid: string, period: ReportPeriod): Promise<void> {
  const resp = await authFetch(
    `/api/parent/students/${encodeURIComponent(sid)}/report?period=${period}`,
  );
  if (!resp.ok) {
    const body = (await resp.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || `报告下载失败 (HTTP ${resp.status})`);
  }
  const blob = await resp.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `report_${sid}_${period}.docx`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ─── 2-A: guardian_learner_link 授权管理 ────────────────────────────────

// 权限词汇表（权威源 web/api/guardian.py GUARDIAN_PERMISSIONS）
export const GUARDIAN_PERMISSIONS: { key: string; label: string }[] = [
  { key: "view_progress", label: "查看学习进度" },
  { key: "view_evidence", label: "查看证据链细节（Phase 4）" },
  { key: "download_report", label: "下载学习报告" },
  { key: "receive_alerts", label: "接收异常预警（预留）" },
  { key: "assign_materials", label: "分配学习材料（预留）" },
];

export interface GuardianLink {
  link_id: string;
  status: "pending" | "active" | "rejected" | "revoked";
  permissions: string[];
  requested_at: string;
  guardian_username?: string | null;
  guardian_display_name?: string | null;
  learner_username?: string | null;
  learner_display_name?: string | null;
  learner_student_id?: string | null;
  [key: string]: unknown;
}

export interface LinkActionResponse {
  ok: boolean;
  link: GuardianLink;
}

export function fetchGuardianLinks(): Promise<{ links: GuardianLink[] }> {
  return getJson<{ links: GuardianLink[] }>("/api/guardian/links");
}

/** 发起绑定申请（对方须为存在且未禁用的学生账号；同对 pending/active 唯一 → 409）。 */
export function requestGuardianLink(
  learnerUsername: string,
  permissions: string[],
): Promise<LinkActionResponse> {
  return postJson<LinkActionResponse>("/api/guardian/links", {
    learner_username: learnerUsername,
    permissions,
  });
}

/** 撤回 pending 申请 / 撤销 active 授权（立即生效）。 */
export async function cancelGuardianLink(linkId: string): Promise<LinkActionResponse> {
  const resp = await authFetch(`/api/guardian/links/${encodeURIComponent(linkId)}`, {
    method: "DELETE",
  });
  if (!resp.ok) {
    const body = (await resp.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || `操作失败 (HTTP ${resp.status})`);
  }
  return (await resp.json()) as LinkActionResponse;
}

/** 授权管理操作错误的用户可读文案（400 业务规则 / 404 不存在 / 409 重复申请）。 */
export function linkErrorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  return (e as Error)?.message ?? "操作失败";
}
