"""Phase 1 (1-G-1): 呈现引擎真实进程灰度脚本 — 沿用 12.6 灰度模式.

链路: 真实 uvicorn 进程 + 真实 LLM (MiniMax 主), 3 个案例:
  开户+登录 (2-0 账号体系落地后走真实登录链路, 无鉴权后门)
       → 答错 ×2 → POST /api/presentation/outline (带 evidence_id)
         → POST /api/presentation/scenes
         → POST /api/presentation/event (scene_viewed × n + scene_completed)
         → 再答对 → GET /api/state (theta 演化核对)

输出: 每案例生成内容打印到 stdout (人工检查内容质量: 讲解对不对、
和学生实际薄弱点匹不匹配 — 13.8 "不只是跑通不报错")。

用法:
  ECOS_DB_PATH=/tmp/canary_p1.db python scripts/canary_phase1_presentation.py
需要环境变量里有 MiniMax API key (ECOSLLMClient.from_env("minimax"))。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request

PORT = int(os.environ.get("CANARY_PORT", "5199"))
BASE = f"http://127.0.0.1:{PORT}"
# CANARY_CASES=canary_p1_b,canary_p1_c 可只跑指定案例 (重跑断点续传用)
_CASE_FILTER = [s.strip() for s in os.environ.get("CANARY_CASES", "").split(",") if s.strip()]

# 3 案例: 不同知识点 / 误概念背景 (内容质量人工检查样本)
CASES = [
    {"sid": "canary_p1_a", "skill": "math.quadratic", "wrong": "A", "right": "B"},
    {"sid": "canary_p1_b", "skill": "physics.motion", "wrong": "C", "right": "D"},
    {"sid": "canary_p1_c", "skill": "chemistry.reaction", "wrong": "B", "right": "A"},
]

# 2-0: 灰度账号 (每案例一个学生账号, 密码仅灰度 tmp DB 内有效)
CANARY_PASSWORD = "canary-password-2026"
_AUTH_TOKEN: str | None = None


def req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if _AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {_AUTH_TOKEN}"
    r = urllib.request.Request(
        BASE + path, data=data, method=method, headers=headers,
    )
    # 场景请求 = 大纲步数次 LLM 串行调用, 每次含 thinking 模型推理, 全程可达数分钟
    with urllib.request.urlopen(r, timeout=900) as resp:
        return json.loads(resp.read())


def _provision_accounts(sids: list[str]) -> None:
    """灰度开户 (直连 tmp DB 建学生账号).

    开户直连 DB 是因为服务进程独立、v1 无注册端点 (K12 由管理员/教师
    开户, 见 web/api/auth.py 头注); 登录必须走 HTTP — 灰度环境正是要
    验证鉴权链路本身 (2-0-3: 不做环境变量关鉴权的后门)。
    """
    # ECOS_DB_PATH 已在 main() 设为灰度 tmp DB, import 晚于 env 设置
    from web.api import auth as auth_service

    for sid in sids:
        try:
            auth_service.create_user(
                username=f"canary_{sid}",
                password=CANARY_PASSWORD,
                role="student",
                display_name=f"灰度学生 {sid}",
                learning_student_id=sid,
            )
        except Exception as e:
            if "已存在" not in str(e):
                raise  # 断点续传时账号已建, 其余失败上抛


def _login_as(sid: str) -> None:
    """按案例登录对应学生账号, 后续请求全部带 Bearer token."""
    global _AUTH_TOKEN
    resp = req("POST", "/api/auth/login", {
        "username": f"canary_{sid}",
        "password": CANARY_PASSWORD,
    })
    _AUTH_TOKEN = resp["token"]
    print(f"[canary] login ok: {resp['user']['username']} "
          f"(role={resp['user']['role']}, sid={resp['user']['learning_student_id']})")

def _wait_scenes(sid: str, outline_id: str) -> list:
    """§10 #10: POST /scenes 非阻塞 (202) → 轮询 status → 拉取场景列表."""
    resp = req("POST", "/api/presentation/scenes", {
        "student_id": sid, "outline_id": outline_id,
    })
    q = f"?student_id={urllib.parse.quote(sid)}"
    if resp.get("status") == "ready":
        return req("GET", f"/api/presentation/scenes/{outline_id}{q}")
    while True:
        st = req("GET", f"/api/presentation/scenes/{outline_id}/status{q}")
        print(f"[scenes] 生成进度 {st['generated']}/{st['total']} ({st['status']})")
        if st["status"] == "ready":
            return req("GET", f"/api/presentation/scenes/{outline_id}{q}")
        if st["status"] == "not_started":
            resp = req("POST", "/api/presentation/scenes", {
                "student_id": sid, "outline_id": outline_id,
            })
        time.sleep(10)


