"""OpenAI speech: POST /v1/audio/speech, raw PCM back (24 kHz, 16-bit mono). Phase 7b, from HomeHiro.

Sound tags are taken out (OpenAI would read them aloud). The style goes as ``instructions`` (only
gpt-4o-mini-tts takes them); ``speed`` is OpenAI's own. No usage comes back, so the cost is estimated.
"""

from __future__ import annotations

from .audio import PCM_RATE, pcm_seconds
from .kit import CHARS_PER_TOKEN, Speech, speech_cost, strip_tags
from .net import VoiceError, send

URL = "https://api.openai.com/v1/audio/speech"
STYLED = ("gpt-4o-mini-tts",)  # the models that take instructions (a dated gpt-4o-mini-tts-… too)


async def speak(text: str, *, api_key: str, model: str, voice: str, style: str = "", speed: float = 1.0) -> Speech:
    said = strip_tags(text)
    if not said:
        raise VoiceError("Nothing to say once the sound tags are taken out (OpenAI would read them aloud)", 400)
    body: dict[str, object] = {"model": model, "input": said, "voice": voice, "response_format": "pcm", "speed": speed}
    styled = model.startswith(STYLED) and bool(style.strip())
    if styled:
        body["instructions"] = style.strip()
    r = await send("POST", URL, provider="OpenAI", json=body, headers={"Authorization": f"Bearer {api_key}"})
    if len(r.content) < 2:  # not one 16-bit sample: nothing to encode
        raise VoiceError("OpenAI: the answer had no audio")
    seconds = pcm_seconds(r.content)
    text_tokens = (len(said) + (len(style.strip()) if styled else 0)) // CHARS_PER_TOKEN
    cost = speech_cost("openai", model, characters=len(said), text_tokens=text_tokens, audio_seconds=seconds)
    return Speech(r.content, PCM_RATE, seconds, cost, cost_exact=False, tokens_in=text_tokens)
