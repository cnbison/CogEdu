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
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  generateOutline,
  getOutline,
  getScenes,
  getStatus,
  getTiming,
  listOutlines,
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

export default function ScenePage({
  sid,
  replayOutlineId: replayOutlineIdProp,
}: {
  sid: string;
  replayOutlineId?: string;
}) {
  // 复看目标优先取路由参数（/scene/:outlineId，讲解记录列表点行进入）；
  // prop 留给程序化跳转场景。
  const params = useParams();
  const replayOutlineId = replayOutlineIdProp ?? params.outlineId;
  const navigate = useNavigate();
  const [outline, setOutline] = useState<Outline | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [index, setIndex] = useState(0);
  const [timing, setTiming] = useState<PresentationTiming | null>(null);
  const [statusText, setStatusText] = useState("正在准备…");
  const [errorText, setErrorText] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  // 等待阶段提示：outline = 同步 LLM 大纲调用（最易被误认为无反应的窗口），
  // generating = 逐场景后台生成（渐进出页）
  const [phase, setPhase] = useState<"outline" | "generating">("outline");
  // 入口模式：/scene 先展示讲解记录（历史复看 + 显式生成），点按钮才开始
  // 生成——避免每次进入都静默生成新大纲重复计费（复看走 /scene/:outlineId 自动开始）
  const [started, setStarted] = useState(!!replayOutlineId);
  const records = useQuery({
    queryKey: ["presentationOutlines", sid],
    queryFn: () => listOutlines(sid),
    enabled: !started,
  });

  const pageEnteredAt = useRef(Date.now());
  const totalDwellMs = useRef(0);
  const completedReported = useRef(false);

  // 数据链（生成 / 复看）——started 后才执行
  useEffect(() => {
    if (!started) return;
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
          setPhase("outline");
          setStatusText("正在根据你的学习状态选择讲解内容…");
          loadedOutline = await generateOutline(sid);
          setPhase("generating");
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
  }, [sid, replayOutlineId, started]);

  // 1-F：翻页即回写 scene_viewed（dwell 埋点）；最后一页回写 scene_completed
  const goNext = useCallback(() => {
    if (!outline) return;
    // 渐进渲染中：末页尚未生成完时不触发完成回写
    if (!ready && index >= scenes.length - 1) return;
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
  }, [outline, scenes, index, sid, navigate, ready]);

  const goPrev = () => {
    if (index > 0) {
      setIndex(index - 1);
      pageEnteredAt.current = Date.now();
    }
  };

  // 入口页：讲解记录列表 + 显式生成按钮
  if (!started) {
    const rows = records.data?.outlines ?? [];
    return (
      <div style={{ maxWidth: 560, margin: "0 auto", padding: 16 }}>
        <div className="card">
          <h2>AI 讲解</h2>
          <button className="green" onClick={() => setStarted(true)}>
            生成新讲解
          </button>
          <p className="muted" style={{ fontSize: 13, marginTop: 10 }}>
            生成按你当前的学习状态定制，通常需要几分钟；已生成的讲解从下方记录直接复看，不会重复生成。
          </p>
          {records.isLoading && <p className="muted">正在加载讲解记录…</p>}
          {records.isError && (
            <p className="muted" style={{ color: "var(--danger, #dc2626)" }}>
              讲解记录加载失败：{(records.error as Error)?.message ?? "未知错误"}
              ——若刚更新过后端，请重启服务进程后刷新重试。
            </p>
          )}
          {records.data && rows.length > 0 && (
            <table style={{ marginTop: 14 }}>
              <thead>
                <tr>
                  <th>讲解记录</th>
                  <th>页数</th>
                  <th>日期</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => (
                  <tr
                    key={o.outline_id}
                    style={{ cursor: "pointer" }}
                    onClick={() => navigate(`/scene/${o.outline_id}`)}
                  >
                    <td>
                      <strong>{o.title || "讲解"}</strong>
                    </td>
                    <td className="muted" style={{ fontSize: 12 }}>
                      {o.scene_count > 0 ? `${o.scene_count} 页` : "未生成"}
                    </td>
                    <td className="muted" style={{ fontSize: 12 }}>
                      {o.created_at?.slice(0, 10) ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    );
  }

  if (errorText) {
    return (
      <div className="scene-view" style={{ padding: 16 }}>
        <div className="error-box">{errorText}</div>
      </div>
    );
  }
  // 渐进渲染：大纲就绪且已有落库场景即出页（后续页面生成完自动出现），
  // 不再等全部生成完——消除"黑盒等待"（§10 #10 完整形态）
  if (outline && scenes.length > 0) {
    return renderSceneView();
  }

  // 纯等待态（大纲生成中 / 首个场景未落库）：spinner + 预期时长提示，
  // 避免一行静态文字被误认为无反应（2026-09-15 人工验收反馈）
  return (
    <div className="scene-status">
      <div className="spinner" />
      <p>{statusText}</p>
      <p className="muted" style={{ fontSize: 13 }}>
        {phase === "outline"
          ? "AI 正在生成讲解大纲，通常需要 1~2 分钟，请稍候…"
          : "逐场景生成中，每个场景约 1~2 分钟；已完成的会先显示出来"}
      </p>
    </div>
  );

  function renderSceneView() {
    // 调用点已保证 outline 非空（渐进渲染分支条件）
    const o = outline!;
    const scene = scenes[Math.min(index, scenes.length - 1)];
    const isLast = index === scenes.length - 1;
    const tailGenerating = isLast && !ready;

    return (
      <div className="scene-view">
        <header className="scene-head">
        <h2 id="scene-outline-title">{o.title || "讲解"}</h2>
        <span id="scene-progress" className="muted">
          {index + 1} / {scenes.length}
        </span>
      </header>
      {!ready && (
        <p className="muted" style={{ fontSize: 13, display: "flex", alignItems: "center", gap: 8 }}>
          <span className="spinner" style={{ width: 16, height: 16, margin: 0, borderWidth: 2 }} />
          后续页面正在生成（每个约 1~2 分钟），完成后自动出现；已生成的可直接翻看。
        </p>
      )}
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
        <button
          id="scene-next"
          className="green"
          onClick={goNext}
          disabled={tailGenerating}
          title={tailGenerating ? "最后一页还在生成中" : undefined}
        >
          {tailGenerating ? "生成中…" : isLast ? "完成学习 ✓" : "下一页 →"}
        </button>
      </div>
    </div>
  );
  }
}