def main() -> int:
    tmp_db = os.environ.get("ECOS_DB_PATH") or os.path.join(
        tempfile.mkdtemp(prefix="canary_p1_"), "canary.db"
    )
    env = dict(os.environ, ECOS_DB_PATH=tmp_db)
    print(f"[canary] db={tmp_db}, port={PORT}")
    proc = subprocess.Popen(
        # app.py __main__ 写死 5173, 灰度用 uvicorn CLI 指定端口
        # (lifespan ensure_started 的激活口径两种入口一致, 见 app.py 头注)
        [sys.executable, "-m", "uvicorn", "web.api.app:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                v = req("GET", "/api/version")
                print(f"[canary] server up: {v}")
                break
            except Exception:
                time.sleep(1)
        else:
            print("[canary] server failed to start")
            return 1

        results = []
        # 2-0: 开户 (全部案例一次建齐) — 每案例是不同学生, token 是
        # per-user 的, 循环内逐案例登录自己的账号 (越权 403 会直接失败,
        # 灰度环境正是要验证鉴权链路本身)
        _provision_accounts([c["sid"] for c in CASES if not _CASE_FILTER or c["sid"] in _CASE_FILTER])
        for case in CASES:
            if _CASE_FILTER and case["sid"] not in _CASE_FILTER:
                continue
            sid = case["sid"]
            _login_as(sid)
            print(f"\n{'=' * 70}\n[case] {sid}  skill={case['skill']}")

            # 1. 答错 ×2 (首答 warmup)
            for i in range(2):
                ans = req("POST", "/api/answer", {
                    "student_id": sid,
                    "problem_id": f"CANARY-Q{i + 1}",
                    "skill_id": case["skill"],
                    "correct": False, "score": 0.0, "bloom_layer": "L3",
                    "user_answer": case["wrong"],
                })
            theta_wrong = ans["theta"]
            print(f"[answer] theta after wrong x2: {theta_wrong}")

            # 2. 大纲
            outline = req("POST", "/api/presentation/outline", {
                "student_id": sid, "evidence_id": f"ev-{sid}",
            })
            print(f"[outline] {outline['outline_id']}  title={outline['title']}")
            for s in outline["steps"]:
                print(f"  - {s['title']}  要点: {'; '.join(s['key_points'])}")

            # 3. 场景
            scenes = _wait_scenes(sid, outline["outline_id"])
            print(f"[scenes] {len(scenes)} scenes, degraded={[s['degraded'] for s in scenes]}")
            for s in scenes:
                text = next((b["content"] for b in s["blocks"] if b["type"] == "text"), "")
                img = next((b for b in s["blocks"] if b["type"] == "image"), {})
                print(f"\n  ── 场景: {s['title']}  (配图意图: {img.get('alt', '')})")
                print(f"  {text[:500]}{'…' if len(text) > 500 else ''}")

            # 4. 行为回写
            for idx, s in enumerate(scenes):
                req("POST", "/api/presentation/event", {
                    "student_id": sid, "outline_id": outline["outline_id"],
                    "event_type": "scene_viewed", "scene_id": s["scene_id"],
                    "step_id": s["step_id"], "dwell_sec": 12.0 + idx, "index": idx,
                })
            req("POST", "/api/presentation/event", {
                "student_id": sid, "outline_id": outline["outline_id"],
                "event_type": "scene_completed",
                "scene_count": len(scenes), "total_dwell_sec": 60.0,
            })
            print("\n[event] scene_viewed x n + scene_completed → 200")

            # 5. 再答对 → theta 演化
            req("POST", "/api/answer", {
                "student_id": sid, "problem_id": "CANARY-Q9",
                "skill_id": case["skill"], "correct": True, "score": 1.0,
                "bloom_layer": "L3", "user_answer": case["right"],
            })
            state = req("GET", f"/api/state/{sid}")
            theta_after = state["theta"]
            k_moved = theta_after["K"] > theta_wrong["K"]
            print(f"[state] theta K: {theta_wrong['K']:.3f} → {theta_after['K']:.3f}  (答对后上移: {k_moved})")
            print(f"[state] overall_confidence: {state.get('overall_confidence')}")

            results.append({
                "sid": sid, "outline_id": outline["outline_id"],
                "scenes": len(scenes), "degraded": any(s["degraded"] for s in scenes),
                "k_moved_up": k_moved,
            })

        print(f"\n{'=' * 70}\n[canary] 汇总:")
        for r in results:
            print(f"  {r['sid']}: scenes={r['scenes']} degraded={r['degraded']} K上移={r['k_moved_up']}")
        ok = all(not r["degraded"] and r["k_moved_up"] for r in results)
        print(f"[canary] {'✅ 全部通过 (内容质量需人工复核上方输出)' if ok else '❌ 存在异常'}")
        return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


if __name__ == "__main__":
    sys.exit(main())
