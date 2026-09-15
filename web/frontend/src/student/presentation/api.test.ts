// presentation client 契约测试：锁 URL 形状（?student_id= 查询串——router 级
// require_student_access 放行所需）与请求体形状。对应 web/api/routers/presentation.py。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  fetchAudioBlob,
  generateOutline,
  getOutline,
  getScenes,
  getStatus,
  getTiming,
  listOutlines,
  postSceneEvent,
  startScenes,
} from "./api";

const SID = "python_student_001";
const OID = "outline-9";

function stubEnv(token: string | null = "tok-p") {
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => (k === "cogedu_token" ? token : null),
    setItem: () => {},
    removeItem: () => {},
  });
  vi.stubGlobal("window", {
    localStorage: globalThis.localStorage,
    location: { pathname: "/student/", hash: "#/scene", href: "" },
  });
}

function jsonResp(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("presentation client 契约", () => {
  beforeEach(() => stubEnv());
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("generateOutline POST body 带 student_id 且附 Bearer", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResp({ outline_id: OID }));
    vi.stubGlobal("fetch", fetchMock);
    await generateOutline(SID);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/presentation/outline");
    expect(JSON.parse(init.body as string)).toEqual({ student_id: SID });
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer tok-p");
  });

  it("startScenes POST {student_id, outline_id}", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResp({ status: "generating", outline_id: OID }));
    vi.stubGlobal("fetch", fetchMock);
    const resp = await startScenes(SID, OID);
    expect(resp.status).toBe("generating");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/presentation/scenes");
    expect(JSON.parse(init.body as string)).toEqual({ student_id: SID, outline_id: OID });
  });

  it("getStatus/getScenes/getOutline/getTiming GET 带 ?student_id= 查询串", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResp({ generated: 1, total: 3, status: "ready", outline_id: OID }))
      .mockResolvedValueOnce(jsonResp([]))
      .mockResolvedValueOnce(jsonResp({ outline_id: OID }))
      .mockResolvedValueOnce(jsonResp({ wb_draw_ms: 800 }));
    vi.stubGlobal("fetch", fetchMock);
    await getStatus(SID, OID);
    await getScenes(SID, OID);
    await getOutline(SID, OID);
    await getTiming(SID);
    const urls = fetchMock.mock.calls.map((c) => c[0]);
    expect(urls[0]).toBe(`/api/presentation/scenes/${OID}/status?student_id=${SID}`);
    expect(urls[1]).toBe(`/api/presentation/scenes/${OID}?student_id=${SID}`);
    expect(urls[2]).toBe(`/api/presentation/outline/${OID}?student_id=${SID}`);
    expect(urls[3]).toBe(`/api/presentation/timing?student_id=${SID}`);
  });

  it("postSceneEvent 回写 body 形状（1-F）", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResp({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await postSceneEvent(SID, OID, "scene_viewed", { scene_id: "s1", step_id: "p1", dwell_sec: 3.5, index: 0 });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/presentation/event");
    expect(JSON.parse(init.body as string)).toEqual({
      student_id: SID,
      outline_id: OID,
      event_type: "scene_viewed",
      payload: { scene_id: "s1", step_id: "p1", dwell_sec: 3.5, index: 0 },
    });
  });

  it("listOutlines GET 带 ?student_id= 查询串", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResp({ outlines: [] }));
    vi.stubGlobal("fetch", fetchMock);
    await listOutlines(SID);
    expect(fetchMock.mock.calls[0][0]).toBe(`/api/presentation/outlines?student_id=${SID}`);
  });

  it("fetchAudioBlob 同会话缓存（第二次不重复下载）", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("mp3-bytes", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await fetchAudioBlob(SID, "a1");
    await fetchAudioBlob(SID, "a1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect((fetchMock.mock.calls[0] as unknown[])[0]).toBe(
      `/api/presentation/audio/a1?student_id=${SID}`,
    );
  });
});
