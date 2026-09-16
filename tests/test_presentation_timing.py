"""3-E: 时间常数单一数据源测试.

覆盖: 常量/函数型估算 (与 3-C 引擎 JS 测试同口径) / 下发 payload 契约 /
**JS 兜底镜像漂移锁定** (playback.js + whiteboard.js 的内置默认值必须等于
Python 权威值 — 允许兜底镜像存在, 不允许漂移) / GET /timing 端点 +
scene.js 拉取接线。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cogedu.presentation.timing import (
    CJK_MS_PER_CHAR,
    CJK_RATIO_THRESHOLD,
    LATIN_MS_PER_WORD,
    SPEECH_MIN_MS,
    WB_DRAW_MS,
    WB_ENTER_MS,
    WB_STAGGER_MS,
    estimate_action_duration_ms,
    estimate_speech_duration_ms,
    timing_payload,
)
from cogedu.presentation.types import SpeechAction
from web.api.app import app

WEB_STUDENT = Path(__file__).resolve().parents[1] / "web" / "student"


# ─── 函数型估算 (与 tests/js/playback.test.cjs 同口径) ──────────────────────

class TestEstimateSpeech:
    def test_cjk_short_hits_floor(self):
        assert estimate_speech_duration_ms("一二三四五六七八九十") == 2000  # 10×150 < 2000

    def test_cjk_long(self):
        assert estimate_speech_duration_ms("字" * 20) == 3000

    def test_latin_short_hits_floor(self):
        assert estimate_speech_duration_ms("hello world foo") == 2000

    def test_latin_long(self):
        assert estimate_speech_duration_ms("a b c d e f g h i j") == 2400

    def test_speed_divides(self):
        assert estimate_speech_duration_ms("字" * 20, 2.0) == 1500

    def test_empty_hits_floor(self):
        assert estimate_speech_duration_ms("") == SPEECH_MIN_MS
        assert estimate_speech_duration_ms("   ") == SPEECH_MIN_MS


class TestEstimateAction:
    def test_wb_draw(self):
        assert estimate_action_duration_ms({"type": "wb_draw_text"}) == WB_DRAW_MS
        assert estimate_action_duration_ms({"type": "wb_draw_line"}) == WB_DRAW_MS

    def test_speech(self):
        assert estimate_action_duration_ms(
            {"type": "speech", "text": "一二三四五六七八九十"}
        ) == SPEECH_MIN_MS

    def test_speech_typed_model(self):
        assert estimate_action_duration_ms(
            SpeechAction(action_id="a", text="字" * 20, speed=1.0)
        ) == 3000

    def test_unknown_type_conservative(self):
        assert estimate_action_duration_ms({"type": "wb_nope"}) == WB_DRAW_MS


# ─── 下发 payload 契约 ──────────────────────────────────────────────────────

class TestTimingPayload:
    def test_keys_snake_case(self):
        assert set(timing_payload()) == {
            "wb_draw_ms", "wb_enter_ms", "wb_stagger_ms", "speech_min_ms",
            "cjk_ms_per_char", "latin_ms_per_word", "cjk_ratio_threshold",
        }

    def test_values_match_constants(self):
        payload = timing_payload()
        assert payload["wb_draw_ms"] == WB_DRAW_MS
        assert payload["wb_enter_ms"] == WB_ENTER_MS
        assert payload["wb_stagger_ms"] == WB_STAGGER_MS
        assert payload["speech_min_ms"] == SPEECH_MIN_MS
        assert payload["cjk_ms_per_char"] == CJK_MS_PER_CHAR
        assert payload["latin_ms_per_word"] == LATIN_MS_PER_WORD
        assert payload["cjk_ratio_threshold"] == CJK_RATIO_THRESHOLD


# ─── JS 兜底镜像漂移锁定 (允许镜像, 不允许漂移) ─────────────────────────────

def _js_number(js: str, name: str) -> float:
    m = re.search(rf"\b{name}:\s*([0-9.]+)", js)
    assert m, f"JS 兜底镜像缺 {name}"
    return float(m.group(1))


class TestJsMirrorDriftLock:
    def test_playback_defaults_match_python(self):
        js = (WEB_STUDENT / "playback.js").read_text(encoding="utf-8")
        assert _js_number(js, "wbDrawMs") == WB_DRAW_MS
        assert _js_number(js, "speechMinMs") == SPEECH_MIN_MS
        assert _js_number(js, "cjkMsPerChar") == CJK_MS_PER_CHAR
        assert _js_number(js, "latinMsPerWord") == LATIN_MS_PER_WORD
        assert _js_number(js, "cjkRatioThreshold") == CJK_RATIO_THRESHOLD

    def test_whiteboard_defaults_match_python(self):
        js = (WEB_STUDENT / "whiteboard.js").read_text(encoding="utf-8")
        assert _js_number(js, "enterMs") == WB_ENTER_MS
        assert _js_number(js, "staggerMs") == WB_STAGGER_MS


# ─── 端点与前端接线 ─────────────────────────────────────────────────────────

@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


class TestTimingEndpoint:
    def test_200_payload(self, client: TestClient):
        resp = client.get("/api/presentation/timing")
        assert resp.status_code == 200
        assert resp.json() == timing_payload()

    @pytest.mark.real_auth
    def test_student_with_own_id_200(self, client: TestClient, auth_factory):
        headers, user = auth_factory(username="stu_t", role="student",
                                     learning_student_id="stu_t")
        resp = client.get("/api/presentation/timing?student_id=stu_t",
                          headers=headers)
        assert resp.status_code == 200
        assert resp.json()["wb_draw_ms"] == WB_DRAW_MS

    def test_scene_page_fetches_timing(self):
        """前端接线 grep 契约: React ScenePage 拉取 timing, ScenePlayer 注入.

        双轨终点 (2026-09-16): 原 scene.js 锁迁移到 React 工程源文件。
        """
        pres = Path(__file__).resolve().parents[1] / "web" / "frontend" / "src" / "student" / "presentation"
        page = (pres / "ScenePage.tsx").read_text(encoding="utf-8")
        player = (pres / "ScenePlayer.tsx").read_text(encoding="utf-8")
        assert "getTiming(" in page      # 拉取端点
        assert "wb_draw_ms" in player    # 注入 engine 的映射存在

