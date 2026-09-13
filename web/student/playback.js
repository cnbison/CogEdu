/* 场景动作序列播放引擎 (Phase 3, 3-C, 方案文档 15.4).
 *
 * 设计来源: 参考 OpenMAIC lib/playback/engine.ts 的状态机与调度结构重写,
 * 按 CogEdu v1 范围裁剪:
 *   - 三态 idle/playing/paused — OpenMAIC 第四态 live (discussion/AI 同学
 *     追问) 不在 Phase 3 范围
 *   - 顺序事件驱动 + setTimeout, 不用 rAF/绝对时间轴 (15.2 3-A-3)
 *   - speech 等音频 ended; 无 audio_id 或播放失败 → 估算计时器兜底,
 *     音频时长不参与调度 (15.5 修正)
 *   - 核心并发正确性机制 = generation 代数令牌 (照抄 OpenMAIC
 *     playbackGeneration): stop/重播使旧异步回调全部失效 — 没有它,
 *     "暂停后旧 setTimeout 又画出下一个图形"这类 bug 必现
 *
 * 依赖注入 (全部可替换, 本文件不碰 DOM):
 *   - renderer: { clear(), execute(action) -> Promise }  — 3-B 白板提供;
 *     默认 no-op (引擎可独立测试/复用)
 *   - speechPlayer: { play(audioId) -> Promise, pause(), resume(), stop() }
 *     — 3-D 接线 <audio>; 默认恒失败 (走估算计时器路径)
 *   - scheduler: { setTimeout, clearTimeout } + now() — 测试注入 FakeClock
 *
 * 时序常量: 内置默认值对齐 OpenMAIC choreography/timing.ts 实测值, 3-E
 * 收口后由服务端 (cogedu/presentation/timing.py) 经 API 下发覆盖 —
 * JS 侧硬编码只是 3-E 落地前的过渡态, 不是终态。
 *
 * 用法:
 *   const engine = CogEduPlayback.createPlaybackEngine({
 *     actions: scene.actions,
 *     renderer: whiteboard,        // 3-B
 *     speechPlayer: audioPlayer,   // 3-D
 *     onActionStart: (a) => ...,   // 字幕/高亮等 UI 反应
 *     onStateChange: (s) => ...,   // 播放/暂停按钮态
 *     onDone: () => ...,
 *   });
 *   engine.start(); engine.pause(); engine.resume(); engine.stop();
 *   engine.replay();  // 重播本页 (3-B-3: v1 砍撤销/重做, 代之以重播)
 */
'use strict';

// ─── 时序常量 (3-E 收口前占位; 值对齐 OpenMAIC timing.ts) ─────────────────

var PLAYBACK_TIMING_DEFAULTS = {
  wbDrawMs: 800,            // 每个白板动作的讲解节奏间隔 (OpenMAIC WB_DRAW_MS)
  speechMinMs: 2000,        // 估算语音时长下限 (OpenMAIC estimateSpeechDurationMs)
  cjkMsPerChar: 150,        // 中文每字毫秒
  latinMsPerWord: 240,      // 英文每词毫秒 (≈250 WPM)
  cjkRatioThreshold: 0.3,   // CJK 占比超过此值按中文语速估算
};

// ─── 语音时长估算 (3-E 将由服务端下发同源实现, 此处为兜底) ────────────────

// 估算语音时长 ms: CJK 占比 > 0.3 → max(2000, 字数×150); 否则按词 240ms;
// 最后除以 speed。15.4 3-C-3: 只做无音频时的兜底, 不参与音频调度。
function estimateSpeechDurationMs(text, speed, timing) {
  var t = Object.assign({}, PLAYBACK_TIMING_DEFAULTS, timing || {});
  var s = String(text || '');
  var chars = s.replace(/\s/g, '');
  if (!chars.length) return t.speechMinMs;
  var cjk = (chars.match(/[㐀-䶿一-鿿]/g) || []).length;
  var durationMs;
  if (cjk / chars.length > t.cjkRatioThreshold) {
    durationMs = Math.max(t.speechMinMs, cjk * t.cjkMsPerChar);
  } else {
    var words = s.trim().split(/\s+/).filter(Boolean).length;
    durationMs = Math.max(t.speechMinMs, words * t.latinMsPerWord);
  }
  return Math.round(durationMs / Math.max(speed || 1, 0.1));
}

// ─── 播放引擎 ─────────────────────────────────────────────────────────────

// 状态机三态 (3-C-1): idle → playing ⇄ paused; stop/播完 → idle
var STATE_IDLE = 'idle';
var STATE_PLAYING = 'playing';
var STATE_PAUSED = 'paused';

// wb_* 动作类型 (schema 白名单的引擎侧镜像; 3-F 生成层已过滤, 此处兜底)
var WB_ACTION_TYPES = ['wb_draw_text', 'wb_draw_shape', 'wb_draw_line', 'wb_draw_latex'];

