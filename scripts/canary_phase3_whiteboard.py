"""Phase 3 (3-G): 白板与语音真实进程灰度脚本 — 沿用 1-G/2-E 模式.

链路: 真实 uvicorn 进程 + 真实 LLM (MiniMax), 2 个含公式讲解的案例:
  开户 + 真实登录 (无鉴权后门)
    → 答错 ×2 (制造干预背景)
    → POST /api/presentation/outline
    → POST /api/presentation/scenes (student_id + outline_id, 3-F-5 契约)
      → 断言: schema_version=2 / actions 非空 / 类型全在白名单 /
              坐标在画布内 / action_id 口径 / estimated_duration_ms 已填
    → GET /api/presentation/timing (3-E 下发契约)
    → (可选) TTS 后台补齐核对: 配置了 COGEDU_TTS_API_KEY 且未设
      CANARY_SKIP_TTS=1 时轮询 audio 端点; 否则打印跳过 (降级链即默认路径)
    → 行为回写 (1-F 链路回归)
    → 再答对 → GET /api/state theta K 上移

输出: 每案例 actions 完整 JSON 打印到 stdout (人工复核 15.8 验收点:
画图与讲解节奏是否对得上、公式是否清晰、坐标布局是否合理)。

用法:
  set -a && source .env && set +a   # MINIMAX_API_KEY
  ECOS_DB_PATH=/tmp/canary_p3.db python scripts/canary_phase3_whiteboard.py
  CANARY_CASES=canary_p3_a          # 断点续传跑单案例
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

PORT = int(os.environ.get("CANARY_PORT", "5201"))
BASE = f"http://127.0.0.1:{PORT}"
_CASE_FILTER = [s.strip() for s in os.environ.get("CANARY_CASES", "").split(",") if s.strip()]

CASES = [
    {"sid": "canary_p3_a", "skill": "math.quadratic", "wrong": "A", "right": "B"},
    {"sid": "canary_p3_b", "skill": "physics.motion", "wrong": "C", "right": "D"},
]

CANARY_PASSWORD = "canary-password-2026"
_AUTH_TOKEN: str | None = None

# 3-A 白名单 (服务端 ALLOWED_ACTION_TYPES 镜像, 用于灰度断言)
WHITELIST = {"wb_draw_text", "wb_draw_shape", "wb_draw_line", "wb_draw_latex", "speech"}
CANVAS_W, CANVAS_H = 1000, 562.5


def req(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if _AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {_AUTH_TOKEN}"
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    # 场景请求 = 每步一次 LLM 串行调用, 全程可达数分钟 (同 1-G 口径)
    with urllib.request.urlopen(r, timeout=900) as resp:
        return json.loads(resp.read())


def _action_coord_issues(actions: list[dict]) -> list[str]:
    """坐标画布内断言 (3-A-2; 服务端已 clamp, 越界即异常信号)."""
    issues: list[str] = []
    for i, a in enumerate(actions):
        t = a.get("type")
        pts: list[tuple[str, float, float]] = []
        if t in ("wb_draw_text", "wb_draw_shape", "wb_draw_latex"):
            pts = [("x,y", a.get("x", -1), a.get("y", -1))]
        elif t == "wb_draw_line":
            pts = [("p1", a.get("x1", -1), a.get("y1", -1)),
                   ("p2", a.get("x2", -1), a.get("y2", -1))]
        for label, x, y in pts:
            if not (0 <= x <= CANVAS_W and 0 <= y <= CANVAS_H):
                issues.append(f"action[{i}] {t} {label}=({x},{y}) 越界")
    return issues


def _provision_accounts(sids: list[str]) -> None:
    from web.api import auth as auth_service

    for sid in sids:
        try:
            auth_service.create_user(
                username=f"canary_{sid}", password=CANARY_PASSWORD,
                role="student", display_name=f"灰度学生 {sid}",
                learning_student_id=sid,
            )
        except Exception as e:
            if "已存在" not in str(e):
                raise


def _login_as(sid: str) -> None:
    global _AUTH_TOKEN
    resp = req("POST", "/api/auth/login", {
        "username": f"canary_{sid}", "password": CANARY_PASSWORD,
    })
    _AUTH_TOKEN = resp["token"]
    print(f"[canary] login ok: {resp['user']['username']} "
          f"(role={resp['user']['role']}, sid={resp['user']['learning_student_id']})")


def _check_tts_backfill(sid: str, scenes: list[dict]) -> str:
    """TTS 后台补齐核对; 未配置/显式跳过 → 'skipped' (降级链即默认路径)."""
    if os.environ.get("CANARY_SKIP_TTS") == "1":
        print("[tts] CANARY_SKIP_TTS=1 → 跳过 (播放端走估算计时器降级链)")
        return "skipped"
    if not os.environ.get("COGEDU_TTS_API_KEY"):
        print("[tts] 未配置 COGEDU_TTS_API_KEY → 跳过 (speech 静音降级, 3-D-5 默认路径)")
        return "skipped"
    target = next(
        (s for s in scenes
         if any(a.get("type") == "speech" for a in (s.get("actions") or []))),
        None,
    )
    if target is None:
        return "no-speech"
    speech = next(a for a in (target.get("actions") or []) if a.get("type") == "speech")
    audio_id = f"tts_{target['scene_id']}_{speech['action_id']}"
    path = (f"/api/presentation/audio/{urllib.parse.quote(audio_id)}"
            f"?student_id={urllib.parse.quote(sid)}")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            # audio 端点返回二进制, 不走 req() 的 JSON 解析 — 只判 HTTP 状态
            r = urllib.request.Request(
                BASE + path, method="GET",
                headers={"Authorization": f"Bearer {_AUTH_TOKEN}"},
            )
            with urllib.request.urlopen(r, timeout=30) as resp:
                if resp.status == 200:
                    body = resp.read()
                    print(f"[tts] 后台补齐完成: {audio_id} "
                          f"({len(body)} bytes, {resp.headers.get('Content-Type')})")
                    return "ok"
        except Exception:
            pass
        time.sleep(2)
    print(f"[tts] 120s 内未等到 {audio_id} (后台线程可能仍在合成/失败降级)")
    return "timeout"


def _run_case(case: dict) -> dict:
    sid = case["sid"]
    _login_as(sid)
    print(f"\n{'=' * 70}\n[case] {sid}  skill={case['skill']}")

    # 答错 ×2 (对齐 1-G 口径: 证据量太小时 K 变化低于显示精度)
    for i in range(2):
        ans = req("POST", "/api/answer", {
            "student_id": sid, "problem_id": f"CANARY3-Q{i + 1}",
            "skill_id": case["skill"], "correct": False, "score": 0.0,
            "bloom_layer": "L3", "user_answer": case["wrong"],
        })
    theta_wrong = ans["theta"]
    print(f"[answer] theta after wrong x2: {theta_wrong}")

    outline = req("POST", "/api/presentation/outline", {
        "student_id": sid, "evidence_id": f"ev-{sid}",
    })
    print(f"[outline] {outline['outline_id']}  title={outline['title']}")

    scenes = req("POST", "/api/presentation/scenes", {
        "student_id": sid, "outline_id": outline["outline_id"],
    })
    print(f"[scenes] {len(scenes)} scenes, degraded={[s['degraded'] for s in scenes]}, "
          f"schema={[s.get('schema_version') for s in scenes]}")

    problems: list[str] = []
    scenes_with_actions = 0
    total_warnings = 0
    for idx, s in enumerate(scenes):
        if s.get("degraded"):
            problems.append(f"scene[{idx}] degraded")
        actions = s.get("actions") or []
        text = next((b["content"] for b in s["blocks"] if b["type"] == "text"), "")
        print(f"\n  ── 场景[{idx}] {s['title']}  schema={s.get('schema_version')}  "
              f"actions={len(actions)}  warnings={s.get('warnings')}")
        print(f"  讲解: {text[:300]}{'…' if len(text) > 300 else ''}")
        total_warnings += len(s.get("warnings") or [])
        if not actions:
            problems.append(f"scene[{idx}] 无动作序列")
            continue
        scenes_with_actions += 1
        for i, a in enumerate(actions):
            if a.get("type") not in WHITELIST:
                problems.append(f"scene[{idx}] action[{i}] 类型 {a.get('type')!r} 越白名单")
            if a.get("estimated_duration_ms") is None:
                problems.append(f"scene[{idx}] action[{i}] 缺 estimated_duration_ms")
            expected_prefix = f"{s['scene_id']}_a"
            if not str(a.get("action_id", "")).startswith(expected_prefix):
                problems.append(f"scene[{idx}] action[{i}] action_id 口径异常: {a.get('action_id')}")
        problems.extend(f"scene[{idx}] {p}" for p in _action_coord_issues(actions))
        # 完整动作序列打印 (人工复核: 节奏/公式/布局)
        print(f"  actions JSON:\n{json.dumps(actions, ensure_ascii=False, indent=2)}")

    # 3-E: timing 下发契约
    timing = req("GET", f"/api/presentation/timing?student_id={urllib.parse.quote(sid)}")
    timing_ok = isinstance(timing, dict) and timing.get("wb_draw_ms") == 800
    print(f"\n[timing] 下发 {timing if timing_ok else '❌ 异常: ' + str(timing)}")

    tts_status = _check_tts_backfill(sid, scenes)

    for idx, s in enumerate(scenes):
        req("POST", "/api/presentation/event", {
            "student_id": sid, "outline_id": outline["outline_id"],
            "event_type": "scene_viewed", "scene_id": s["scene_id"],
            "step_id": s["step_id"], "dwell_sec": 12.0 + idx, "index": idx,
        })
    req("POST", "/api/presentation/event", {
        "student_id": sid, "outline_id": outline["outline_id"],
        "event_type": "scene_completed", "scene_count": len(scenes),
        "total_dwell_sec": 60.0,
    })
    print("[event] scene_viewed x n + scene_completed → 200")

    ans = req("POST", "/api/answer", {
        "student_id": sid, "problem_id": "CANARY3-Q9", "skill_id": case["skill"],
        "correct": True, "score": 1.0, "bloom_layer": "L3", "user_answer": case["right"],
    })
    state = req("GET", f"/api/state/{sid}")
    k_moved = state["theta"]["K"] > theta_wrong["K"]
    print(f"[state] theta K: {theta_wrong['K']:.6f} → {state['theta']['K']:.6f}  (上移: {k_moved})")

    return {
        "sid": sid, "scenes": len(scenes),
        "scenes_with_actions": scenes_with_actions,
        "degraded": any(s["degraded"] for s in scenes),
        "problems": problems, "warnings_total": total_warnings,
        "timing_ok": timing_ok, "tts": tts_status, "k_moved_up": k_moved,
    }


def main() -> int:
    tmp_db = os.environ.get("ECOS_DB_PATH") or os.path.join(
        tempfile.mkdtemp(prefix="canary_p3_"), "canary.db"
    )
    env = dict(os.environ, ECOS_DB_PATH=tmp_db)
    print(f"[canary] db={tmp_db}, port={PORT}")
    # 服务日志落文件 (502 之类 LLM 侧失败要看 uvicorn stderr 定位)
    log_path = tmp_db + ".server.log"
    print(f"[canary] server log: {log_path}")
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "web.api.app:app",
         "--host", "127.0.0.1", "--port", str(PORT)],
        env=env, stdout=log_file, stderr=subprocess.STDOUT,
    )
    try:
        for _ in range(60):
            try:
                print(f"[canary] server up: {req('GET', '/api/version')}")
                break
            except Exception:
                time.sleep(1)
        else:
            print("[canary] server failed to start")
            return 1

        cases = [c for c in CASES if not _CASE_FILTER or c["sid"] in _CASE_FILTER]
        _provision_accounts([c["sid"] for c in cases])
        results = [_run_case(c) for c in cases]

        print(f"\n{'=' * 70}\n[canary] 汇总:")
        for r in results:
            print(f"  {r['sid']}: scenes={r['scenes']} 含动作={r['scenes_with_actions']} "
                  f"degraded={r['degraded']} warnings={r['warnings_total']} "
                  f"timing={r['timing_ok']} tts={r['tts']} K上移={r['k_moved_up']}")
            for p in r["problems"]:
                print(f"    ⚠️ {p}")
        ok = all(
            not r["degraded"] and r["scenes_with_actions"] > 0 and not r["problems"]
            and r["timing_ok"] and r["k_moved_up"] and r["tts"] in ("ok", "skipped", "no-speech")
            for r in results
        )
        print(f"[canary] {'✅ 脚本级通过 (动作序列质量需人工复核上方 JSON 输出)' if ok else '❌ 存在异常'}")
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
