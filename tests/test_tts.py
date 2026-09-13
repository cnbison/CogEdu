"""3-D-1/3: TTS 客户端 (MockTransport, 不发真实请求) 与长文本拆分测试."""
from __future__ import annotations

import httpx
import pytest

from cogedu.presentation.tts import (
    MiniMaxTTSClient,
    SpeechAction,
    TTSConfig,
    TTSSynthesisError,
    split_speech_action,
    split_speech_text,
    speech_max_chars,
)


# ─── 长文本三级拆分 (3-D-3) ─────────────────────────────────────────────────

class TestSplitSpeechText:
    def test_short_returns_single(self):
        assert split_speech_text("勾股定理讲解", 100) == ["勾股定理讲解"]

    def test_empty_and_whitespace(self):
        assert split_speech_text("", 100) == []
        assert split_speech_text("   \n  ", 100) == []

    def test_sentence_level_split(self):
        # 两段各自在限长内、总长超限 → 按句级标点切成 2 段 (分隔符保留段尾)
        text = "先看公式。" + "x" * 58
        parts = split_speech_text(text, 60)
        assert len(parts) == 2
        assert parts[0] == "先看公式。"
        assert len(parts[1]) == 58

    def test_clause_level_fallback(self):
        # 单句超长 → 二级按子句标点切
        text = "第一部分，" + "a" * 60 + "，第二部分，" + "b" * 60
        parts = split_speech_text(text, 60)
        assert len(parts) >= 2
        assert all(len(p) <= 70 for p in parts)  # 段尾带分隔符可略超

    def test_hard_cut_no_punctuation(self):
        text = "z" * 250
        parts = split_speech_text(text, 100)
        assert [len(p) for p in parts] == [100, 100, 50]

    def test_preserves_order(self):
        text = "。" .join(f"段{i}" + "字" * 80 for i in range(5)) + "。"
        parts = split_speech_text(text, 60)
        joined = "".join(parts)
        assert joined.index("段0") < joined.index("段1") < joined.index("段2")

    def test_invalid_max_chars(self):
        with pytest.raises(ValueError):
            split_speech_text("abc", 0)


class TestSplitSpeechAction:
    def _action(self, text: str) -> SpeechAction:
        return SpeechAction(action_id="a1", text=text, speed=1.2, audio_id="old")

    def test_within_limit_untouched(self):
        result = split_speech_action(self._action("短句"), 100)
        assert len(result) == 1
        assert result[0].action_id == "a1"

    def test_split_subactions(self):
        text = "。" .join("字" * 80 for _ in range(4)) + "。"
        result = split_speech_action(self._action(text), 100)
        assert len(result) >= 2
        assert result[0].action_id == "a1_0"
        assert result[1].action_id == "a1_1"
        assert all(a.audio_id is None for a in result)   # 拆分在音频回填前
        assert all(a.speed == 1.2 for a in result)

    def test_empty_text_drops(self):
        assert split_speech_action(self._action("  "), 100) == []


# ─── 配置 ──────────────────────────────────────────────────────────────────

class TestTTSConfig:
    def test_missing_key_raises(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("COGEDU_TTS_API_KEY", raising=False)
        with pytest.raises(TTSSynthesisError, match="COGEDU_TTS_API_KEY"):
            TTSConfig.from_env()

    def test_from_env_defaults(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("COGEDU_TTS_API_KEY", "k-test")
        monkeypatch.delenv("COGEDU_TTS_BASE_URL", raising=False)
        cfg = TTSConfig.from_env()
        assert cfg.base_url == "https://api.minimaxi.com"
        assert cfg.model == "speech-2.8-hd"
        assert cfg.voice == "female-yujie"

    def test_max_chars_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("COGEDU_TTS_MAX_TEXT_CHARS", "500")
        assert speech_max_chars() == 500
        monkeypatch.setenv("COGEDU_TTS_MAX_TEXT_CHARS", "bogus")
        assert speech_max_chars() == 2000   # 非法回退 + warning
        monkeypatch.delenv("COGEDU_TTS_MAX_TEXT_CHARS")
        assert speech_max_chars() >= 100


# ─── MiniMax 客户端 (MockTransport) ────────────────────────────────────────

def _client(handler) -> MiniMaxTTSClient:
    return MiniMaxTTSClient(
        TTSConfig(base_url="https://fake.minimax", api_key="k"),
        transport=httpx.MockTransport(handler),
    )


class TestMiniMaxClient:
    def test_success_hex_decode(self):
        audio_hex = "0011223344".replace("22", "22")
        payload = {
            "data": {"audio": "deadbeef"},
            "extra_info": {"audio_format": "mp3"},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            body = request.read()
            assert b"t2a_v2" not in body  # 路径在 URL 上
            assert request.url.path == "/v1/t2a_v2"
            assert request.headers["Authorization"] == "Bearer k"
            return httpx.Response(200, json=payload)

        result = _client(handler).generate("讲解文本")
        assert result.audio == bytes.fromhex("deadbeef")
        assert result.format == "mp3"

    def test_voice_speed_override(self):
        captured: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured.update(json.loads(request.read()))
            return httpx.Response(200, json={"data": {"audio": "ff"}, "extra_info": {}})

        _client(handler).generate("文本", voice="male-x", speed=1.5)
        assert captured["voice_setting"]["voice_id"] == "male-x"
        assert captured["voice_setting"]["speed"] == 1.5
        assert captured["model"] == "speech-2.8-hd"

    def test_http_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        with pytest.raises(TTSSynthesisError, match="401"):
            _client(handler).generate("文本")

    def test_missing_audio(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {}})

        with pytest.raises(TTSSynthesisError, match="缺音频"):
            _client(handler).generate("文本")

    def test_invalid_hex(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"audio": "xyz"}})

        with pytest.raises(TTSSynthesisError, match="hex"):
            _client(handler).generate("文本")

    def test_odd_hex_length(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"audio": "abc"}})

        with pytest.raises(TTSSynthesisError, match="hex"):
            _client(handler).generate("文本")
