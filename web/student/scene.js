/* 讲解场景页 (Phase 1, 1-E — Phase 3 3-B/3-C 扩展白板播放) — 翻页式渲染.
 *
 * 数据链: POST /api/presentation/outline {student_id}
 *       → POST /api/presentation/scenes {outline_id} → scenes[]
 *
 * Phase 3 扩展 (3-B/3-C): scene.actions 非空时显示白板讲解区
 * (播放/暂停/重播 + 字幕), 由 playback.js 引擎驱动 whiteboard.js 渲染;
 * actions 为 null (Phase 1 旧场景 / 无动作) 时保持纯翻页, 行为不变。
 *
 * 安全约定 (1-E-2): LLM 文本内容一律 textContent 进 DOM, 不用 innerHTML;
 * 公式段经 formula.js 的 KaTeX 封装渲染 (3-B-2 共享模块, 白板公式同源)。
 * KaTeX 未加载成功时公式降级为等宽文本, 不阻塞讲解阅读。
 *
 * 1-F 回写事件 (scene_next/dwell/question) 的学生端埋点随后续任务接入,
 * 本文件先保证渲染链路。
 */
'use strict';

let sid = '';
let outline = null;
let scenes = [];
let currentIndex = 0;
let pageEnteredAt = 0;      // 当前页进入时间戳 (dwell 埋点)
let totalDwellMs = 0;       // 全部页面累计停留
let completedReported = false;

// Phase 3: 白板播放状态 (3-B/3-C 接线; 每页重建)
let wb = null;        // whiteboard.js 实例 (renderer 提供方)
let engine = null;    // playback.js 引擎
let wbStarted = false;  // 本页是否已开播 (区分"播放讲解"/"重新播放"按钮态)
// 3-E: 服务端下发的时间常数 (cogedu/presentation/timing.py 权威源);
// null = 下发失败, JS 兜底镜像顶上 (镜像值被 pytest 契约测试锁定)
let timing = null;

// 1-F: 场景行为回写 (best-effort, 失败 console.warn 不静默, 不阻塞翻页)
// 2-0-4: 回写携带学生身份 (Authorization Bearer) — 服务端校验
// learning_student_id 与 payload.student_id 一致, 匿名可写已封死
function trackSceneEvent(eventType, extra) {
  const body = Object.assign({ student_id: sid, outline_id: outline ? outline.outline_id : '' }, extra);
  const headers = { 'Content-Type': 'application/json' };
  const token = (window.CogEduAuth && window.CogEduAuth.getToken()) || '';
  if (token) headers['Authorization'] = 'Bearer ' + token;
  fetch('/api/presentation/event', {
    method: 'POST',
    headers: headers,
    body: JSON.stringify(body),
    keepalive: true, // 最后一条 (scene_completed) 在跳转前发出也能送达
  }).catch((e) => console.warn('场景行为事件发送失败:', e));
}

// ─── 启动 ────────────────────────────────────────────────────────────────

async function boot() {
  // 2-0-4: 页面守卫 — 未登录/会话失效跳 /login (auth.js)
  if (window.CogEduAuth) window.CogEduAuth.requireLogin();
  const params = new URLSearchParams(location.search);
  // 2-0-4: 学生身份优先取登录账号绑定的 learning_student_id —
  // 服务端按 learning_student_id 与 payload.student_id 一致性校验,
  // 匿名带任意 sid 的回写已封死
  const authUser = (window.CogEduAuth && window.CogEduAuth.getUser()) || null;
  sid = params.get('sid')
    || (authUser && authUser.learning_student_id)
    || localStorage.getItem('cogedu_last_sid')
    || '';
  if (!sid) {
    sid = prompt('请输入学生 ID：');
    if (!sid) { setStatus('缺少学生 ID（URL 形如 /student/scene.html?sid=xxx）', true); return; }
  }
  localStorage.setItem('cogedu_last_sid', sid);
  document.getElementById('scene-sid').textContent = sid;

  try {
    setStatus('正在根据你的学习状态选择讲解内容…');
    outline = await api('/api/presentation/outline', {
      student_id: sid,
      // 从学习页进入时可带 evidence_id (1-A-4 追溯), v1 直达入口不带
    });
    setStatus('正在生成讲解场景…');
    // 3-F-5: student_id 必带 — require_student_access 按它校验学生本人,
    // 服务端再验 outline 归属 (outline.student_id 必须一致)
    scenes = await api('/api/presentation/scenes', {
      student_id: sid,
      outline_id: outline.outline_id,
    });
    await fetchTiming();   // 3-E: 时间常数注入 engine/whiteboard (失败用兜底镜像)
    document.getElementById('scene-outline-title').textContent = outline.title || '讲解';
    document.getElementById('scene-view').style.display = '';
    document.getElementById('scene-status').style.display = 'none';
    showScene(0);
  } catch (e) {
    setStatus('讲解生成失败：' + (e && e.message ? e.message : e), true);
  }
}

