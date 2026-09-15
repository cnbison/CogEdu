// 白板讲解宿主（9-D，挂载式整合——方案文档 §10.1.3 拍板）。
//
// 原则：React 只做宿主，三个 vanilla 模块原样保留：
//   web/student/formula.js（KaTeX 封装）/ playback.js（播放引擎，代数令牌
//   时序语义已验收）/ whiteboard.js（DOM+SVG renderer）。
// 本组件等价于 legacy scene.js 的 setupPlayback/togglePlay/replayPage 部分：
//   createWhiteboard(container, {timing}) + createPlaybackEngine({actions,
//   renderer, speechPlayer, timing, ...})，每页重建不跨页复用，卸载必 stop。
// 模块经 student.html <script defer> 全局注入（window.CogEduXxx），
// 缺失时退回纯翻页（console.warn，与 legacy 守卫一致）。
import { useEffect, useRef, useState } from "react";
import { fetchAudioBlob, type PresentationTiming, type Scene, type SceneAction } from "./api";

interface PlaybackEngine {
  start(): void;
  pause(): void;
  resume(): void;
  stop(): void;
  replay(): void;
  getState(): "idle" | "playing" | "paused";
}

interface WhiteboardHandle {
  renderer: { clear(): void; execute(action: SceneAction): Promise<void> };
}

// 引擎 speechPlayer 接口实现（3-D 三级路径：audio ended 驱动 → 失败回落
// 引擎内置估算计时器，字幕静音推进）。blob 下载在 presentation/api.ts。
function createSpeechPlayer(sid: string) {
  let audio: HTMLAudioElement | null = null;
  return {
    play(audioId: string): Promise<boolean> {
      return new Promise((resolve, reject) => {
        fetchAudioBlob(sid, audioId)
          .then((blob) => {
            audio = new Audio(URL.createObjectURL(blob));
            audio.onended = () => resolve(true);
            audio.onerror = () => reject(new Error("audio 播放失败"));
            audio.play().catch(() => reject(new Error("audio 起播失败")));
          })
          .catch((e) => reject(e));
      });
    },
    pause() {
      if (audio) audio.pause();
    },
    resume() {
      if (audio) audio.play().catch(() => {});
    },
    stop() {
      if (audio) {
        audio.onended = null;
        audio.onerror = null;
        audio.pause();
        audio.src = "";
        audio = null;
      }
    },
  };
}

export default function ScenePlayer({
  scene,
  sid,
  timing,
}: {
  scene: Scene;
  sid: string;
  timing: PresentationTiming | null;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<PlaybackEngine | null>(null);
  const [engine, setEngine] = useState<PlaybackEngine | null>(null);
  const [state, setState] = useState<"idle" | "playing" | "paused">("idle");
  const [started, setStarted] = useState(false);
  const [subtitle, setSubtitle] = useState("");

  const hasActions = !!(scene.actions && scene.actions.length);

  // 每页重建（3-C-4 翻页联动：卸载即 stop——令牌失效 + 音频停止）
  useEffect(() => {
    if (!hasActions) return;
    const g = window as unknown as {
      CogEduPlayback?: { createPlaybackEngine(o: Record<string, unknown>): PlaybackEngine };
      CogEduWhiteboard?: { createWhiteboard(el: HTMLElement, o?: Record<string, unknown>): WhiteboardHandle };
    };
    if (!g.CogEduPlayback || !g.CogEduWhiteboard || !containerRef.current) {
      console.warn("播放组件未加载, 本页退回纯翻页模式");
      return;
    }
    const wb = g.CogEduWhiteboard.createWhiteboard(containerRef.current, {
      timing: timing
        ? { enterMs: timing.wb_enter_ms, staggerMs: timing.wb_stagger_ms }
        : undefined,
    });
    const eng = g.CogEduPlayback.createPlaybackEngine({
      actions: scene.actions,
      renderer: wb.renderer,
      speechPlayer: createSpeechPlayer(sid),
      timing: timing
        ? {
            wbDrawMs: timing.wb_draw_ms,
            speechMinMs: timing.speech_min_ms,
            cjkMsPerChar: timing.cjk_ms_per_char,
            latinMsPerWord: timing.latin_ms_per_word,
            cjkRatioThreshold: timing.cjk_ratio_threshold,
          }
        : undefined,
      // 字幕同步（3-C-3）：speech 动作开始展示讲解词
      onActionStart: (action: { type: string; text?: string }) => {
        if (action.type === "speech") setSubtitle(action.text ?? "");
      },
      onStateChange: (s: "idle" | "playing" | "paused") => setState(s),
      onDone: () => setState(eng.getState()),
    });
    engineRef.current = eng;
    setEngine(eng);
    setState("idle");
    setStarted(false);
    setSubtitle("");
    return () => {
      eng.stop(); // 代数令牌失效 + 音频停止（tests/js/playback.test.cjs 锁语义）
      engineRef.current = null;
      setEngine(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene.scene_id]);

  if (!hasActions) return null;

  const togglePlay = () => {
    const eng = engineRef.current;
    if (!eng) return;
    const s = eng.getState();
    if (s === "idle") {
      setStarted(true);
      eng.start();
    } else if (s === "playing") {
      eng.pause();
    } else if (s === "paused") {
      eng.resume();
    }
    setState(eng.getState());
  };

  const replayPage = () => {
    engineRef.current?.replay(); // stop + start + renderer.clear（3-C 确定性重放）
  };

  return (
    <div className="wb-section" id="wb-section">
      <div className="wb-controls">
        <button id="wb-play" onClick={togglePlay}>
          {state === "playing" ? "⏸ 暂停" : state === "paused" ? "▶ 继续播放" : started ? "▶ 重新播放" : "▶ 播放讲解"}
        </button>
        {/* 重播按钮：开播过才出现（3-B-3：重播是唯一的"再来一遍"） */}
        {started && (
          <button id="wb-replay" className="amber" onClick={replayPage}>
            ↻ 重播本页
          </button>
        )}
      </div>
      <div id="wb-container" ref={containerRef} className="wb-container" />
      {subtitle ? (
        <div id="wb-subtitle" className="wb-subtitle">
          {subtitle}
        </div>
      ) : null}
      {engine === null && (
        <p className="muted" style={{ fontSize: 13 }}>
          播放组件不可用，本页以纯翻页展示（内容不受影响）。
        </p>
      )}
    </div>
  );
}
