/* 公式渲染共享模块 (Phase 3, 3-B-2, 方案文档 15.3) — "同一能力只写一次".
 *
 * scene 文字块 (1-E-2) 与白板公式动作 (wb_draw_latex) 共用同一个 KaTeX
 * 封装函数; 此前它是 scene.js 的私有 appendFormula, 提取为本模块后两侧
 * 引用同一份, 渲染行为不会漂移。
 *
 * KaTeX 仍是 CDN 引入 (scene.html 的 vendor TODO 未做); 未加载成功时
 * 降级为等宽原文展示, 不阻塞讲解阅读 (1-E-2 约定延续)。
 */
'use strict';

// 把 tex 渲染进容器 el。displayMode=true 为独立展示块, false 为行内。
function renderFormulaInto(el, tex, displayMode) {
  if (typeof window !== 'undefined' && window.katex) {
    const span = document.createElement('span');
    // KaTeX 输出自身生成的标记; trust 默认 false, 输入中的 HTML 会被转义
    span.innerHTML = window.katex.renderToString(tex, {
      throwOnError: false,
      displayMode: displayMode,
    });
    el.appendChild(span);
  } else {
    // CDN 加载失败的降级: 等宽原文展示 (1-E-2 注记)
    const code = document.createElement('code');
    code.className = 'formula-error';
    code.textContent = (displayMode ? '$$' : '$') + tex + (displayMode ? '$$' : '$');
    el.appendChild(code);
  }
}

const CogEduFormula = { renderFormulaInto: renderFormulaInto };

if (typeof window !== 'undefined') {
  window.CogEduFormula = CogEduFormula;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = CogEduFormula;
}
