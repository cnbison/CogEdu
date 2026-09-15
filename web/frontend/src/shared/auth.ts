// 9-B 认证与 API 基座：CogEdu 自建认证（Bearer + 服务端会话）的前端对接层。
//
// 语义必须与 legacy web/auth.js（authFetch/requireLogin）一致：
//   - token 存 localStorage["cogedu_token"]，user 存 localStorage["cogedu_user"]（两栈互操作）
//   - 每请求带 Authorization: Bearer <token>
//   - 401 → 清会话 + 跳 /login?next=<当前路径>（服务端会话可撤销，撤销下一请求即失效）
//   - next 白名单由 login 页保证（只接受 "/" 开头的站内路径）
// 契约锁定：tests/test_auth_api.py（login/me/logout 契约 + 前端接线锁）。
// API base 恒为同源相对路径 /api（无 CORS 中间件；grep 锁禁止写死主机名）。

export const TOKEN_KEY = "cogedu_token";
export const USER_KEY = "cogedu_user";

export type UserRole = "guardian" | "student" | "teacher" | "admin";

export interface PublicUser {
  user_id: number;
  username: string;
  role: UserRole;
  display_name: string | null;
  learning_student_id: string | null;
}

interface LoginResponse {
  token: string;
  expires_at: string;
  user: PublicUser;
}

interface MeResponse {
  user: PublicUser;
}

export function getToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getCachedUser(): PublicUser | null {
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PublicUser;
  } catch {
    // 缓存损坏按未登录处理，不静默保留坏数据
    return null;
  }
}

export function saveSession(token: string, user: PublicUser): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

/** 登录后按角色回首页（与 login.html homeOf 一致）。 */
export function homePathOf(role: UserRole): string {
  if (role === "student") return "/student/";
  if (role === "guardian") return "/parent/";
  return "/teacher/";
}

/** 当前页的站内回跳路径（含 HashRouter 的 hash 部分），供 /login?next= 用。 */
export function currentReturnPath(): string {
  return window.location.pathname + window.location.hash;
}

function navigate(url: string): void {
  window.location.href = url;
}

function redirectToLogin(): void {
  navigate(`/login?next=${encodeURIComponent(currentReturnPath())}`);
}

/**
 * 统一请求入口：自动附 Bearer 头；401 → 清会话 + 跳登录页。
 * 返回原始 Response（JSON 解析交给上层 helper，便于非 JSON 响应场景）。
 */
export async function authFetch(url: string, opts: RequestInit = {}): Promise<Response> {
  const headers = new Headers(opts.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(url, { ...opts, headers });
  if (resp.status === 401) {
    clearSession();
    redirectToLogin();
    throw new Error(`API ${url} 失败: HTTP 401（会话失效，已跳转登录）`);
  }
  return resp;
}

/** 非 2xx 错误：message 保持 ECOS 风格文案，另带 status/body 供端点级降级契约用（如 judge 422）。 */
export class ApiError extends Error {
  status: number;
  body: Record<string, unknown>;

  constructor(path: string, status: number, body: Record<string, unknown>) {
    const serverMsg = typeof body.error === "string" ? body.error : "";
    super(serverMsg || `API ${path} 失败: HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const resp = await authFetch(path, { headers: { Accept: "application/json" } });
  if (!resp.ok) throw new ApiError(path, resp.status, await resp.json().catch(() => ({})));
  return (await resp.json()) as T;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await authFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new ApiError(path, resp.status, await resp.json().catch(() => ({})));
  return (await resp.json()) as T;
}

/** 登录（POST /api/auth/login）。失败抛错（HTTP 401 → 后端统一 error 文案）。 */
export async function login(username: string, password: string): Promise<PublicUser> {
  const resp = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    const body = (await resp.json().catch(() => ({}))) as { error?: string };
    throw new Error(body.error || `登录失败 (HTTP ${resp.status})`);
  }
  const data = (await resp.json()) as LoginResponse;
  saveSession(data.token, data.user);
  return data.user;
}

/** 登出：先撤销服务端会话（best-effort），无论成败都清本地。 */
export async function logout(): Promise<void> {
  try {
    await postJson("/api/auth/logout", {});
  } catch (e) {
    console.warn("logout 请求失败（本地会话仍清除）:", e);
  }
  clearSession();
  navigate("/login");
}

/** 服务端会话校验（不只信本地缓存，与 legacy requireLogin 语义一致）。 */
export async function fetchSession(): Promise<PublicUser> {
  const data = await getJson<MeResponse>("/api/auth/me");
  return data.user;
}
