// UI-R-2（设计稿 docs/ui-r-0-信息架构设计稿.md §5 D2）：讲解场景页"大纲面板"。
//
// 双栏右侧（≥1024px）：与字幕栏并排显示"本页大纲要点 / 已生成页缩略"。
// 768-1023px：折叠为抽屉（ScenePage 控制 toggle，CSS 控制位置）。
// <768px：不渲染（移动端退化形态不展示大纲面板）。
//
// 数据来源 = 渐进渲染期间 ScenePage 已落库的 scenes（边生成边出页）。
// 列表项：scene.step_id + scene.title；未生成的 step（已在大纲但未落库）
// 显示为 disabled 灰色行——避免"大纲说有但点击无反应"的死链体感。

import type { Outline, Scene } from "./api";

interface OutlinePanelProps {
  outline: Outline;
  scenes: Scene[];
  currentIndex: number;
  onJump: (index: number) => void;
}

export default function OutlinePanel({
  outline,
  scenes,
  currentIndex,
  onJump,
}: OutlinePanelProps) {
  // 大纲步数与已落库场景数取较大者——大纲可多于已生成（如生成中断）
  const totalSteps = Math.max(scenes.length, outline.steps?.length ?? scenes.length);
  // 构造大纲索引数据：每个 step = 大纲标题 + 是否已落库
  const steps =
    outline.steps && outline.steps.length
      ? outline.steps
      : scenes.map((s) => ({ step_id: s.step_id, title: s.title }));
  const byStep = new Map(scenes.map((s) => [s.step_id, s] as const));

  return (
    <nav className="outline-panel" aria-label="讲解大纲">
      <div className="outline-panel-head">
        <strong>本页大纲</strong>
        <span className="outline-panel-count">
          {scenes.length} / {totalSteps}
        </span>
      </div>
      <ol className="outline-list">
        {steps.map((step, i) => {
          const generated = byStep.has(step.step_id);
          const isCurrent = i === currentIndex;
          if (!generated) {
            return (
              <li
                key={step.step_id}
                className="outline-row disabled"
                aria-disabled="true"
                title={`第 ${i + 1} 页尚未生成（${step.step_id}）`}
              >
                <span className="outline-row-num">{i + 1}</span>
                <span className="outline-row-title">{step.title}</span>
                <span className="outline-row-soon">生成中</span>
              </li>
            );
          }
          return (
            <li key={step.step_id}>
              <button
                type="button"
                className={`outline-row${isCurrent ? " active" : ""}`}
                onClick={() => onJump(i)}
                aria-current={isCurrent ? "true" : undefined}
              >
                <span className="outline-row-num">{i + 1}</span>
                <span className="outline-row-title">{step.title}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}