// ─── 渲染 ────────────────────────────────────────────────────────────────

function showScene(i) {
  currentIndex = i;
  pageEnteredAt = Date.now();
  stopPlayback();   // 3-C-4 翻页联动: 离开本页前必须 stop (令牌失效+音频停止)
  const scene = scenes[i];
  const card = document.getElementById('scene-content');
  card.innerHTML = ''; // 容器清空: 内容块由 DOM API 构建, 不拼 HTML 字符串

  document.getElementById('scene-progress').textContent = (i + 1) + ' / ' + scenes.length;
  document.getElementById('scene-degraded-banner').style.display =
    scene.degraded ? '' : 'none';

  const title = document.createElement('h3');
  title.textContent = scene.title;
  card.appendChild(title);

  for (const block of scene.blocks || []) {
    if (block.type === 'text') renderTextBlock(card, block.content);
    else if (block.type === 'image') renderImageBlock(card, block);
  }

  // Phase 3: 含动作序列的场景 → 白板讲解区 (3-B); 无动作 = 纯翻页不变
  if (scene.actions && scene.actions.length) {
    setupPlayback(scene);
  }

  document.getElementById('scene-prev').disabled = i === 0;
  const nextBtn = document.getElementById('scene-next');
  nextBtn.disabled = false;
  nextBtn.textContent = i === scenes.length - 1 ? '完成学习 ✓' : '下一页 →';
  window.scrollTo({ top: 0 });
}

function renderTextBlock(container, content) {
  // $...$ 行内 / $$...$$ 独立公式; 其余文本 textContent (不 innerHTML)
  const re = /(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)/g;
  const paragraphs = String(content).split(/\n{2,}/);
  for (const para of paragraphs) {
    const parts = para.split(re).filter(Boolean);
    if (!parts.length) continue;
    const p = document.createElement('p');
    for (const part of parts) {
      if (part.startsWith('$$') && part.endsWith('$$')) {
        const div = document.createElement('div');
        div.className = 'formula-display';
        window.CogEduFormula.renderFormulaInto(div, part.slice(2, -2), true);
        p.appendChild(div);
      } else if (part.startsWith('$') && part.endsWith('$') && part.length > 2) {
        window.CogEduFormula.renderFormulaInto(p, part.slice(1, -1), false);
      } else {
        p.appendChild(document.createTextNode(part));
      }
    }
    container.appendChild(p);
  }
}

function renderImageBlock(container, block) {
  const wrap = document.createElement('div');
  wrap.className = 'scene-image';
  if (block.url) {
    const img = document.createElement('img');
    img.loading = 'lazy'; // 1-E-3 懒加载
    img.alt = block.alt || '';
    img.onerror = () => wrap.replaceChildren(makePlaceholder(block));
    img.src = block.url;
    wrap.appendChild(img);
  } else {
    wrap.appendChild(makePlaceholder(block));
  }
  container.appendChild(wrap);
}

function makePlaceholder(block) {
  const ph = document.createElement('div');
  ph.className = 'img-placeholder';
  const icon = document.createElement('span');
  icon.className = 'icon';
  icon.textContent = '🖼️';
  const label = document.createElement('span');
  label.textContent = '配图（占位）：' + (block.alt || '示意图');
  ph.appendChild(icon);
  ph.appendChild(label);
  return ph;
}

// ─── 音频播放器 (Phase 3, 3-D) ───────────────────────────────────────────

