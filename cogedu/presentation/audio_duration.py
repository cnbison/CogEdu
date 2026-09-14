"""Phase 3 (3-D-2, 15.5): 音频时长字节嗅探.

``measure_audio_duration(audio: bytes) -> int | None`` (毫秒) — 入库时
测一次存库, 供记录/未来视频导出; **播放调度不消费** (3-C 引擎 ended
事件驱动, 估算计时器兜底)。

设计来源: OpenMAIC ``audio-duration.ts`` (~330 行) 的思路, Python 重写——
- 靠 magic bytes 嗅探格式, 不信任调用方声明的 format;
- WAV: RIFF chunk 走查, duration = dataSize / byteRate;
- MP3: 首帧头解析 (版本/层/码率/采样率), Xing/Info 帧数优先,
  CBR 估算兜底;
- 任何解析失败返回 **None 优雅降级** (对齐"宁可明确降级不静默"——
  调用方拿 None 落 duration_ms=NULL 并 warning, 不抛异常不猜数)。
"""
from __future__ import annotations

import struct

# MPEG 版本 (header byte 1 的高位) → 采样率表 (Layer III)
_SAMPLE_RATES: dict[int, list[int]] = {
    3: [44100, 48000, 32000],   # MPEG1
    2: [22050, 24000, 16000],   # MPEG2
    0: [11025, 12000, 8000],    # MPEG2.5
}
# Layer III 码率表 (kbps), index = header byte 2 高 4 位
_BITRATES_V1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
_BITRATES_V2_L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]


def measure_audio_duration(audio: bytes) -> int | None:
    """嗅探音频字节数并返回时长 (ms); 解析失败返回 None."""
    if not audio:
        return None
    try:
        if audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
            return _wav_duration_ms(audio)
        if audio[:3] == b"ID3" or (
            len(audio) > 1 and audio[0] == 0xFF and (audio[1] & 0xE0) == 0xE0
        ):
            return _mp3_duration_ms(audio)
    except Exception:  # noqa: BLE001 — 任何嗅探失败都按"测不出"降级
        return None
    return None


# ─── WAV: RIFF chunk 走查 ───────────────────────────────────────────────────

def _wav_duration_ms(audio: bytes) -> int | None:
    byte_rate: int | None = None
    data_size: int | None = None
    offset = 12  # 跳过 RIFF 头 (RIFF + size + WAVE)
    while offset + 8 <= len(audio):
        chunk_id = audio[offset : offset + 4]
        (chunk_size,) = struct.unpack_from("<I", audio, offset + 4)
        if chunk_id == b"fmt " and chunk_size >= 16:
            # fmt chunk: audioFormat(2) channels(2) sampleRate(4) byteRate(4)...
            (byte_rate,) = struct.unpack_from("<I", audio, offset + 8 + 8)
        elif chunk_id == b"data":
            available = len(audio) - (offset + 8)
            if chunk_size == 0 or available < chunk_size:
                return None  # 空 data 或声明长度被截断 — 不可信, 不猜数
            data_size = chunk_size
        offset += 8 + chunk_size + (chunk_size % 2)  # chunk 按 word 对齐
        if data_size is not None and byte_rate is not None:
            break
    if not byte_rate or data_size is None:
        return None
    return int(data_size / byte_rate * 1000)


# ─── MP3: 帧头 + Xing/Info 帧数优先, CBR 兜底 ───────────────────────────────

def _mp3_duration_ms(audio: bytes) -> int | None:
    offset = 0
    if audio[:3] == b"ID3":  # 跳过 ID3v2 tag (syncsafe size)
        if len(audio) < 10:
            return None
        tag_size = (
            (audio[6] & 0x7F) << 21
            | (audio[7] & 0x7F) << 14
            | (audio[8] & 0x7F) << 7
            | (audio[9] & 0x7F)
        )
        offset = 10 + tag_size
    if len(audio) < offset + 4:
        return None

    b0, b1, b2, b3 = audio[offset], audio[offset + 1], audio[offset + 2], audio[offset + 3]
    if b0 != 0xFF or (b1 & 0xE0) != 0xE0:
        return None
    version = (b1 >> 3) & 0x03       # 3=MPEG1, 2=MPEG2, 0=MPEG2.5
    layer = (b1 >> 1) & 0x03         # 1=Layer III
    if layer != 1 or version not in _SAMPLE_RATES:
        return None
    bitrate_idx = (b2 >> 4) & 0x0F
    # 帧头位布局: byte2 = bitrate(4) + 采样率(2, bits 3-2) + padding(1) + private(1);
    # 采样率不在 byte3（此前误读 b3 bits 3-2, 32000Hz 被算成 44100 → 时长
    # 短 1.378 倍, 3-G 真实 TTS 验收发现）
    sample_rate_idx = (b2 >> 2) & 0x03
    padding = (b2 >> 1) & 0x01
    rates = _SAMPLE_RATES[version]
    if sample_rate_idx >= len(rates):
        return None
    sample_rate = rates[sample_rate_idx]
    bitrate_table = _BITRATES_V1_L3 if version == 3 else _BITRATES_V2_L3
    if bitrate_idx == 0 or bitrate_idx >= len(bitrate_table):
        return None
    bitrate_kbps = bitrate_table[bitrate_idx]
    samples_per_frame = 1152 if version == 3 else 576
    frame_len = int(samples_per_frame / 8 * bitrate_kbps * 1000 / sample_rate) + padding

    # Xing/Info 头: 首帧内搜 (side info 长度随模式不同, 搜索窗内找)
    window = audio[offset : offset + frame_len + 64]
    xing_pos = window.find(b"Xing")
    info_pos = window.find(b"Info")
    tag_pos = xing_pos if xing_pos != -1 else info_pos
    if tag_pos != -1 and tag_pos + 8 <= len(window):
        (flags,) = struct.unpack_from(">I", window, tag_pos + 4)
        if flags & 0x01 and tag_pos + 12 <= len(window):
            (frames,) = struct.unpack_from(">I", window, tag_pos + 8)
            if frames > 0:
                return int(frames * samples_per_frame / sample_rate * 1000)

    # CBR 兜底: 全文件按首帧码率估算
    payload = len(audio) - offset
    if bitrate_kbps <= 0:
        return None
    return int(payload * 8 / (bitrate_kbps * 1000) * 1000)
