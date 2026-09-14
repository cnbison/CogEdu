/* 白板渲染组件 (Phase 3, 3-B, 方案文档 15.3) — DOM + SVG path 路线.
 *
 * 技术路线 (v0.6 已拍板): 文字/公式是 HTML (KaTeX 经 formula.js 共享模块),
 * 只有图形/线段内嵌 SVG path — OpenMAIC whiteboard-canvas.tsx 实证路线,
 * 不是"SVG vs Canvas"二选一。v1 是观众场景: 无自由绘制、无撤销/重做
 * (3-B-3 砍掉, 代之以重播本页)、无滚轮缩放, 只做自适应等比缩放。
 *
 * 架构: 本组件只实现 playback 引擎 (3-C) 的 renderer 接口
 *   { clear(), execute(action) -> Promise }
 * 调度全在引擎侧, 本组件不做任何时序。
 *
 * 坐标系统 (3-A-2): 虚拟画布 1000×562.5, 原点左上, 像素值 — 与
 * cogedu/presentation/types.py 同源 (3-E 收口后由服务端下发, 当前镜像)。
 * 缩放: 虚拟层固定尺寸 + transform scale, 字号/线宽随画布等比缩放。
 *
 * 安全约定: LLM 文本 (wb_draw_text.content) 一律 textContent 进 DOM;
 * innerHTML 仅两处合法 — scene 卡片清空与公式 (KaTeX 本地渲染产物,
 * 非 LLM 原文, trust=false 默认转义内嵌 HTML)。
 */
'use strict';

// ─── 虚拟画布常量 (与 cogedu/presentation/types.py 镜像, 3-E 收口) ─────────

var WB_VIRTUAL_WIDTH = 1000;
var WB_VIRTUAL_HEIGHT = 562.5;   // 16:9

// 元素入场动画 (3-B-4): 值对齐 OpenMAIC (450ms 入场 + 50ms 级联), 3-E 收口
var WB_TIMING_DEFAULTS = { enterMs: 450, staggerMs: 50 };

// 图形 path (OpenMAIC ActionEngine SHAPE_PATHS 同款, viewBox 0 0 1000 1000)
var WB_SHAPE_PATHS = {
  rectangle: 'M 0 0 L 1000 0 L 1000 1000 L 0 1000 Z',
  circle: 'M 500 0 A 500 500 0 1 1 499 0 Z',
  triangle: 'M 500 0 L 1000 1000 L 0 1000 Z',
};

// ─── 纯函数 (node 可测; DOM 组装在 createWhiteboard 内) ────────────────────

// 画布坐标 clamp (3-A-2 兜底: 3-F 解析侧已 clamp, 渲染侧再防御一层)
function clampCanvasPoint(x, y) {
  return [
    Math.min(Math.max(Number(x) || 0, 0), WB_VIRTUAL_WIDTH),
    Math.min(Math.max(Number(y) || 0, 0), WB_VIRTUAL_HEIGHT),
  ];
}

function shapePath(shape) {
  return Object.prototype.hasOwnProperty.call(WB_SHAPE_PATHS, shape)
    ? WB_SHAPE_PATHS[shape]
    : null;
}

// 视口宽 (px) → 缩放系数
function computeScale(viewportWidthPx) {
  return (viewportWidthPx || WB_VIRTUAL_WIDTH) / WB_VIRTUAL_WIDTH;
}

// 剥离 LLM 误加进 latex 字段的 $/$$ 定界符与杂散 $ (与服务端
// cogedu/presentation/scene.py _strip_latex_delimiters 同源——服务端
// 3-F 新数据已剥, 此处兜底覆盖已落库的旧数据)
function stripLatexDelimiters(raw) {
  var s = String(raw || '').trim();
  if (s.indexOf('$$') === 0) s = s.slice(2).replace(/^\s+/, '');
  else if (s.indexOf('$') === 0) s = s.slice(1).replace(/^\s+/, '');
  if (s.slice(-2) === '$$') s = s.slice(0, -2).replace(/\s+$/, '');
  else if (s.slice(-1) === '$') s = s.slice(0, -1).replace(/\s+$/, '');
  s = s.split('$').join('');
  return s.trim();
}

