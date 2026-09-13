"""3-D-2: 音频时长字节嗅探测试.

样本全部测试内合成 (WAV 用 struct 拼 RIFF; MP3 手工构帧头 + Xing tag),
不依赖任何音频资产文件。覆盖: WAV 精确解析 / Xing 帧数优先 / CBR 兜底 /
ID3 前缀跳过 / 垃圾与截断输入 None 降级。
"""
from __future__ import annotations

import struct

from cogedu.presentation.audio_duration import measure_audio_duration


def make_wav(duration_ms: int, sample_rate: int = 8000) -> bytes:
    """16-bit 单声道 PCM WAV: duration = dataSize / byteRate."""
    byte_rate = sample_rate * 2
    data_size = int(byte_rate * duration_ms / 1000)
    fmt = struct.pack("<HHIIHH", 1, 1, sample_rate, byte_rate, 2, 16)
    return (
        b"RIFF" + struct.pack("<I", 36 + data_size) + b"WAVE"
        + b"fmt " + struct.pack("<I", 16) + fmt
        + b"data" + struct.pack("<I", data_size)
        + b"\x00" * data_size
    )


def make_mp3_frame_header(version: int = 3, sample_rate_idx: int = 0,
                          bitrate_idx: int = 9, padding: int = 0) -> bytes:
    # b0=0xFF; b1: sync(111) + version + layer(01=III) + no CRC
    b1 = 0xFB | ((version & 0x03) << 3) & 0xFF  # 0xFB = MPEG1 Layer3
    if version != 3:
        b1 = 0xFF | 0xE0 | (version << 3) | 0x02
    b2 = (bitrate_idx << 4) | 0x00
    b3 = (sample_rate_idx << 2) | (padding << 1)
    return bytes([0xFF, b1, b2, b3])


def make_mp3_xing(frames: int) -> bytes:
    """MPEG1 Layer3 128kbps 44.1kHz, 带 Xing 帧数 tag."""
    header = make_mp3_frame_header()  # 128kbps → frame_len 417
    xing = b"Xing" + struct.pack(">I", 0x01) + struct.pack(">I", frames)
    body = header + b"\x00" * 100 + xing + b"\x00" * 300
    return body.ljust(417 * max(frames, 1), b"\x00")


class TestWav:
    def test_exact_duration(self):
        # 1000ms @ 8kHz: dataSize/byteRate = 1.0s
        assert measure_audio_duration(make_wav(1000)) == 1000

    def test_fractional(self):
        # 250ms
        assert measure_audio_duration(make_wav(250)) == 250

    def test_truncated_no_data_chunk(self):
        header_only = make_wav(1000)[:44]  # 只有 44 字节头
        assert measure_audio_duration(header_only) is None


class TestMp3:
    def test_xing_frames_priority(self):
        # 10 帧 × 1152 / 44100 ≈ 261ms (帧数优先, 与文件体积无关)
        expected = int(10 * 1152 / 44100 * 1000)
        assert measure_audio_duration(make_mp3_xing(10)) == expected

    def test_cbr_fallback_no_xing(self):
        # 无 Xing tag: 全文件按首帧码率 (128kbps) 估算
        audio = make_mp3_frame_header() + b"\x00" * 16000
        expected = int(16004 * 8 / (128 * 1000) * 1000)
        assert measure_audio_duration(audio) == expected

    def test_id3_prefix_skipped(self):
        # ID3v2: 'ID3' + 版本(2) + 标志(1) + syncsafe size(4) = 10 字节, size 0
        tag = b"ID3" + b"\x04\x00" + b"\x00" + b"\x00\x00\x00\x00"
        audio = tag + make_mp3_xing(5)
        expected = int(5 * 1152 / 44100 * 1000)
        assert measure_audio_duration(audio) == expected

    def test_invalid_header(self):
        assert measure_audio_duration(b"\x00" * 100) is None


class TestDegrade:
    def test_empty(self):
        assert measure_audio_duration(b"") is None

    def test_garbage(self):
        assert measure_audio_duration(b"not audio at all" * 10) is None

    def test_truncated_mp3(self):
        assert measure_audio_duration(b"\xff\xfb") is None
