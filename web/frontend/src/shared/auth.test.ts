// auth 基座行为测试（vitest，node 环境，stub 全局 localStorage/window/fetch）。
// 锁定与 legacy web/auth.js 一致的语义：Bearer 头、401 清会话跳登录、错误文案格式。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  authFetch,
  clearSession,
  currentReturnPath,
  getJson,
  getToken,
  login,
  saveSession,
  TOKEN_KEY,
  USER_KEY,
} from "./auth";

type Stored = Record<string, string>;

function stubStorage(): Stored {
  const store: Stored = {};
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => {
      store[k] = v;
    },
    removeItem: (k: string) => {
      delete store[k];
    },
  });
  return store;
}

function stubLocation(pathname = "/student/", hash = "#/growth") {
  const loc = { pathname, hash, href: `${pathname}${hash}` };
  vi.stubGlobal("window", { location: loc, localStorage: globalThis.localStorage });
  return loc;
}

const sampleUser = {
  user_id: 1,
  username: "stu01",
  role: "student" as const,
  display_name: null,
  learning_student_id: "python_student_001",
};

describe("auth 基座", () => {
  beforeEach(() => {
    stubStorage();
    stubLocation();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("saveSession/getToken/clearSession 往返", () => {
    saveSession("tok-1", sampleUser);
    expect(getToken()).toBe("tok-1");
    expect(JSON.parse(window.localStorage.getItem(USER_KEY)!).username).toBe("stu01");
    clearSession();
    expect(getToken()).toBeNull();
    expect(window.localStorage.getItem(USER_KEY)).toBeNull();
  });

  it("authFetch 附带 Bearer 头", async () => {
    saveSession("tok-2", sampleUser);
    const fetchMock = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await authFetch("/api/auth/me");
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok-2");
  });

  it("authFetch 401 → 清会话 + 跳 /login?next=（含 hash 回跳）", async () => {
    saveSession("tok-3", sampleUser);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 401 })));
    await expect(authFetch("/api/x")).rejects.toThrow(/401/);
    expect(getToken()).toBeNull();
    const next = encodeURIComponent("/student/#/growth");
    expect(window.location.href).toBe(`/login?next=${next}`);
  });

  it("getJson 非 2xx 抛 ECOS 风格错误文案", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 502 })));
    await expect(getJson("/api/presentation/outline/9")).rejects.toThrow(
      "API /api/presentation/outline/9 失败: HTTP 502",
    );
  });

  it("login 提交用户名密码并保存会话", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ token: "tok-4", expires_at: "2026-09-21T00:00:00", user: sampleUser }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const user = await login("stu01", "pw-123456");
    expect(user.username).toBe("stu01");
    expect(getToken()).toBe("tok-4");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/auth/login");
    expect(JSON.parse(init.body as string)).toEqual({ username: "stu01", password: "pw-123456" });
  });

  it("login 失败透出后端 error 文案", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "用户名或密码错误" }), { status: 401 }),
      ),
    );
    await expect(login("stu01", "bad")).rejects.toThrow("用户名或密码错误");
    expect(getToken()).toBeNull();
  });

  it("currentReturnPath = pathname + hash", () => {
    stubLocation("/parent/", "#/?student=s1");
    expect(currentReturnPath()).toBe("/parent/#/?student=s1");
  });

  it("localStorage 常量与 legacy web/auth.js 互操作（键名锁定）", () => {
    window.localStorage.setItem(TOKEN_KEY, "legacy-token");
    expect(getToken()).toBe("legacy-token");
  });
});
