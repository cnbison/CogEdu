/**
 * 2-0-4 (Phase 2, 14.2): 前端登录态共享脚本 — 登录页/学生端/家长端/教师端共用。
 *
 * 职责:
 *   - token 存取 (localStorage; Bearer header 方案, 不用 cookie —
 *     见 web/api/routers/auth.py 头注)
 *   - authFetch: 带 Authorization 的 fetch 包装, 401 → 清 token 跳登录页
 *   - requireLogin: 页面守卫, 未登录/会话失效跳 /login
 *   - logout: POST /api/auth/logout 后清 token 回登录页
 *
 * 用法: 每个页面 <script src="/auth.js"> 先于业务脚本加载。
 */
(function () {
  'use strict';

  var TOKEN_KEY = 'cogedu_token';
  var USER_KEY = 'cogedu_user';

  function getToken() { return localStorage.getItem(TOKEN_KEY) || ''; }

  function getUser() {
    try { return JSON.parse(localStorage.getItem(USER_KEY) || 'null'); }
    catch (e) { return null; }
  }

  function saveSession(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user || null));
  }

  function clearSession() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  function toLogin() {
    var here = encodeURIComponent(location.pathname + location.search);
    location.href = '/login?next=' + here;
  }

  /** 页面守卫: 无 token 直接跳登录; 有 token 经 /api/auth/me 校验
   *  (撤销/过期即失效, 不只信本地缓存)。 */
  function requireLogin() {
    if (!getToken()) { toLogin(); return; }
    fetch('/api/auth/me', { headers: { 'Authorization': 'Bearer ' + getToken() } })
      .then(function (r) { if (r.status === 401) { clearSession(); toLogin(); } })
      .catch(function () { /* 网络异常不跳转, 业务请求自己会报错 */ });
  }

  /** 带 Authorization 的 fetch; 401 → 清 token 跳登录页。 */
  function authFetch(url, opts) {
    opts = opts || {};
    opts.headers = Object.assign(
      { 'Authorization': 'Bearer ' + getToken() },
      opts.headers || {}
    );
    return fetch(url, opts).then(function (r) {
      if (r.status === 401) { clearSession(); toLogin(); }
      return r;
    });
  }

  /** 登出: 服务端撤销会话 (立即生效) + 清本地。 */
  function logout() {
    var token = getToken();
    clearSession();
    if (token) {
      fetch('/api/auth/logout', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token },
      }).catch(function () { /* 本地已清, 服务端会话由 TTL 兜底 */ });
    }
    location.href = '/login';
  }

  window.CogEduAuth = {
    getToken: getToken,
    getUser: getUser,
    saveSession: saveSession,
    clearSession: clearSession,
    requireLogin: requireLogin,
    authFetch: authFetch,
    logout: logout,
  };
})();