// 引擎 (3-C) speechPlayer 接口的实现体: audio_id → 服务端音频 → <audio>。
// - 播放失败 (HTTP 404/起播失败) → reject → 引擎回落估算计时器, 字幕静音
//   推进 (3-D-5 降级链, UI 已有字幕位); 不做浏览器 Web Speech API (v0.6 拍板)
// - GET 带 student_id 查询串 (router 级 dependency 放行学生角色所需);
//   服务端按音频归属 (audio→scene.student_id) 做权威校验
// - blob 按 audioId 会话内缓存: 重播/回看不重复下载
function createSpeechPlayer() {
  const blobCache = new Map();   // audioId → blob
  let audio = null;

  function fetchBlob(audioId) {
    if (blobCache.has(audioId)) return Promise.resolve(blobCache.get(audioId));
    const headers = {};
    const token = (window.CogEduAuth && window.CogEduAuth.getToken()) || '';
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return fetch(
      `/api/presentation/audio/${encodeURIComponent(audioId)}`
      + `?student_id=${encodeURIComponent(sid)}`,
      { headers },
    ).then((resp) => {
      if (!resp.ok) throw new Error('audio HTTP ' + resp.status);
      return resp.blob();
    }).then((blob) => {
      blobCache.set(audioId, blob);
      return blob;
    });
  }

  return {
    play(audioId) {
      return new Promise((resolve, reject) => {
        fetchBlob(audioId).then((blob) => {
          audio = new Audio(URL.createObjectURL(blob));
          audio.onended = () => resolve(true);
          audio.onerror = () => reject(new Error('audio 播放失败'));
          audio.play().catch(() => reject(new Error('audio 起播失败')));
        }).catch((e) => reject(e));
      });
    },
    pause() { if (audio) audio.pause(); },
    resume() { if (audio) audio.play().catch(() => {}); },
    stop() {
      if (audio) {
        audio.onended = null;
        audio.onerror = null;
        audio.pause();
        audio.src = '';
        audio = null;
      }
    },
  };
}

// ─── 白板播放接线 (Phase 3, 3-B/3-C) ─────────────────────────────────────

// 3-C-4 翻页联动: 翻页/重进页前必须 stop — 令牌失效 + 音频停止 + UI 复位。
// 引擎/白板均为每页重建, 不跨页复用。
function stopPlayback() {
  if (engine) {
    engine.stop();
    engine = null;
  }
  wb = null;
  wbStarted = false;
  hideSubtitle();
  const section = document.getElementById('wb-section');
  if (section) section.style.display = 'none';
}

// 含动作序列的场景: 挂白板 + 建引擎。静态资源缺失时守卫退回纯翻页。
function setupPlayback(scene) {
  if (!window.CogEduPlayback || !window.CogEduWhiteboard) {
    console.warn('播放组件未加载, 本页退回纯翻页模式');
    return;
  }
  const section = document.getElementById('wb-section');
  const container = document.getElementById('wb-container');
  wb = window.CogEduWhiteboard.createWhiteboard(container, {
    timing: timing ? { enterMs: timing.wb_enter_ms, staggerMs: timing.wb_stagger_ms } : undefined,
  });
  engine = window.CogEduPlayback.createPlaybackEngine({
    actions: scene.actions,
    renderer: wb.renderer,
    speechPlayer: createSpeechPlayer(),   // 3-D: 音频 ended 驱动, 失败回落估算
    timing: timing ? {   // 3-E: 服务端下发的时序常数 (权威源 timing.py)
      wbDrawMs: timing.wb_draw_ms,
      speechMinMs: timing.speech_min_ms,
      cjkMsPerChar: timing.cjk_ms_per_char,
      latinMsPerWord: timing.latin_ms_per_word,
      cjkRatioThreshold: timing.cjk_ratio_threshold,
    } : undefined,
    // 字幕同步 (3-C-3): speech 动作开始时展示讲解词 — 有音频时随音频走,
    // 无音频 (3-D 未接/生成失败) 时随估算计时器静音推进
    onActionStart: function (action) {
      if (action.type === 'speech') showSubtitle(action.text);
    },
    onStateChange: updatePlayButton,
    onDone: function () { updatePlayButton(engine.getState()); },
  });
  section.style.display = '';
  updatePlayButton('idle');
}

