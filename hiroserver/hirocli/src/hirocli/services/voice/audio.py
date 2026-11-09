"""Audio formats (Phase 7b, ported from HomeHiro's ``tts/audio.py``).

The providers hand back raw PCM (16-bit mono); each output is encoded once from there. Opus is encoded
in-process with PyAV (its wheels bundle ffmpeg and libopus), so no ffmpeg binary is needed.
"""

from __future__ import annotations

import array
import io
import math
import wave

import av

PCM_RATE = 24000  # both providers' native rate
WAVEFORM_BARS = 64  # WhatsApp draws a voice note's bars from 64 values, 0..100


def pcm_seconds(pcm: bytes, rate: int = PCM_RATE) -> float:
    return len(pcm) / 2 / rate


def wav_to_pcm(data: bytes) -> tuple[bytes, int]:
    """(16-bit mono PCM, sample rate) from a WAV file, e.g. Gemini's designed-voice sample."""
    with wave.open(io.BytesIO(data)) as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError("expected 16-bit mono WAV")
        return w.readframes(w.getnframes()), w.getframerate()


def to_ogg_opus(pcm: bytes, rate: int = PCM_RATE) -> bytes:
    """OGG/Opus as WhatsApp records voice notes: mono, 48 kHz, 32 kbps, tuned for speech."""
    frame = av.AudioFrame(format="s16", layout="mono", samples=len(pcm) // 2)
    frame.planes[0].update(pcm[: len(pcm) - len(pcm) % 2])
    frame.sample_rate = rate
    buf = io.BytesIO()
    with av.open(buf, "w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=48000, layout="mono")
        stream.bit_rate = 32000
        stream.options = {"application": "voip"}
        resampler = av.AudioResampler(format="s16", layout="mono", rate=48000)
        for resampled in [*resampler.resample(frame), *resampler.resample(None)]:
            for packet in stream.encode(resampled):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return buf.getvalue()


def waveform(pcm: bytes) -> bytes:
    """WhatsApp's 64-byte loudness envelope (RMS per slice, scaled to the loudest slice)."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    total = len(samples)
    if total == 0:
        return b""
    rms = []
    for i in range(WAVEFORM_BARS):
        chunk = samples[i * total // WAVEFORM_BARS : (i + 1) * total // WAVEFORM_BARS]
        rms.append(math.sqrt(sum(v * v for v in chunk) / len(chunk)) if chunk else 0.0)
    peak = max(rms) or 1.0
    return bytes(min(100, int(v / peak * 100)) for v in rms)