function createPlaybackEngine(options) {
  var opts = options || {};
  var actions = Array.isArray(opts.actions) ? opts.actions : [];
  var timing = Object.assign({}, PLAYBACK_TIMING_DEFAULTS, opts.timing || {});

  // renderer: wb_* 动作的执行体 (3-B 白板); 默认 no-op
  var renderer = opts.renderer || {
    clear: function () {},
    execute: function () { return Promise.resolve(); },
  };
  // speechPlayer: 音频播放体 (3-D); 默认恒失败 → 全部走估算计时器路径
  var speechPlayer = opts.speechPlayer || {
    play: function () { return Promise.reject(new Error('no speech player')); },
    pause: function () {},
    resume: function () {},
    stop: function () {},
  };
  // scheduler/now: 测试注入 FakeClock; 默认真实定时器
  var scheduler = opts.scheduler || {
    setTimeout: function (fn, ms) { return setTimeout(fn, ms); },
    clearTimeout: function (id) { return clearTimeout(id); },
  };
  var now = opts.now || function () { return Date.now(); };

  var onStateChange = opts.onStateChange || function () {};
  var onActionStart = opts.onActionStart || function () {};
  var onDone = opts.onDone || function () {};

  var state = STATE_IDLE;
  var generation = 0;          // 3-C-2 代数令牌: stop/replay 后旧回调全部失效
  var cursor = 0;              // 下一个待执行的动作下标
  // 当前在途等待 (pause 时算剩余时间, resume 时续期):
  // { handle, startedAt, durationMs, onFire }
  var activeWait = null;
  // 当前 speech 动作的音频路径状态 (3-C-3)。play promise 可能在暂停期间
  // 已定局 (ended/失败) 而其续点被 valid() 丢弃 — settled/outcome 记录
  // 定局结果, resume() 据此接管推进, 否则恢复后既不转发也不推进
  var audio = { active: false, settled: false, outcome: null, fallbackMs: 0, gen: 0 };
  // wb_* 动作的 execute promise 在途中 (pause 可能落在这个窗口:
  // promise 在暂停期间 resolve 的话其续点已被 valid() 丢弃, resume 需补推)
  var inFlightExecute = false;

  function setState(next) {
    if (state === next) return;
    state = next;
    onStateChange(state);
  }

  function valid(gen) {
    // 回调存活判定: 令牌未失效且仍处于 playing (pause 期间不推进)
    return gen === generation && state === STATE_PLAYING;
  }

  // 可暂停的等待: 记录 startedAt/durationMs, pause 取剩余, resume 续期
  function wait(ms, gen, onFire) {
    if (ms <= 0) ms = 0;
    activeWait = {
      startedAt: now(),
      durationMs: ms,
      onFire: onFire,
      handle: scheduler.setTimeout(function () {
        activeWait = null;
        if (valid(gen) && onFire) onFire();
      }, ms),
    };
  }

  function pauseActiveWait() {
    if (!activeWait) return;
    scheduler.clearTimeout(activeWait.handle);
    var elapsed = now() - activeWait.startedAt;
    var remaining = Math.max(0, activeWait.durationMs - elapsed);
    var onFire = activeWait.onFire;
    activeWait = { startedAt: now(), durationMs: remaining, handle: null, onFire: onFire };
  }

  function resumeActiveWait(gen) {
    if (!activeWait) return;
    var w = activeWait;
    w.startedAt = now();
    w.handle = scheduler.setTimeout(function () {
      activeWait = null;
      if (valid(gen) && w.onFire) w.onFire();
    }, w.durationMs);
  }

  function clearActiveWait() {
    if (activeWait && activeWait.handle !== null) {
      scheduler.clearTimeout(activeWait.handle);
    }
    activeWait = null;
  }

  // 主循环 (3-C-2): 顺序事件驱动, await 当前动作完成后推进下一个;
  // 每个异步续点先查令牌+状态, 失效即静默退出 (stop/replay 已接管)

  // 音频定局后的推进: ended → 直接推进; 失败/未开播 → 估算兜底等待
  function afterAudio(gen) {
    var advance = function () { if (valid(gen)) processNext(gen); };
    if (audio.outcome === 'ended') {
      advance();
    } else {
      wait(audio.fallbackMs, gen, advance);
    }
  }

  function processNext(gen) {
    if (!valid(gen)) return;
    if (cursor >= actions.length) {
      setState(STATE_IDLE);
      clearActiveWait();
      onDone();
      return;
    }
    var index = cursor;
    var action = actions[index];
    cursor = index + 1;
    onActionStart(action, index);

    var advance = function () { if (valid(gen)) processNext(gen); };

    if (action.type === 'speech') {
      var estMs = estimateSpeechDurationMs(action.text, action.speed, timing);
      if (action.audio_id) {
        // 3-C-3 优先级: 有 audio_id 且加载成功 → ended 事件驱动
        audio.active = true;
        audio.settled = false;
        audio.outcome = null;
        audio.fallbackMs = estMs;
        audio.gen = gen;
        speechPlayer.play(action.audio_id).then(
          function (started) {
            audio.settled = true;
            audio.outcome = started === false ? 'not-started' : 'ended';
            if (!valid(gen)) return;   // 暂停期间定局: resume() 接管推进
            audio.active = false;
            afterAudio(gen);
          },
          function () {
            audio.settled = true;
            audio.outcome = 'failed';  // 加载/播放失败 → 估算兜底 (15.4 3-C-3)
            if (!valid(gen)) return;
            audio.active = false;
            afterAudio(gen);
          }
        );
      } else {
        wait(estMs, gen, advance);
      }
      return;
    }

    // 白名单外动作: 告警跳过不阻塞整场 (对齐"宁可明确降级不静默")
    if (WB_ACTION_TYPES.indexOf(action.type) === -1) {
      console.warn('未知动作类型, 跳过:', action.type);
      wait(0, gen, advance);
      return;
    }

    // wb_* 动作: 执行 (DOM 插入即时返回) + WB_DRAW_MS 级节奏等待后推进。
    // 续点先查 valid 再清 inFlightExecute: 暂停期间 resolve 的续点被丢弃时
    // 保留标志, resume() 的补推分支据此恢复, 否则恢复后引擎卡死
    inFlightExecute = true;
    Promise.resolve(renderer.execute(action)).then(
      function () {
        if (!valid(gen)) return;
        inFlightExecute = false;
        wait(timing.wbDrawMs, gen, advance);
      },
      function (e) {
        if (!valid(gen)) return;
        inFlightExecute = false;
        // 单个动作渲染失败不阻塞整场 (对齐"宁可明确降级不静默")
        console.warn('动作渲染失败, 跳过:', action.type, e);
        wait(0, gen, advance);
      }
    );
  }

  // ── 状态转移 (3-C-1) ──────────────────────────────────────────────────

  function start() {
    if (state !== STATE_IDLE) return;
    if (!actions.length) { onDone(); return; }  // 无动作 = 纯翻页场景 (Phase 1)
    generation += 1;   // 新一轮播放: 旧回调全部作废
    cursor = 0;
    inFlightExecute = false;
    renderer.clear();
    setState(STATE_PLAYING);
    processNext(generation);
  }

  function pause() {
    if (state !== STATE_PLAYING) return;
    setState(STATE_PAUSED);
    pauseActiveWait();          // 记录剩余时间
    if (audio.active) speechPlayer.pause();  // 音频挂起, ended 自然延后
  }

  function resume() {
    if (state !== STATE_PAUSED) return;
    setState(STATE_PLAYING);
    if (audio.active && audio.settled) {
      // ended/失败发生在暂停期间, 其续点已被 valid() 丢弃 — 此处接管推进
      audio.active = false;
      afterAudio(audio.gen);
    } else if (audio.active) {
      speechPlayer.resume();    // 原播放 promise 仍挂着, ended 后自然续走
    } else if (activeWait && activeWait.handle === null) {
      resumeActiveWait(generation);   // 暂停中记录了剩余时间 → 续期
    } else if (inFlightExecute) {
      // execute promise 在暂停期间 resolve, 其续点已被 valid() 丢弃 —
      // 补一个 0 等待推进 (该动作画面已完成, 不重播)
      var gen = generation;
      wait(0, gen, function () { if (valid(gen)) processNext(gen); });
    }
    // 其余情况: execute 仍在途中, 其续点恢复 playing 后自行推进
  }

  function stop() {
    if (state === STATE_IDLE && !activeWait && !audio.active) return;
    generation += 1;            // 令牌失效: 所有在途回调作废
    clearActiveWait();
    if (audio.active) { speechPlayer.stop(); audio.active = false; }
    cursor = 0;
    inFlightExecute = false;
    setState(STATE_IDLE);
  }

  // 重播本页 (3-B-3): stop + start, 白板经 renderer.clear() 重置
  function replay() {
    stop();
    start();
  }

  return {
    start: start,
    pause: pause,
    resume: resume,
    stop: stop,
    replay: replay,
    getState: function () { return state; },
    // 供翻页联动 (3-C-4, 随 3-B 接入 scene.js): 离开本页前必须 stop
    getActionCount: function () { return actions.length; },
  };
}

// ─── 导出: 浏览器 global + node (测试) 双通道 ──────────────────────────────

var CogEduPlayback = {
  createPlaybackEngine: createPlaybackEngine,
  estimateSpeechDurationMs: estimateSpeechDurationMs,
  PLAYBACK_TIMING_DEFAULTS: PLAYBACK_TIMING_DEFAULTS,
};

if (typeof window !== 'undefined') {
  window.CogEduPlayback = CogEduPlayback;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = CogEduPlayback;
}
