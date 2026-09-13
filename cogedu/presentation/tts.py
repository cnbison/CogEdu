"""Phase 3 (3-D, 15.5): 语音合成集成 — MiniMax TTS 单供应商 + 长文本拆分.

设计要点 (方案文档 15.5, v0.6 四项决策之"TTS 异步补齐 + 播放端降级"):

- **单供应商** (v0.6 拍板): MiniMax TTS。CogEdu LLM 已用 MiniMax,
  零新增供应商; v1 不做多供应商注册表。
- **接口不含时长** (3-D-2): OpenMAIC 同款 — TTSResult 只有 audio bytes
  + format。播放调度不消费音频时长 (3-C 引擎 ended 事件驱动), 时长在
  **入库时**由 ``audio_duration.measure_audio_duration`` 字节嗅探测一次,
  供记录/未来导出。
- **Protocol 注入** 对齐 presentation 包的 SupportsChat 模式: 调用方构造
  时注入, 本模块不绑 web 层; MiniMaxTTSClient 的 httpx transport 可注入
  (测试用 MockTransport, 不发真实请求)。
- API 形态参考 OpenMAIC ``tts-providers.ts`` generateMiniMaxTTS (T2A v2,
  hex 音频回传), Python 重写, 无任何运行时引用。
- **限长常量**: MiniMax 官方限长未在线核实, 默认保守值 2000 字符
  (env 可配); 3-G 灰度时用真实长文本核实修正。
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

from cogedu.presentation.types import SpeechAction

_log = logging.getLogger(__name__)


class TTSSynthesisError(Exception):
    """TTS 合成失败 (HTTP 错误 / 响应缺音频 / hex 非法). 上游供应商问题."""


# ─── 配置 ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TTSConfig:
    """TTS 供应商配置 (对齐 LLMConfig 的 env 注入口径).

    默认指向 MiniMax 国内平台 (api.minimaxi.com, OpenMAIC 同款);
    COGEDU_TTS_API_KEY 缺失时 from_env 抛错并给出指引。
    """

    base_url: str
    api_key: str
    model: str = "speech-2.8-hd"
    voice: str = "female-yujie"
    timeout_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "TTSConfig":
        api_key = os.environ.get("COGEDU_TTS_API_KEY", "").strip()
        if not api_key:
            raise TTSSynthesisError(
                "COGEDU_TTS_API_KEY 未设置。请在环境变量中配置 MiniMax API Key"
                "（语音合成 v1 使用 MiniMax 单供应商）。"
            )
        return cls(
            base_url=os.environ.get("COGEDU_TTS_BASE_URL", "").strip()
            or "https://api.minimaxi.com",
            api_key=api_key,
            model=os.environ.get("COGEDU_TTS_MODEL", "").strip() or "speech-2.8-hd",
            voice=os.environ.get("COGEDU_TTS_VOICE", "").strip() or "female-yujie",
        )


# 长文本拆分阈值 (3-D-3): 未在线核实的保守默认, env 可配
def speech_max_chars() -> int:
    raw = os.environ.get("COGEDU_TTS_MAX_TEXT_CHARS", "").strip()
    try:
        value = int(raw) if raw else 2000
    except ValueError:
        _log.warning("COGEDU_TTS_MAX_TEXT_CHARS 非法 (%r), 回退 2000", raw)
        value = 2000
    return max(value, 100)


# ─── 统一接口 (Protocol, 不绑具体 SDK) ─────────────────────────────────────

@dataclass(frozen=True)
class TTSResult:
    """合成结果 — 刻意不含时长 (3-D-2, 见模块 docstring)."""

    audio: bytes
    format: str  # "mp3" / "wav"


class SupportsTTS(Protocol):
    """TTS 客户端最小协议 (3-F 生成侧依赖此协议, 不绑 MiniMax 实现)."""

    def generate(self, text: str, *, voice: str | None = None, speed: float = 1.0) -> TTSResult:
        """合成语音。失败抛 TTSSynthesisError (调用方决定降级路径)."""
        ...


# ─── MiniMax 实现 (T2A v2) ─────────────────────────────────────────────────

class MiniMaxTTSClient:
    """MiniMax T2A v2 HTTP 客户端.

    transport 参数仅供测试注入 httpx.MockTransport; 生产不传。
    """

    def __init__(self, config: TTSConfig, transport: Any = None) -> None:
        import httpx

        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def generate(self, text: str, *, voice: str | None = None, speed: float = 1.0) -> TTSResult:
        payload = {
            "model": self.config.model,
            "text": text,
            "stream": False,
            "output_format": "hex",
            "voice_setting": {
                "voice_id": voice or self.config.voice,
                "speed": speed,
                "vol": 1,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
            "language_boost": "auto",
        }
        try:
            resp = self._client.post(
                "/v1/t2a_v2",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json; charset=utf-8",
                },
            )
        except Exception as e:
            raise TTSSynthesisError(f"MiniMax TTS 请求失败: {e}") from e

        if resp.status_code != 200:
            raise TTSSynthesisError(
                f"MiniMax TTS API error: HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        hex_audio = (data.get("data") or {}).get("audio")
        if not isinstance(hex_audio, str) or not hex_audio.strip():
            raise TTSSynthesisError(
                f"MiniMax TTS 响应缺音频: {str(data)[:200]}"
            )
        cleaned = hex_audio.strip()
        if len(cleaned) % 2 != 0 or not re.fullmatch(r"[0-9a-fA-F]+", cleaned):
            raise TTSSynthesisError("MiniMax TTS hex 音频载荷非法")
        try:
            audio = bytes.fromhex(cleaned)
        except ValueError as e:
            raise TTSSynthesisError("MiniMax TTS hex 音频解码失败") from e
        fmt = (data.get("extra_info") or {}).get("audio_format") or "mp3"
        return TTSResult(audio=audio, format=str(fmt))


# ─── 长文本拆分 (3-D-3): 句级 → 子句级 → 硬切 三级降级 ──────────────────────

_SENTENCE_SEPS = "。！？!?；;：:\n"
_CLAUSE_SEPS = "，,、"


def _split_keep(text: str, seps: str) -> list[str]:
    """按标点切分, 分隔符保留在段尾 (不做字节拼接, 各段独立合成)."""
    parts: list[str] = []
    buf: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in seps:
            parts.append("".join(buf))
            buf = []
    if buf:
        parts.append("".join(buf))
    return parts


def split_speech_text(text: str, max_chars: int) -> list[str]:
    """超长讲解文本按三级降级拆分 (OpenMAIC splitLongSpeechText 同思路).

    返回各段 (空段剔除)。保序; 每段独立合成独立音频, 不做字节拼接。
    """
    if max_chars < 1:
        raise ValueError("max_chars 必须 >= 1")
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= max_chars:
        return [stripped]

    pieces: list[str] = []
    for seg in _split_keep(stripped, _SENTENCE_SEPS):
        if len(seg) <= max_chars:
            pieces.append(seg)
            continue
        for sub in _split_keep(seg, _CLAUSE_SEPS):
            if len(sub) <= max_chars:
                pieces.append(sub)
                continue
            pieces.extend(sub[i : i + max_chars] for i in range(0, len(sub), max_chars))
    return [p for p in (piece.strip() for piece in pieces) if p]


def split_speech_action(action: SpeechAction, max_chars: int) -> list[SpeechAction]:
    """超长 speech 动作拆成多个连续 speech 动作 (OpenMAIC splitLongSpeechActions
    同思路): action_id 后缀 ``_{i}``, voice/speed 保留, audio_id 置空
    (拆分发生在音频回填之前)。不超长时原样返回单元素列表。"""
    segments = split_speech_text(action.text, max_chars)
    if not segments:
        return []
    if len(segments) == 1:
        return [action]
    return [
        SpeechAction(
            action_id=f"{action.action_id}_{i}",
            estimated_duration_ms=action.estimated_duration_ms,
            text=seg,
            voice=action.voice,
            speed=action.speed,
            audio_id=None,
        )
        for i, seg in enumerate(segments)
    ]
