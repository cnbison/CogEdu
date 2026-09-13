/* 3-C 播放引擎时序正确性测试 (node:test, 零依赖).
 *
 * 运行: node --test tests/js/
 * 由 tests/test_playback_engine_js.py 包装进 pytest (无 node 则 skip,
 * 对齐 PG 集成测试的 skip 惯例) — pre-push 的 pytest 是唯一质量门禁。
 *
 * 覆盖 (方案文档 15.4 / 15.8 3-G "时序逻辑不出错"):
 *   - 乱序防护: 动作严格按数组顺序执行
 *   - 时间重叠防护: WB_DRAW_MS 节奏等待期间不推进下一动作
 *   - 代数令牌: stop/replay 后旧定时器回调全部失效
 *   - 暂停/恢复: 剩余时间语义 (不重过头、不跳动作)
 *   - 语音三级路径: 音频 ended 优先 / 播放失败估算兜底 / 无 audio_id 估算
 *   - 重播本页: renderer.clear + 从头重放
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const {
  createPlaybackEngine,
  estimateSpeechDurationMs,
  PLAYBACK_TIMING_DEFAULTS,
} = require('../../web/student/playback.js');

// ─── 测试基建: FakeClock 手动时钟 + 微任务冲洗 ──────────────────────────────

class FakeClock {
  constructor() {
    this._now = 0;
    this._seq = 0;
    this._timers = new Map();
  }
  now() { return this._now; }
  setTimeout(fn, ms) {
    const id = ++this._seq;
    this._timers.set(id, { fn, at: this._now + Math.max(0, ms) });
    return id;
  }
  clearTimeout(id) { this._timers.delete(id); }
  // 推进时钟, 按到期顺序触发所有 due 定时器
  advance(ms) {
    const target = this._now + ms;
    for (;;) {
      let bestId = null;
      let bestAt = Infinity;
      for (const [id, t] of this._timers) {
        if (t.at < bestAt) { bestAt = t.at; bestId = id; }
      }
      if (bestId === null || bestAt > target) break;
      this._now = bestAt;
      const t = this._timers.get(bestId);
      this._timers.delete(bestId);
      t.fn();
    }
    this._now = target;
  }
  pendingCount() { return this._timers.size; }
}

// 冲洗微任务 (renderer promise 的 .then 续点)
const flush = () => new Promise((resolve) => setImmediate(resolve));

// 手动 resolve 的 promise (模拟音频 ended 时机)
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function makeRenderer() {
  const state = { clearCount: 0, executed: [] };
  return {
    state,
    clear() { state.clearCount += 1; },
    execute(action) { state.executed.push(action.content || action.type); return Promise.resolve(); },
  };
}

function makeSpeech() {
  const state = { playCalls: [], pauseCalls: 0, resumeCalls: 0, stopCalls: 0 };
  let current = deferred();
  return {
    state,
    get next() { return current; },  // getter: play() 重赋值后测试仍拿得到在途 deferred
    play(audioId) { state.playCalls.push(audioId); current = deferred(); return current.promise; },
    pause() { state.pauseCalls += 1; },
    resume() { state.resumeCalls += 1; },
    stop() { state.stopCalls += 1; current.resolve(false); },
  };
}

function wbText(content) {
  return { type: 'wb_draw_text', content, x: 100, y: 100 };
}

// ─── 状态机与顺序 ──────────────────────────────────────────────────────────

test('wb 动作严格按序执行, WB_DRAW_MS 间隔内不推进 (防乱序/防重叠)', async () => {
  const clock = new FakeClock();
  const renderer = makeRenderer();
  const starts = [];
  let doneCount = 0;
  const engine = createPlaybackEngine({
    actions: [wbText('a'), wbText('b'), wbText('c')],
    renderer,
    scheduler: clock,
    now: () => clock.now(),
    onActionStart: (a, i) => starts.push(i),
    onDone: () => { doneCount += 1; },
  });

  assert.strictEqual(engine.getState(), 'idle');
  engine.start();
  await flush();
  assert.strictEqual(engine.getState(), 'playing');
  assert.deepStrictEqual(renderer.state.executed, ['a']);       // 只执行第一个
  assert.deepStrictEqual(starts, [0]);

  clock.advance(PLAYBACK_TIMING_DEFAULTS.wbDrawMs - 1);          // 差 1ms
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a']);        // 不推进

  clock.advance(1);                                              // 到点
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a', 'b']);
  assert.deepStrictEqual(starts, [0, 1]);

  clock.advance(PLAYBACK_TIMING_DEFAULTS.wbDrawMs);
  await flush();
  clock.advance(PLAYBACK_TIMING_DEFAULTS.wbDrawMs);
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a', 'b', 'c']);
  assert.strictEqual(engine.getState(), 'idle');                 // 播完回 idle
  assert.strictEqual(doneCount, 1);
});

test('空动作列表: start 直接 onDone, 不进入 playing (Phase 1 纯翻页场景)', () => {
  let doneCount = 0;
  const engine = createPlaybackEngine({
    actions: null,
    onDone: () => { doneCount += 1; },
  });
  engine.start();
  assert.strictEqual(engine.getState(), 'idle');
  assert.strictEqual(doneCount, 1);
});

// ─── 代数令牌: stop/replay 后旧回调失效 ────────────────────────────────────

test('stop 后旧定时器回调失效: 不推进、不触发 onDone (防"暂停后旧 timeout 又画图")', async () => {
  const clock = new FakeClock();
  const renderer = makeRenderer();
  let doneCount = 0;
  const engine = createPlaybackEngine({
    actions: [wbText('a'), wbText('b')],
    renderer,
    scheduler: clock,
    now: () => clock.now(),
    onDone: () => { doneCount += 1; },
  });
  engine.start();
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a']);

  engine.stop();                                                 // 令牌失效
  assert.strictEqual(engine.getState(), 'idle');
  clock.advance(60_000);                                         // 旧 wait 到点
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a']);        // 不推进
  assert.strictEqual(doneCount, 0);                              // 不误报完成
  assert.strictEqual(clock.pendingCount(), 0);                   // 无残留定时器
});

test('replay = 清空白板 + 从头重放, 旧一轮回调失效', async () => {
  const clock = new FakeClock();
  const renderer = makeRenderer();
  const engine = createPlaybackEngine({
    actions: [wbText('a'), wbText('b')],
    renderer,
    scheduler: clock,
    now: () => clock.now(),
  });
  engine.start();
  await flush();
  clock.advance(PLAYBACK_TIMING_DEFAULTS.wbDrawMs);
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a', 'b']);
  const clearsAfterFirstRun = renderer.state.clearCount;

  engine.replay();                                               // 重播本页
  await flush();
  assert.strictEqual(renderer.state.clearCount, clearsAfterFirstRun + 1);
  assert.deepStrictEqual(renderer.state.executed, ['a', 'b', 'a']); // 从头
  clock.advance(PLAYBACK_TIMING_DEFAULTS.wbDrawMs);
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a', 'b', 'a', 'b']);
});

// ─── 暂停/恢复: 剩余时间语义 ────────────────────────────────────────────────

test('暂停保持剩余时间: 暂停期间不推进, 恢复后补完剩余再推进', async () => {
  const clock = new FakeClock();
  const renderer = makeRenderer();
  const engine = createPlaybackEngine({
    actions: [wbText('a'), wbText('b')],
    renderer,
    scheduler: clock,
    now: () => clock.now(),
  });
  engine.start();
  await flush();
  clock.advance(300);                                            // 800ms 等待走了 300
  engine.pause();
  assert.strictEqual(engine.getState(), 'paused');

  clock.advance(60_000);                                         // 暂停期间时间流逝
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a']);        // 不推进

  engine.resume();
  assert.strictEqual(engine.getState(), 'playing');
  clock.advance(499);                                            // 剩余 500-1
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a']);
  clock.advance(1);                                              // 补完剩余
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a', 'b']);   // 不从头重放
});

test('暂停落在 execute 在途窗口时, 恢复后补推进不卡死', async () => {
  const clock = new FakeClock();
  // execute 返回手动控制 promise (模拟渲染动画在途)
  const gates = [];
  const renderer = {
    clear() {},
    execute() { const d = deferred(); gates.push(d); return d.promise; },
  };
  const engine = createPlaybackEngine({
    actions: [wbText('a'), wbText('b')],
    renderer,
    scheduler: clock,
    now: () => clock.now(),
  });
  engine.start();
  await flush();
  assert.strictEqual(gates.length, 1);

  engine.pause();           // execute promise 还没 resolve
  gates[0].resolve();       // 在暂停期间 resolve (续点被 valid() 丢弃)
  await flush();
  clock.advance(60_000);
  assert.deepStrictEqual(gates.length, 1);                       // 暂停中不推进

  engine.resume();          // 补 0 等待推进, 不重播已完成的动作 a
  await flush();
  clock.advance(0);
  await flush();
  assert.strictEqual(gates.length, 2);                           // 进入动作 b
  assert.strictEqual(engine.getState(), 'playing');
});

// ─── 语音三级路径 (3-C-3) ──────────────────────────────────────────────────

test('无 audio_id 的 speech: 估算计时器驱动, 不触碰 speechPlayer', async () => {
  const clock = new FakeClock();
  const speech = makeSpeech();
  let doneCount = 0;
  const engine = createPlaybackEngine({
    actions: [{ type: 'speech', text: '一二三四五六七八九十', speed: 1 }],
    speechPlayer: speech,
    scheduler: clock,
    now: () => clock.now(),
    onDone: () => { doneCount += 1; },
  });
  engine.start();
  await flush();
  assert.deepStrictEqual(speech.state.playCalls, []);            // 不碰音频
  clock.advance(2000 - 1);
  await flush();
  assert.strictEqual(doneCount, 0);
  clock.advance(1);                                              // max(2000, 10×150)=2000
  await flush();
  assert.strictEqual(doneCount, 1);
  assert.strictEqual(engine.getState(), 'idle');
});

test('有 audio_id: ended 事件驱动, 音频时长不参与调度', async () => {
  const clock = new FakeClock();
  const speech = makeSpeech();
  let doneCount = 0;
  const engine = createPlaybackEngine({
    actions: [{ type: 'speech', text: '讲解', audio_id: 'tts_s1_a1' }],
    speechPlayer: speech,
    scheduler: clock,
    now: () => clock.now(),
    onDone: () => { doneCount += 1; },
  });
  engine.start();
  await flush();
  assert.deepStrictEqual(speech.state.playCalls, ['tts_s1_a1']); // 走音频
  clock.advance(600_000);                                        // 再久也不推进
  await flush();
  assert.strictEqual(doneCount, 0);

  speech.next.resolve();                                         // ended
  await flush();
  assert.strictEqual(doneCount, 1);                              // 立即推进, 无额外等待
});

test('音频播放失败 → 估算计时器兜底', async () => {
  const clock = new FakeClock();
  const speech = makeSpeech();
  let doneCount = 0;
  const engine = createPlaybackEngine({
    actions: [{ type: 'speech', text: '一二三四五六七八九十' , audio_id: 'tts_x' }],
    speechPlayer: speech,
    scheduler: clock,
    now: () => clock.now(),
    onDone: () => { doneCount += 1; },
  });
  engine.start();
  await flush();
  speech.next.reject(new Error('audio 404'));                    // 加载失败
  await flush();
  clock.advance(2000);
  await flush();
  assert.strictEqual(doneCount, 1);                              // 兜底路径走通
});

test('音频播放中的暂停/恢复: 未结束时转发 speechPlayer, ended 后续走', async () => {
  const clock = new FakeClock();
  const speech = makeSpeech();
  const engine = createPlaybackEngine({
    actions: [{ type: 'speech', text: '讲解', audio_id: 'tts_s1_a1' }],
    speechPlayer: speech,
    scheduler: clock,
    now: () => clock.now(),
  });
  engine.start();
  await flush();
  engine.pause();
  assert.strictEqual(speech.state.pauseCalls, 1);                // 挂起音频
  engine.resume();
  assert.strictEqual(speech.state.resumeCalls, 1);               // 转发恢复
  assert.strictEqual(engine.getState(), 'playing');
  speech.next.resolve();                                         // ended
  await flush();
  assert.strictEqual(engine.getState(), 'idle');                 // 单动作: 推进至完成
});

test('音频在暂停期间已 ended: resume 接管推进, 不再转发 speechPlayer', async () => {
  const clock = new FakeClock();
  const speech = makeSpeech();
  let doneCount = 0;
  const engine = createPlaybackEngine({
    actions: [{ type: 'speech', text: '讲解', audio_id: 'tts_s1_a1' }],
    speechPlayer: speech,
    scheduler: clock,
    now: () => clock.now(),
    onDone: () => { doneCount += 1; },
  });
  engine.start();
  await flush();
  engine.pause();
  speech.next.resolve();                                         // 暂停中 ended
  await flush();
  assert.strictEqual(engine.getState(), 'paused');               // 不推进

  engine.resume();
  assert.strictEqual(speech.state.resumeCalls, 0);               // 已定局, 不转发
  assert.strictEqual(engine.getState(), 'idle');                 // 接管推进至完成
  assert.strictEqual(doneCount, 1);
});

// ─── 防御与估算函数 ────────────────────────────────────────────────────────

test('未知动作类型: 告警跳过不阻塞整场 (对齐降级约定)', async () => {
  const clock = new FakeClock();
  const renderer = makeRenderer();
  const engine = createPlaybackEngine({
    actions: [{ type: 'wb_nope' }, wbText('a')],
    renderer,
    scheduler: clock,
    now: () => clock.now(),
  });
  engine.start();
  await flush();
  clock.advance(PLAYBACK_TIMING_DEFAULTS.wbDrawMs);              // 未知动作 0 等待
  await flush();
  clock.advance(0);
  await flush();
  assert.deepStrictEqual(renderer.state.executed, ['a']);        // 继续走
  clock.advance(PLAYBACK_TIMING_DEFAULTS.wbDrawMs);
  await flush();
  assert.strictEqual(engine.getState(), 'idle');
});

test('wb 动作渲染失败: 跳过并推进, 不阻塞整场', async () => {
  const clock = new FakeClock();
  const renderer = {
    clear() {},
    execute(action) {
      if (action.content === 'bad') return Promise.reject(new Error('render fail'));
      return Promise.resolve();
    },
  };
  const engine = createPlaybackEngine({
    actions: [wbText('bad'), wbText('good')],
    renderer,
    scheduler: clock,
    now: () => clock.now(),
  });
  engine.start();
  await flush();
  clock.advance(PLAYBACK_TIMING_DEFAULTS.wbDrawMs);              // 失败动作 0 等待推进
  await flush();
  clock.advance(0);
  await flush();
  clock.advance(PLAYBACK_TIMING_DEFAULTS.wbDrawMs);
  await flush();
  assert.strictEqual(engine.getState(), 'idle');
});

test('estimateSpeechDurationMs: 中文按字/英文按词/下限/speed 收口', () => {
  const t = PLAYBACK_TIMING_DEFAULTS;
  // 10 个中文字: max(2000, 10×150)=2000
  assert.strictEqual(estimateSpeechDurationMs('一二三四五六七八九十', 1), 2000);
  // 20 个中文字: 3000
  assert.strictEqual(estimateSpeechDurationMs('一二三四五六七八九十一二三四五六七八九十', 1), 3000);
  // 短英文: 3 词 × 240 < 2000 → 下限 2000
  assert.strictEqual(estimateSpeechDurationMs('hello world foo', 1), 2000);
  // 长英文: 10 词 × 240 = 2400
  assert.strictEqual(estimateSpeechDurationMs('a b c d e f g h i j', 1), 2400);
  // speed=2 减半
  assert.strictEqual(estimateSpeechDurationMs('一二三四五六七八九十一二三四五六七八九十', 2), 1500);
  // 空文本 → 下限
  assert.strictEqual(estimateSpeechDurationMs('', 1), t.speechMinMs);
});
