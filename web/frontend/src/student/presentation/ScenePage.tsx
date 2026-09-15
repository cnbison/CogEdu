// 讲解场景页（9-D：legacy scene.js 的数据链 + 翻页 + 1-F 回写平移为 React）。
//
// 数据链：POST /outline → POST /scenes（非阻塞 202/200 复用）→ 轮询 status
// （3s；not_started 幂等重触发≤2 次）→ GET scenes。渐进渲染（§10 #10 尾）：
// generating 期间每次轮询同步拉取已落库场景列表，边生成边出页。
// 复看模式（/scene/:outlineId）：两个只读 GET，不触发生成。
//
// 安全约定（1-E-2 延续）：LLM 文本一律 textContent / createTextNode；
// innerHTML 仅限 KaTeX 渲染产物（经 formula.js renderFormulaInto）。
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  generateOutline,
  getOutline,
  getScenes,
  getStatus,
  getTiming,
  startScenes,
  postSceneEvent,
  type Outline,
  type PresentationTiming,
  type Scene,
} from "./api";
import ScenePlayer from "./ScenePlayer";
import "../scene.css";

const POLL_MS = 3000;
const MAX_RETRIGGER = 2;

// ─── 区块渲染（legacy renderTextBlock/renderImageBlock 平移）─────────────

function FormulaSpan({ tex, display }: { tex: string; display?: boolean }) {
  const ref = useRef<HTMLSpanElement | null>(null);
  useEffect(() => {
    const g = window as unknown as {
      CogEduFormula?: { renderFormulaInto(el: HTMLElement, tex: string, display: boolean): void };
    };
    if (ref.current && g.CogEduFormula) {
      g.CogEduFormula.renderFormulaInto(ref.current, tex, !!display);
    } else if (ref.current) {
      // KaTeX 未加载：等宽原文降级（与 legacy formula.js 行为一致）
      ref.current.textContent = tex;
    }
  }, [tex, display]);
  return <span ref={ref} className={display ? "formula-display" : undefined} />;
}

// $...$ 行内 / $$...$$ 独立公式；其余文本走 text node（不 innerHTML）
function TextBlock({ content }: { content: string }) {
  const re = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g;
  const paragraphs = String(content).split(/\n{2,}/);
  return (
    <>
      {paragraphs.map((para, pi) => {
        const parts = para.split(re).filter(Boolean);
        if (!parts.length) return null;
        return (
          <p key={pi}>
            {parts.map((part, ii) => {
              if (part.startsWith("$$") && part.endsWith("$$")) {
                return <FormulaSpan key={ii} display tex={part.slice(2, -2)} />;
              }
              if (part.startsWith("$") && part.endsWith("$") && part.length > 2) {
                return <FormulaSpan key={ii} tex={part.slice(1, -1)} />;
              }
              return <span key={ii}>{part}</span>;
            })}
          </p>
        );
      })}
    </>
  );
}

function ImageBlockView({ block }: { block: { url?: string | null; alt?: string } }) {
  const [failed, setFailed] = useState(false);
  return (
    <div className="scene-image">
      {block.url && !failed ? (
        <img loading="lazy" alt={block.alt || ""} src={block.url} onError={() => setFailed(true)} />
      ) : (
        <div className="img-placeholder">
          <span className="icon">🖼️</span>
          <span>配图（占位）：{block.alt || "示意图"}</span>
        </div>
      )}
    </div>
  );
}

// ─── 场景页 ─────────────────────────────────────────────────────────────

