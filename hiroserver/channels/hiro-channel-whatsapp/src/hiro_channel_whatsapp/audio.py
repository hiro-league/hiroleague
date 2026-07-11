"""MP3 → OGG/Opus transcoding for outbound WhatsApp voice notes (P7).

The TTS pipeline yields MP3 (``audio/mpeg``); a *native* WhatsApp voice-note
bubble requires ``audio/ogg`` (Opus) with ``PTT=true`` — MP3-as-PTT renders as a
broken/greyed clip on Android (design §9). So this transcode is mandatory, not a
nicety: it turns the reply audio into a real voice note.

ffmpeg discovery: honour an explicit ``HIRO_WHATSAPP_FFMPEG`` override, else pick
up ``ffmpeg`` from PATH. NOTE: neonize's own ``build_audio_message`` also shells
out to ``ffmpeg``/``ffprobe`` at send time (to probe duration), so a working
ffmpeg install on PATH is a hard requirement for outbound audio regardless of
this module — see docs/whatsapp-channel-implementation.md P8 (ffmpeg provisioning).
"""

from __future__ import annotations

import array
import asyncio
import math
import os
import shutil

from hiro_commons.log import Logger

log = Logger.get("WHATSAPP.AUDIO")

# WhatsApp renders a voice note's bars from a fixed-length amplitude envelope on
# the AudioMessage.waveform field: 64 bytes, each 0..100. Empty → flat placeholder.
_WAVEFORM_SAMPLES = 64

# Env override for a non-PATH ffmpeg binary (e.g. a bundled/static build).
_FFMPEG_ENV = "HIRO_WHATSAPP_FFMPEG"

# Opus encode settings tuned for speech, matching how the WhatsApp app records
# voice notes: mono, VoIP-optimised Opus in an Ogg container. 32 kbps mono is
# transparent for voice while keeping the clip small.
_OPUS_ARGS = [
    "-c:a", "libopus",
    "-b:a", "32k",
    "-ac", "1",
    "-ar", "48000",
    "-application", "voip",
]


class TranscodeError(RuntimeError):
    """Raised when the MP3 → OGG/Opus transcode cannot be completed."""


def find_ffmpeg() -> str | None:
    """Locate the ffmpeg binary: env override first, then PATH. None if absent."""
    override = os.environ.get(_FFMPEG_ENV, "").strip()
    if override:
        return override if os.path.isfile(override) else None
    return shutil.which("ffmpeg")


def _have(binary: str) -> bool:
    return shutil.which(binary) is not None


async def ensure_ffmpeg_on_path() -> bool:
    """Best-effort: guarantee ``ffmpeg`` AND ``ffprobe`` are on this process's PATH.

    Prefers a system install; otherwise provisions the bundled ``static-ffmpeg``
    binaries (downloaded + cached on first call — run off the event loop). neonize
    needs ``ffprobe`` too (its build_audio_message shells it at send time), so we
    require both. Returns True when both are available; never raises — a miss just
    means voice replies fall back to sending the audio as a file.
    """
    if _have("ffmpeg") and _have("ffprobe"):
        return True
    try:
        import static_ffmpeg  # optional dep; bundles ffmpeg + ffprobe
    except ImportError:
        log.warning(
            "⚠️ ffmpeg/ffprobe not on PATH and static-ffmpeg is not installed — "
            "outbound voice will fall back to sending audio as a file"
        )
        return False
    try:
        # add_paths downloads the binaries on first use and mutates os.environ PATH;
        # it is blocking, so keep it off the event loop. weak=True defers to any
        # system ffmpeg already present.
        await asyncio.to_thread(static_ffmpeg.add_paths, weak=True)
    except Exception as exc:  # network/extract failure — best-effort, log and go on
        log.warning("⚠️ Could not provision bundled ffmpeg", error=str(exc))
        return False
    ok = _have("ffmpeg") and _have("ffprobe")
    if ok:
        log.info("🎬 ffmpeg/ffprobe ready for outbound voice")
    else:
        log.warning("⚠️ ffmpeg provisioning ran but binaries still not on PATH")
    return ok


async def transcode_to_ogg_opus(src: bytes) -> bytes:
    """Transcode arbitrary audio bytes (MP3 from TTS) to OGG/Opus bytes.

    Streams via ffmpeg stdin→stdout (no temp files). Raises ``TranscodeError`` on
    a missing binary, a non-zero exit, or empty output so the caller can fall back.
    """
    if not src:
        raise TranscodeError("no input audio bytes")
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise TranscodeError(
            f"ffmpeg not found (set {_FFMPEG_ENV} or add ffmpeg to PATH)"
        )
    args = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        *_OPUS_ARGS,
        "-f", "ogg", "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate(input=src)
    except OSError as exc:  # binary vanished / not executable between find and spawn
        raise TranscodeError(f"could not run ffmpeg: {exc}") from exc
    if proc.returncode != 0 or not out:
        detail = err.decode("utf-8", "replace").strip()[:300] if err else ""
        raise TranscodeError(f"ffmpeg exited {proc.returncode}: {detail}")
    log.info(
        "🎙️ Transcoded reply audio → OGG/Opus",
        in_size=len(src),
        out_size=len(out),
    )
    return out


async def compute_waveform(ogg_opus: bytes) -> bytes:
    """Build WhatsApp's 64-byte amplitude envelope (0..100) for a voice note.

    Decodes the clip to mono 8 kHz 16-bit PCM via ffmpeg (8 kHz is ample for a
    64-bar envelope and keeps the RMS pass cheap), then RMS-reduces to 64 buckets
    normalized to the loudest bucket. Best-effort: returns ``b""`` on any failure —
    the note still plays, just with a flat placeholder instead of bars.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not ogg_opus:
        return b""
    args = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-i", "pipe:0",
        "-ac", "1", "-ar", "8000", "-f", "s16le", "pipe:1",
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        pcm, err = await proc.communicate(input=ogg_opus)
    except OSError as exc:
        log.warning("⚠️ Could not run ffmpeg for waveform", error=str(exc))
        return b""
    if proc.returncode != 0 or not pcm:
        detail = err.decode("utf-8", "replace").strip()[:200] if err else ""
        log.warning("⚠️ Waveform PCM decode failed", returncode=proc.returncode, detail=detail)
        return b""
    return _rms_envelope(pcm)


def _rms_envelope(pcm: bytes) -> bytes:
    """Reduce signed 16-bit mono PCM to a 64-byte 0..100 RMS envelope."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - (len(pcm) % 2)])  # 16-bit frames must be even
    total = len(samples)
    if total == 0:
        return b""
    rms: list[float] = []
    for i in range(_WAVEFORM_SAMPLES):
        # Proportional bucket bounds so every sample lands in exactly one bucket.
        start = i * total // _WAVEFORM_SAMPLES
        end = (i + 1) * total // _WAVEFORM_SAMPLES
        chunk = samples[start:end]
        if not chunk:
            rms.append(0.0)
            continue
        rms.append(math.sqrt(sum(v * v for v in chunk) / len(chunk)))
    peak = max(rms) or 1.0
    return bytes(min(100, int(value / peak * 100)) for value in rms)
