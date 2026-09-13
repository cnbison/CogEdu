"""Phase 3 (3-E, 15.6): 时间常数单一数据源.

照搬 OpenMAIC ``lib/choreography/timing.ts`` 的模式 + CogEdu 特有的
跨语言问题: Python 生成侧 (3-F 填动作的 ``estimated_duration_ms``) 与
JS 播放端 (3-C 引擎的无音频估算兜底、白板入场动画) 消费同一套数字,
两份手抄必然漂移 — 本模块是唯一权威源:

- 生成侧直接 import 本模块 (``estimate_action_duration_ms``);
- 前端经 ``GET /api/presentation/timing`` 下发 (scene.js 注入
  playback engine / whiteboard);
- JS 侧保留**兜底镜像** (timing 下发失败时页面仍可用), 但镜像数值被
  pytest 契约测试与 Python 权威值逐一锁定 (test_presentation_timing.py),
  防漂移。

纯模块: 不 import web/fastapi (边界纪律对齐 OpenMAIC timing.ts
"不依赖 React/DOM", 文件头声明 + eslint 边界规则强制, 这里由包边界
约定 + 零 mutation 扫描覆盖)。

数值对齐 OpenMAIC timing.ts 实测值 (WB_DRAW_MS=800 / 入场 450ms /
stagger 50ms / 语音估算 CJK 150ms/字 ≈250WPM 英文 240ms/词), 收口可调。
"""
from __future__ import annotations

from typing import Any

# ─── 纯常量 ────────────────────────────────────────────────────────────────

WB_DRAW_MS = 800            # 每个白板动作的讲解节奏间隔
WB_ENTER_MS = 450           # 白板元素入场动画时长 (3-B-4)
WB_STAGGER_MS = 50          # 入场级联间隔 (按元素序号递增)
SPEECH_MIN_MS = 2000        # 语音估算时长下限
CJK_MS_PER_CHAR = 150       # 中文每字毫秒
LATIN_MS_PER_WORD = 240     # 英文每词毫秒 (≈250 WPM)
CJK_RATIO_THRESHOLD = 0.3   # CJK 占比超过此值按中文语速估算


# ─── 函数型常量 (按内容长度计算, 与纯常量分列 — 15.6 3-E-2) ─────────────────

def estimate_speech_duration_ms(text: str, speed: float = 1.0) -> int:
    """无音频时 speech 动作的估算时长 (ms).

    播放兜底 (3-C 引擎) 与生成侧 ``estimated_duration_ms`` 同源计算。
    CJK 占比 > 阈值 → max(SPEECH_MIN_MS, 字数×CJK_MS_PER_CHAR);
    否则按词 → max(SPEECH_MIN_MS, 词数×LATIN_MS_PER_WORD); 最后除以 speed。
    """
    stripped = (text or "").strip()
    chars = "".join(stripped.split())
    if not chars:
        return SPEECH_MIN_MS
    cjk = sum(1 for ch in chars if "㐀" <= ch <= "鿿")
    if cjk / len(chars) > CJK_RATIO_THRESHOLD:
        duration = max(SPEECH_MIN_MS, cjk * CJK_MS_PER_CHAR)
    else:
        duration = max(SPEECH_MIN_MS, len(stripped.split()) * LATIN_MS_PER_WORD)
    return round(duration / max(speed, 0.1))


def estimate_action_duration_ms(action: Any) -> int:
    """单个动作的预计时长 (3-F 填 ``estimated_duration_ms`` 用).

    wb_* → WB_DRAW_MS; speech → estimate_speech_duration_ms;
    未知类型 → WB_DRAW_MS (保守兜底, 与引擎跳过前 0 等待不冲突:
    此估算值只做展示/导出用)。接受 SpeechAction 或 dict。
    """
    if isinstance(action, dict):
        action_type = action.get("type")
        text = action.get("text", "")
        speed = action.get("speed", 1.0)
    else:
        action_type = getattr(action, "type", None)
        text = getattr(action, "text", "") or ""
        speed = getattr(action, "speed", 1.0) or 1.0
    if action_type == "speech":
        return estimate_speech_duration_ms(text, speed)
    return WB_DRAW_MS


def timing_payload() -> dict[str, int | float]:
    """下发前端的常量集 (GET /api/presentation/timing, snake_case)."""
    return {
        "wb_draw_ms": WB_DRAW_MS,
        "wb_enter_ms": WB_ENTER_MS,
        "wb_stagger_ms": WB_STAGGER_MS,
        "speech_min_ms": SPEECH_MIN_MS,
        "cjk_ms_per_char": CJK_MS_PER_CHAR,
        "latin_ms_per_word": LATIN_MS_PER_WORD,
        "cjk_ratio_threshold": CJK_RATIO_THRESHOLD,
    }