export default function ScenePage({ sid, replayOutlineId }: { sid: string; replayOutlineId?: string }) {
  const navigate = useNavigate();
  const [outline, setOutline] = useState<Outline | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [index, setIndex] = useState(0);
  const [timing, setTiming] = useState<PresentationTiming | null>(null);
  const [statusText, setStatusText] = useState("正在准备…");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const pageEnteredAt = useRef(Date.now());
  const totalDwellMs = useRef(0);
  const completedReported = useRef(false);

  // 数据链（生成 / 复看）
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        let loadedScenes: Scene[];
        let loadedOutline: Outline;
        if (replayOutlineId) {
          setStatusText("正在加载已生成的讲解…");
          loadedOutline = await getOutline(sid, replayOutlineId);
          loadedScenes = await getScenes(sid, replayOutlineId);
          if (!loadedScenes.length) {
            setErrorText("该大纲还没有已生成的场景 (生成可能未完成), 请重新点击讲解生成。");
            return;
          }
        } else {
          setStatusText("正在根据你的学习状态选择讲解内容…");
          loadedOutline = await generateOutline(sid);
          setStatusText("正在生成讲解场景…");
          let gen = await startScenes(sid, loadedOutline.outline_id);
          if (gen.status === "generating") {
            let retriggered = 0;
            for (;;) {
              await new Promise((r) => setTimeout(r, POLL_MS));
              if (cancelled) return;
              const st = await getStatus(sid, loadedOutline.outline_id);
              setStatusText(`正在生成讲解场景… ${st.generated} / ${st.total}`);
              // §10 #10 尾：渐进渲染——已落库的场景边生成边出页
              if (st.generated > 0) {
                const partial = await getScenes(sid, loadedOutline.outline_id);
                if (!cancelled && partial.length) setScenes(partial);
              }
              if (st.status === "ready") break;
              if (st.status === "not_started") {
                if (++retriggered > MAX_RETRIGGER) {
                  throw new Error("场景生成反复中断，请稍后重试");
                }
                gen = await startScenes(sid, loadedOutline.outline_id);
              }
            }
          }
          loadedScenes = await getScenes(sid, loadedOutline.outline_id);
        }
        if (cancelled) return;
        setOutline(loadedOutline);
        setScenes(loadedScenes);
        // 3-E 时间常数（失败不阻塞，模块内兜底镜像顶上——数值锁）
        try {
          setTiming(await getTiming(sid));
        } catch (e) {
          console.warn("时间常数下发失败, 使用内置兜底值:", e);
        }
        setReady(true);
      } catch (e) {
        if (!cancelled) setErrorText("讲解生成失败：" + ((e as Error)?.message ?? String(e)));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sid, replayOutlineId]);

  // 1-F：翻页即回写 scene_viewed（dwell 埋点）；最后一页回写 scene_completed
  const goNext = useCallback(() => {
    if (!outline) return;
    const dwellSec = (Date.now() - pageEnteredAt.current) / 1000;
    totalDwellMs.current += Date.now() - pageEnteredAt.current;
    void postSceneEvent(sid, outline.outline_id, "scene_viewed", {
      scene_id: scenes[index]?.scene_id,
      step_id: scenes[index]?.step_id,
      dwell_sec: Math.round(dwellSec * 10) / 10,
      index,
    });
    if (index < scenes.length - 1) {
      setIndex(index + 1);
      pageEnteredAt.current = Date.now();
    } else if (!completedReported.current) {
      completedReported.current = true;
      void postSceneEvent(sid, outline.outline_id, "scene_completed", {
        scene_count: scenes.length,
        total_dwell_sec: Math.round((totalDwellMs.current / 1000) * 10) / 10,
      });
      navigate("/"); // 回学习页（今天）
    }
  }, [outline, scenes, index, sid, navigate]);

  const goPrev = () => {
    if (index > 0) {
      setIndex(index - 1);
      pageEnteredAt.current = Date.now();
    }
  };

  if (errorText) {
    return (
      <div className="scene-view" style={{ padding: 16 }}>
        <div className="error-box">{errorText}</div>
      </div>
    );
  }
  if (!ready || !outline || !scenes.length) {
    return (
      <div className="scene-status" style={{ padding: 16 }}>
        <p className="muted">{statusText}</p>
        {scenes.length > 0 && (
          <p className="muted" style={{ fontSize: 13 }}>
            已生成 {scenes.length} 页，完成后即可从头翻阅。
          </p>
        )}
      </div>
    );
  }

  const scene = scenes[Math.min(index, scenes.length - 1)];
  const isLast = index === scenes.length - 1;

  return (
    <div className="scene-view">
      <header className="scene-head">
        <h2 id="scene-outline-title">{outline.title || "讲解"}</h2>
        <span id="scene-progress" className="muted">
          {index + 1} / {scenes.length}
        </span>
      </header>
      {scene.degraded && (
        <div id="scene-degraded-banner" className="degraded-banner">
          本场景为降级内容（生成不完整），仅供参考。
        </div>
      )}
      <div id="scene-content" className="card scene-content">
        <h3>{scene.title}</h3>
        {(scene.blocks || []).map((block, i) =>
          block.type === "text" ? (
            <TextBlock key={i} content={block.content} />
          ) : (
            <ImageBlockView key={i} block={block} />
          ),
        )}
      </div>
      <ScenePlayer scene={scene} sid={sid} timing={timing} />
      <div className="scene-pager">
        <button id="scene-prev" onClick={goPrev} disabled={index === 0}>
          ← 上一页
        </button>
        <button id="scene-next" className="green" onClick={goNext}>
          {isLast ? "完成学习 ✓" : "下一页 →"}
        </button>
      </div>
    </div>
  );
}
