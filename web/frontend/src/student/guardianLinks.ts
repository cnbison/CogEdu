// 学生侧 guardian-links 客户端（2-A：待确认列表 / 确认 / 拒绝 / 撤销）。
// 对应 web/api/routers/guardian.py 学生侧端点；admin 可代操作（require_roles student/admin）。
import { authFetch, getJson, postJson } from "../shared/auth";
import type { GuardianLink, LinkActionResponse } from "../parent/api";

export type { GuardianLink, LinkActionResponse };

export function fetchLearnerLinks(): Promise<{ links: GuardianLink[] }> {
  return getJson<{ links: GuardianLink[] }>("/api/student/guardian-links");
}

export function confirmLink(linkId: string): Promise<LinkActionResponse> {
  return postJson<LinkActionResponse>(
    `/api/student/guardian-links/${encodeURIComponent(linkId)}/confirm`,
    {},
  );
}

export function rejectLink(linkId: string): Promise<LinkActionResponse> {
  return postJson<LinkActionResponse>(
    `/api/student/guardian-links/${encodeURIComponent(linkId)}/reject`,
    {},
  );
}

export async function revokeLearnerLink(linkId: string): Promise<LinkActionResponse> {
  const resp = await authFetch(
    `/api/student/guardian-links/${encodeURIComponent(linkId)}`,
    { method: "DELETE" },
  );
  if (!resp.ok) {
    const body = (await resp.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || `操作失败 (HTTP ${resp.status})`);
  }
  return (await resp.json()) as LinkActionResponse;
}
