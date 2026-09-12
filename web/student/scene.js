/* 讲解场景页 (Phase 1, 1-E) — 翻页式渲染.
 *
 * 数据链: POST /api/presentation/outline {student_id}
 *       → POST /api/presentation/scenes {outline_id} → scenes[]
 *
 * 安全约定 (1-E-2): LLM 文本内容一律 textContent 进 DOM, 不用 innerHTML;
 * 公式段经 KaTeX renderToString (trust=false 默认, 内嵌 HTML 被转义)。
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
    scenes = await api('/api/presentation/scenes', { outline_id: outline.outline_id });
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
        appendFormula(div, part.slice(2, -2), true);
        p.appendChild(div);
      } else if (part.startsWith('$') && part.endsWith('$') && part.length > 2) {
        appendFormula(p, part.slice(1, -1), false);
      } else {
        p.appendChild(document.createTextNode(part));
      }
    }
    container.appendChild(p);
  }
}

function appendFormula(el, tex, displayMode) {
  if (window.katex) {
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
    code.textContent = displayMode ? '$$' + tex + '$$' : '$' + tex + '$';
    el.appendChild(code);
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
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new Error(data.error || '请求失败 (HTTP ' + resp.status + ')');
  }
  return data;
}

function setStatus(text, showError) {
  document.getElementById('scene-status-text').textContent = text;
  document.getElementById('scene-retry').style.display = showError ? '' : 'none';
  document.querySelector('#scene-status .spinner').style.display = showError ? 'none' : '';
}

boot();