// 动作 → 元素规格 (纯数据, 不碰 DOM)。未知/非法动作返回 null (调用方跳过)。
// action 字段名为 3-A schema 的 snake_case 口径。
function elementSpec(action, index, timing) {
  if (!action || typeof action.type !== 'string') return null;
  var t = Object.assign({}, WB_TIMING_DEFAULTS, timing || {});
  var spec = {
    kind: action.type,
    index: index,
    anim: { durationMs: t.enterMs, delayMs: index * t.staggerMs },
  };

  if (action.type === 'wb_draw_text') {
    var p = clampCanvasPoint(action.x, action.y);
    spec.style = {
      left: p[0], top: p[1],
      width: action.width, fontSize: action.font_size, color: action.color,
    };
    spec.text = action.content;   // LLM 文本: 组装侧 textContent, 不 innerHTML
    return spec;
  }

  if (action.type === 'wb_draw_shape') {
    var d = shapePath(action.shape);
    if (!d) return null;          // 白名单外图形: 调用方告警跳过
    var ps = clampCanvasPoint(action.x, action.y);
    spec.style = { left: ps[0], top: ps[1], width: action.width, height: action.height };
    spec.path = d;
    spec.fill = action.fill_color;
    return spec;
  }

  if (action.type === 'wb_draw_line') {
    // 整幅虚拟画布的 SVG 覆盖层: 线段坐标即画布坐标 (两点式, 3-A-1)
    var a = clampCanvasPoint(action.x1, action.y1);
    var b = clampCanvasPoint(action.x2, action.y2);
    spec.style = { left: 0, top: 0, width: WB_VIRTUAL_WIDTH, height: WB_VIRTUAL_HEIGHT };
    spec.line = {
      x1: a[0], y1: a[1], x2: b[0], y2: b[1],
      stroke: action.color, strokeWidth: action.stroke_width,
    };
    return spec;
  }

  if (action.type === 'wb_draw_latex') {
    var pl = clampCanvasPoint(action.x, action.y);
    spec.style = { left: pl[0], top: pl[1], width: action.width, color: action.color };
    spec.latex = action.latex;    // 经 formula.js 的 KaTeX 渲染, 非 LLM 原文直插
    return spec;
  }

  return null;                    // 未知动作类型: 调用方告警跳过
}

// ─── 组件: renderer 接口实现 + 自适应缩放 ──────────────────────────────────

