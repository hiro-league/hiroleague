"""Reading an ``ai.ask``'s params (wire JSON) into an ``AskRequest`` — refusals are ``invalid``."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from hiro_channel_sdk.constants import AI_ERROR_INVALID

from .errors import AskError
from .runner import AskRequest

MAX_PICTURES = 60  # the most a use may declare (StudyHiro's study reviews)


def decode_b64(value: Any, what: str) -> bytes:
    """Base64 (a ``data:…;base64,`` prefix allowed) → bytes, or AskError invalid."""
    if not isinstance(value, str) or not value.strip():
        raise AskError(AI_ERROR_INVALID, f"{what} must be base64 text.")
    text = value.strip()
    if text.startswith("data:") and "," in text:
        text = text.split(",", 1)[1]
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AskError(AI_ERROR_INVALID, f"{what} isn't valid base64.") from exc


def ask_request_from_params(params: dict[str, Any], *, use_key: str | None, who: str) -> AskRequest:
    prompt = params.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise AskError(AI_ERROR_INVALID, "prompt is required.")
    raw_pictures = params.get("pictures") or []
    if not isinstance(raw_pictures, list):
        raise AskError(AI_ERROR_INVALID, "pictures must be a list of base64 JPEGs.")
    if len(raw_pictures) > MAX_PICTURES:
        raise AskError(AI_ERROR_INVALID, f"At most {MAX_PICTURES} pictures in one ask.")
    pictures = [decode_b64(p, f"picture {i + 1}") for i, p in enumerate(raw_pictures)]
    labels = params.get("picture_labels") or []
    if not isinstance(labels, list) or not all(isinstance(x, str) for x in labels):
        raise AskError(AI_ERROR_INVALID, "picture_labels must be a list of text.")
    sound_bytes: bytes | None = None
    sound_mime = "audio/wav"
    sound = params.get("sound")
    if sound is not None:
        if not isinstance(sound, dict):
            raise AskError(AI_ERROR_INVALID, "sound must be {b64, mime}.")
        sound_bytes = decode_b64(sound.get("b64"), "sound")
        sound_mime = str(sound.get("mime") or "audio/wav")
    schema = params.get("schema")
    if schema is not None and not isinstance(schema, dict):
        raise AskError(AI_ERROR_INVALID, "schema must be a JSON schema object.")
    timeout = params.get("timeout")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float))):
        raise AskError(AI_ERROR_INVALID, "timeout must be a number of seconds.")
    profile = params.get("profile")
    if profile is not None and not isinstance(profile, str):
        raise AskError(AI_ERROR_INVALID, "profile must be a profile id.")
    return AskRequest(
        prompt=prompt,
        use=use_key,
        profile_id=profile or None,
        pictures=pictures,
        picture_labels=list(labels),
        sound=sound_bytes,
        sound_mime=sound_mime,
        schema=schema,
        detail=str(params.get("detail") or "medium"),
        local_only=bool(params.get("local_only", False)),
        timeout=float(timeout) if timeout is not None else None,
        wait=bool(params.get("wait", True)),
        who=who,
    )
