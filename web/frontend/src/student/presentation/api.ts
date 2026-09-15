// presentation 域客户端（对应 web/api/routers/presentation.py，Phase 1/3 契约）。
// 语义与 legacy web/student/scene.js 平移一致：
//   - router 级 require_student_access：GET 一律带 ?student_id= 查询串，POST 带 body student_id
//   - POST /scenes 非阻塞：已有落库场景 → 200 {status:"ready"}（结果复用）；否则 202 generating
//   - GET /scenes/{id}/status 三态 ready/generating/not_started（not_started 幂等重触发）
//   - 复看走两个只读 GET（outline/{id} + scenes/{id}），不触发生成
import { authFetch, getJson, postJson } from "../../shared/auth";

export interface OutlineStep {
  step_id: string;
  title: string;
  key_points: string[];
  objective?: string | null;
}

export interface Outline {
  outline_id: string;
  student_id: string;
  title: string;
  steps: OutlineStep[];
  schema_version: number;
}

export interface SceneBlockText {
  type: "text";
  content: string;
}

export interface SceneBlockImage {
  type: "image";
  url?: string | null;
  alt?: string;
}

export type SceneBlock = SceneBlockText | SceneBlockImage;

// 动作序列（Phase 3, 3-A v2 schema）：白板动作 union + speech。
// 渲染细节由 whiteboard.js/playback.js 消费，前端只透传。
export interface SceneAction {
  type: string;
  action_id?: string;
  [key: string]: unknown;
}

export interface Scene {
  scene_id: string;
  outline_id: string;
  step_id: string;
  student_id: string;
  title: string;
  blocks: SceneBlock[];
  actions?: SceneAction[] | null;
  degraded?: boolean;
}

export interface GenerationStatus {
  outline_id: string;
  generated: number;
  total: number;
  status: "ready" | "generating" | "not_started";
}

// 3-E 时间常数（权威源 cogedu/presentation/timing.py；snake_case 7 字段）
export interface PresentationTiming {
  wb_draw_ms: number;
  wb_enter_ms: number;
  wb_stagger_ms: number;
  speech_min_ms: number;
  cjk_ms_per_char: number;
  latin_ms_per_word: number;
  cjk_ratio_threshold: number;
}

export function generateOutline(sid: string): Promise<Outline> {
  return postJson<Outline>("/api/presentation/outline", { student_id: sid });
}

// 讲解记录（大纲列表，GET /outlines —— 学生本人 ?student_id= 放行）
export interface OutlineSummary {
  outline_id: string;
  title: string;
  created_at: string;
  scene_count: number;
}

export function listOutlines(sid: string): Promise<{ outlines: OutlineSummary[] }> {
  return getJson<{ outlines: OutlineSummary[] }>(
    `/api/presentation/outlines?student_id=${encodeURIComponent(sid)}`,
  );
}

export interface StartScenesResponse {
  status: "ready" | "generating";
  outline_id: string;
  scene_count?: number;
}

export function startScenes(sid: string, outlineId: string): Promise<StartScenesResponse> {
  return postJson<StartScenesResponse>("/api/presentation/scenes", {
    student_id: sid,
    outline_id: outlineId,
  });
}

export function getStatus(sid: string, outlineId: string): Promise<GenerationStatus> {
  return getJson<GenerationStatus>(
    `/api/presentation/scenes/${encodeURIComponent(outlineId)}/status?student_id=${encodeURIComponent(sid)}`,
  );
}

export function getScenes(sid: string, outlineId: string): Promise<Scene[]> {
  return getJson<Scene[]>(
    `/api/presentation/scenes/${encodeURIComponent(outlineId)}?student_id=${encodeURIComponent(sid)}`,
  );
}

export function getOutline(sid: string, outlineId: string): Promise<Outline> {
  return getJson<Outline>(
    `/api/presentation/outline/${encodeURIComponent(outlineId)}?student_id=${encodeURIComponent(sid)}`,
  );
}

export function getTiming(sid: string): Promise<PresentationTiming> {
  return getJson<PresentationTiming>(
    `/api/presentation/timing?student_id=${encodeURIComponent(sid)}`,
  );
}

// 1-F 行为回写：scene_viewed / scene_completed（其余类型 400）。
// best-effort（失败 console.warn 不阻塞翻页）；keepalive 保证最后一页跳转前送达。
export async function postSceneEvent(
  sid: string,
  outlineId: string,
  eventType: "scene_viewed" | "scene_completed",
  payload: Record<string, unknown>,
): Promise<void> {
  try {
    await authFetch("/api/presentation/event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        student_id: sid,
        outline_id: outlineId,
        event_type: eventType,
        payload,
      }),
      keepalive: true,
    });
  } catch (e) {
    console.warn("场景行为事件发送失败:", e);
  }
}

// ─── 音频（3-D）────────────────────────────────────────────────────────
// GET /audio/{id}（服务端按音频归属权威校验）；blob 会话内缓存：
// 重播/回看不重复下载。放在模块级使翻页/重建引擎仍复用。
const blobCache = new Map<string, Blob>();

export async function fetchAudioBlob(sid: string, audioId: string): Promise<Blob> {
  const cached = blobCache.get(audioId);
  if (cached) return cached;
  const resp = await authFetch(
    `/api/presentation/audio/${encodeURIComponent(audioId)}?student_id=${encodeURIComponent(sid)}`,
  );
  if (!resp.ok) throw new Error(`audio HTTP ${resp.status}`);
  const blob = await resp.blob();
  blobCache.set(audioId, blob);
  return blob;
}