function createWhiteboard(container, options) {
  var opts = options || {};
  var timing = Object.assign({}, WB_TIMING_DEFAULTS, opts.timing || {});

  var viewport = document.createElement('div');
  viewport.className = 'wb-viewport';
  var stage = document.createElement('div');   // 虚拟画布层 (固定 1000×562.5)
  stage.className = 'wb-stage';
  viewport.appendChild(stage);
  container.innerHTML = '';                    // 容器清空后挂载 (每次进页重建)
  container.appendChild(viewport);

  function rescale() {
    var w = viewport.clientWidth || container.clientWidth || WB_VIRTUAL_WIDTH;
    stage.style.transform = 'scale(' + computeScale(w) + ')';
  }
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(rescale).observe(viewport);
  } else if (typeof window !== 'undefined') {
    window.addEventListener('resize', rescale);   // 老浏览器兜底
  }
  rescale();

  var count = 0;   // 已放置元素数: stagger 级联序号, clear 时重置

  function setBox(el, style) {
    el.style.left = style.left + 'px';
    el.style.top = style.top + 'px';
    if (style.width != null) el.style.width = style.width + 'px';
    if (style.height != null) el.style.height = style.height + 'px';
  }

  function setAnim(el, spec) {
    el.style.animationDuration = spec.anim.durationMs + 'ms';
    el.style.animationDelay = spec.anim.delayMs + 'ms';
  }

  function buildDom(spec) {
    var el = document.createElement('div');
    el.className = 'wb-el wb-enter';
    setAnim(el, spec);

    if (spec.kind === 'wb_draw_text') {
      el.classList.add('wb-text');
      setBox(el, spec.style);
      el.style.fontSize = (spec.style.fontSize || 18) + 'px';
      el.style.color = spec.style.color || '#333333';
      el.textContent = spec.text;              // LLM 文本: 不用 innerHTML
      return el;
    }

    if (spec.kind === 'wb_draw_shape') {
      el.classList.add('wb-shape');
      setBox(el, spec.style);
      var NS = 'http://www.w3.org/2000/svg';
      var svg = document.createElementNS(NS, 'svg');
      svg.setAttribute('viewBox', '0 0 1000 1000');
      svg.setAttribute('preserveAspectRatio', 'none');
      svg.setAttribute('width', '100%');
      svg.setAttribute('height', '100%');
      var path = document.createElementNS(NS, 'path');
      path.setAttribute('d', spec.path);
      path.setAttribute('fill', spec.fill || '#5b9bd5');
      svg.appendChild(path);
      el.appendChild(svg);
      return el;
    }

    if (spec.kind === 'wb_draw_line') {
      el.classList.add('wb-line');
      setBox(el, spec.style);                  // 整幅虚拟画布的覆盖层
      var NS2 = 'http://www.w3.org/2000/svg';
      var svg2 = document.createElementNS(NS2, 'svg');
      svg2.setAttribute('viewBox', '0 0 ' + WB_VIRTUAL_WIDTH + ' ' + WB_VIRTUAL_HEIGHT);
      svg2.setAttribute('width', '100%');
      svg2.setAttribute('height', '100%');
      var line = document.createElementNS(NS2, 'line');
      line.setAttribute('x1', spec.line.x1);
      line.setAttribute('y1', spec.line.y1);
      line.setAttribute('x2', spec.line.x2);
      line.setAttribute('y2', spec.line.y2);
      line.setAttribute('stroke', spec.line.stroke || '#333333');
      line.setAttribute('stroke-width', spec.line.strokeWidth || 2);
      line.setAttribute('stroke-linecap', 'round');
      svg2.appendChild(line);
      el.appendChild(svg2);
      return el;
    }

    // wb_draw_latex: 公式走共享 KaTeX 封装 (3-B-2 "同一能力只写一次")
    setBox(el, spec.style);
    el.style.color = spec.style.color || '#000000';
    var tex = stripLatexDelimiters(spec.latex);
    if (window.CogEduFormula) {
      window.CogEduFormula.renderFormulaInto(el, tex, true);
    } else {
      el.textContent = tex;                    // formula.js 缺失: 纯文本兜底
    }
    return el;
  }

  function clear() {
    stage.innerHTML = '';                      // stage 内容全部由本组件构建
    count = 0;
  }

  function execute(action) {
    var spec = elementSpec(action, count, timing);
    count += 1;
    if (!spec) {
      console.warn('白板跳过无效动作:', action && action.type);
      return Promise.resolve();                // 单动作失败不阻塞整场
    }
    stage.appendChild(buildDom(spec));
    return Promise.resolve();                  // DOM 插入即时返回, 节奏在引擎侧
  }

  return {
    renderer: { clear: clear, execute: execute },
    rescale: rescale,
  };
}

// ─── 导出: 浏览器 global + node (测试) 双通道 ──────────────────────────────

var CogEduWhiteboard = {
  createWhiteboard: createWhiteboard,
  elementSpec: elementSpec,
  shapePath: shapePath,
  clampCanvasPoint: clampCanvasPoint,
  computeScale: computeScale,
  stripLatexDelimiters: stripLatexDelimiters,
  WB_VIRTUAL_WIDTH: WB_VIRTUAL_WIDTH,
  WB_VIRTUAL_HEIGHT: WB_VIRTUAL_HEIGHT,
  WB_SHAPE_PATHS: WB_SHAPE_PATHS,
  WB_TIMING_DEFAULTS: WB_TIMING_DEFAULTS,
};

if (typeof window !== 'undefined') {
  window.CogEduWhiteboard = CogEduWhiteboard;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = CogEduWhiteboard;
}