function updatePlayButton(state) {
  const playBtn = document.getElementById('wb-play');
  const replayBtn = document.getElementById('wb-replay');
  if (!playBtn) return;
  if (state === 'playing') playBtn.textContent = '⏸ 暂停';
  else if (state === 'paused') playBtn.textContent = '▶ 继续播放';
  else playBtn.textContent = wbStarted ? '▶ 重新播放' : '▶ 播放讲解';
  // 重播按钮: 开播过才出现 (3-B-3: v1 砍撤销/重做, 重播是唯一的"再来一遍")
  replayBtn.style.display = wbStarted ? '' : 'none';
}

function togglePlay() {
  if (!engine) return;
  const s = engine.getState();
  if (s === 'idle') {
    wbStarted = true;
    engine.start();
  } else if (s === 'playing') {
    engine.pause();
  } else if (s === 'paused') {
    engine.resume();
  }
  updatePlayButton(engine.getState());
}

function replayPage() {
  if (!engine) return;
  engine.replay();   // stop + start + renderer.clear (3-C: 从头确定性重放)
}

function showSubtitle(text) {
  const el = document.getElementById('wb-subtitle');
  if (!el) return;
  el.textContent = text;
  el.style.display = '';
}

function hideSubtitle() {
  const el = document.getElementById('wb-subtitle');
  if (!el) return;
  el.style.display = 'none';
  el.textContent = '';
}

// ─── 翻页 (1-E-1) ────────────────────────────────────────────────────────

function prevScene() {
  if (currentIndex > 0) showScene(currentIndex - 1);
}

function nextScene() {
  const dwellSec = (Date.now() - pageEnteredAt) / 1000;
  totalDwellMs += Date.now() - pageEnteredAt;
  const scene = scenes[currentIndex];
  // 1-F-2: 翻页即回写 scene_viewed (dwell 埋点)
  trackSceneEvent('scene_viewed', {
    scene_id: scene.scene_id,
    step_id: scene.step_id,
    dwell_sec: Math.round(dwellSec * 10) / 10,
    index: currentIndex,
  });
  if (currentIndex < scenes.length - 1) {
    showScene(currentIndex + 1);
  } else {
    // 最后一页: 回写 scene_completed (完成信号) 后跳回学习页
    if (!completedReported) {
      completedReported = true;
      trackSceneEvent('scene_completed', {
        scene_count: scenes.length,
        total_dwell_sec: Math.round((totalDwellMs / 1000) * 10) / 10,
      });
    }
    window.location.href = '/student/';
  }
}

// ─── 工具 ────────────────────────────────────────────────────────────────

async function api(url, body) {
  // 2-0-4 补全 (2026-09-14): outline/scenes/timing 与回写/音频一样必须带
  // 登录凭证——此前本函数是页面内唯一裸 fetch 的请求路径, 真实鉴权下
  // "点击讲解"必 401 (测试环境 auth_bypass 掩盖)。走 authFetch 统一
  // 带 Bearer + 401 自动跳登录。
  const opts = { headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) {           // 无 body → GET (3-E /timing)
    opts.method = 'POST';
    opts.body = JSON.stringify(body);
  }
  const resp = await window.CogEduAuth.authFetch(url, opts);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.error || '请求失败 (HTTP ' + resp.status + ')');
  }
  return data;
}

// 3-E: 时间常数下发 (带 student_id 供 router 级 dependency 放行学生角色);
// 失败不阻塞讲解 — JS 兜底镜像顶上 (镜像值被 pytest 契约测试锁定防漂移)
async function fetchTiming() {
  try {
    timing = await api('/api/presentation/timing?student_id=' + encodeURIComponent(sid));
  } catch (e) {
    console.warn('时间常数下发失败, 使用内置兜底值:', e);
  }
}

function setStatus(text, showError) {
  document.getElementById('scene-status-text').textContent = text;
  document.getElementById('scene-retry').style.display = showError ? '' : 'none';
  document.querySelector('#scene-status .spinner').style.display = showError ? 'none' : '';
}

boot();
