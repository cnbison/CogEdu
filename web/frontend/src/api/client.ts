// Teacher API 客户端（移植自 ECOS v0.99.5 前端，端点与 web/api/routers/teacher.py 1:1）。
// 适配：getJson 换用 CogEdu 共享 auth 基座（Bearer 头 + 401 跳登录），其余契约不变。
import { getJson } from "../shared/auth";
import type {
  CalibrationResponse,
  DiagnosticResponse,
  EvidenceResponse,
  InterventionsResponse,
  MisconceptionsResponse,
  RosterResponse,
  StudentDetail,
} from "./types";

export function fetchRoster(): Promise<RosterResponse> {
  return getJson<RosterResponse>("/api/teacher/students");
}

export function fetchStudentDetail(id: string): Promise<StudentDetail> {
  return getJson<StudentDetail>(`/api/teacher/students/${encodeURIComponent(id)}`);
}

export function fetchEvidence(id: string): Promise<EvidenceResponse> {
  return getJson<EvidenceResponse>(`/api/teacher/students/${encodeURIComponent(id)}/evidence`);
}

export function fetchDiagnostic(id: string): Promise<DiagnosticResponse> {
  return getJson<DiagnosticResponse>(`/api/teacher/students/${encodeURIComponent(id)}/diagnostic`);
}

export function fetchInterventions(id: string): Promise<InterventionsResponse> {
  return getJson<InterventionsResponse>(`/api/teacher/students/${encodeURIComponent(id)}/interventions`);
}

export function fetchCalibration(id: string): Promise<CalibrationResponse> {
  return getJson<CalibrationResponse>(`/api/teacher/students/${encodeURIComponent(id)}/calibration`);
}

export function fetchMisconceptions(id: string): Promise<MisconceptionsResponse> {
  return getJson<MisconceptionsResponse>(`/api/teacher/students/${encodeURIComponent(id)}/misconceptions`);
}

// 供 vitest 校验的端点契约 (跟 teacher.py 路由逐条对应)
export const TEACHER_ENDPOINTS = {
  roster: "/api/teacher/students",
  student: (id: string) => `/api/teacher/students/${id}`,
  evidence: (id: string) => `/api/teacher/students/${id}/evidence`,
  diagnostic: (id: string) => `/api/teacher/students/${id}/diagnostic`,
  interventions: (id: string) => `/api/teacher/students/${id}/interventions`,
  calibration: (id: string) => `/api/teacher/students/${id}/calibration`,
  misconceptions: (id: string) => `/api/teacher/students/${id}/misconceptions`,
} as const;
