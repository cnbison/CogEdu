/* 3-B 白板组件纯函数测试 (node:test, 零依赖).
 *
 * 白板的 DOM 组装不做单测 (node 无 DOM) — 行为由 3-G 灰度人工复核 +
 * pytest grep 契约锁接线; 本文件锁定纯逻辑: 坐标 clamp / 图形 path /
 * 缩放计算 / 动作→元素规格映射 (含越界 clamp 与非法动作拒绝)。
 * 运行: node --test tests/js/ (由 tests/test_playback_engine_js.py 一并包装)
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const {
  elementSpec,
  shapePath,
  clampCanvasPoint,
  computeScale,
  stripLatexDelimiters,
  WB_VIRTUAL_WIDTH,
  WB_VIRTUAL_HEIGHT,
  WB_SHAPE_PATHS,
} = require('../../web/student/whiteboard.js');

test('虚拟画布常量与 types.py 镜像一致', () => {
  assert.strictEqual(WB_VIRTUAL_WIDTH, 1000);
  assert.strictEqual(WB_VIRTUAL_HEIGHT, 562.5);   // 16:9
});

test('clampCanvasPoint: 越界收进画布 (3-A-2 渲染侧兜底)', () => {
  assert.deepStrictEqual(clampCanvasPoint(500, 281.25), [500, 281.25]);
  assert.deepStrictEqual(clampCanvasPoint(-10, 200), [0, 200]);
  assert.deepStrictEqual(clampCanvasPoint(1500, 200), [1000, 200]);
  assert.deepStrictEqual(clampCanvasPoint(500, 900), [500, 562.5]);
  assert.deepStrictEqual(clampCanvasPoint(NaN, undefined), [0, 0]);  // 非数值兜底
});

test('shapePath: 三种图形, 白名单外返回 null', () => {
  assert.strictEqual(shapePath('rectangle'), WB_SHAPE_PATHS.rectangle);
  assert.strictEqual(shapePath('circle'), WB_SHAPE_PATHS.circle);
  assert.strictEqual(shapePath('triangle'), WB_SHAPE_PATHS.triangle);
  assert.strictEqual(shapePath('star'), null);
});

test('computeScale: 视口宽 → 等比系数', () => {
  assert.strictEqual(computeScale(500), 0.5);
  assert.strictEqual(computeScale(1000), 1);
  assert.strictEqual(computeScale(0), 1);          // 未布局时兜底 1:1
});

test('elementSpec: wb_draw_text 映射位置/字号/颜色 + 级联动画序号', () => {
  // 字段为服务端 schema 序列化后的形态 (默认值由 Pydantic 填充, JS 不镜像)
  const spec = elementSpec(
    { type: 'wb_draw_text', content: '勾股定理', x: 100, y: 200,
      width: 400, font_size: 18, color: '#333333' },
    2,
  );
  assert.strictEqual(spec.kind, 'wb_draw_text');
  assert.strictEqual(spec.text, '勾股定理');
  assert.strictEqual(spec.style.left, 100);
  assert.strictEqual(spec.style.top, 200);
  assert.strictEqual(spec.style.width, 400);
  assert.strictEqual(spec.style.fontSize, 18);
  assert.strictEqual(spec.style.color, '#333333');
  assert.strictEqual(spec.anim.delayMs, 100);      // index*50 stagger (3-B-4)
  assert.strictEqual(spec.anim.durationMs, 450);
});

test('elementSpec: 越界坐标 clamp 进画布', () => {
  const spec = elementSpec(
    { type: 'wb_draw_text', content: 'x', x: 1500, y: -10 }, 0,
  );
  assert.strictEqual(spec.style.left, 1000);
  assert.strictEqual(spec.style.top, 0);
});

test('elementSpec: wb_draw_shape 携带 path 与填充色; 非法图形拒绝', () => {
  const spec = elementSpec(
    { type: 'wb_draw_shape', shape: 'triangle', x: 0, y: 0, fill_color: '#ff0000' }, 0,
  );
  assert.strictEqual(spec.path, WB_SHAPE_PATHS.triangle);
  assert.strictEqual(spec.fill, '#ff0000');
  assert.strictEqual(
    elementSpec({ type: 'wb_draw_shape', shape: 'star', x: 0, y: 0 }, 0),
    null,
  );
});

test('elementSpec: wb_draw_line 为整幅画布覆盖层 + 端点 clamp', () => {
  const spec = elementSpec(
    { type: 'wb_draw_line', x1: -5, y1: 500, x2: 1200, y2: 500, stroke_width: 3 }, 1,
  );
  assert.strictEqual(spec.style.left, 0);
  assert.strictEqual(spec.style.width, WB_VIRTUAL_WIDTH);
  assert.strictEqual(spec.style.height, WB_VIRTUAL_HEIGHT);
  assert.deepStrictEqual(
    [spec.line.x1, spec.line.y1, spec.line.x2, spec.line.y2],
    [0, 500, 1000, 500],
  );
  assert.strictEqual(spec.line.strokeWidth, 3);
});

test('elementSpec: wb_draw_latex 携带公式串与颜色', () => {
  const spec = elementSpec(
    { type: 'wb_draw_latex', latex: '$a^2+b^2=c^2$', x: 50, y: 60,
      width: 400, color: '#000000' }, 0,
  );
  assert.strictEqual(spec.latex, '$a^2+b^2=c^2$');
  assert.strictEqual(spec.style.color, '#000000');
});

test('elementSpec: 未知动作类型 / 缺 type 拒绝 (null, 调用方跳过)', () => {
  assert.strictEqual(elementSpec({ type: 'spotlight', x: 1, y: 1 }, 0), null);
  assert.strictEqual(elementSpec({ content: 'no type' }, 0), null);
  assert.strictEqual(elementSpec(null, 0), null);
});

// ─── latex 定界符剥离 (渲染侧兜底, 覆盖已落库旧数据; 与 scene.py 同源) ──────

test('stripLatexDelimiters: 单 $ / 双 $$ / 中文混入 / 杂散 $', () => {
  assert.strictEqual(stripLatexDelimiters('$+5^{\\circ}\\text{C}$（零上）'),
                     '+5^{\\circ}\\text{C}（零上）');
  assert.strictEqual(stripLatexDelimiters('$$x^2$$'), 'x^2');
  assert.strictEqual(stripLatexDelimiters('$-100$ 元（收入）'), '-100 元（收入）');
  assert.strictEqual(stripLatexDelimiters('x^2'), 'x^2');           // 干净的不动
  assert.strictEqual(stripLatexDelimiters(''), '');
  assert.strictEqual(stripLatexDelimiters(null), '');
});
