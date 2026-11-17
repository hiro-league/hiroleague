"""Reading an ``ai.ask``'s or ``ai.chat``'s params (wire JSON) into an ``AskRequest`` — refusals are ``invalid``."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from hiro_channel_sdk.constants import AI_ERROR_INVALID

from .errors import AskError
from .runner import AskRequest

MAX_PICTURES = 60  # the most a use may declare (StudyHiro's study reviews)
MAX_LABEL = 80  # Phase 7b: a free label AI usage files the ask under (a camera, a task)


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
    # Phase 7b: who the ask is for (a person id; the caller checks it exists) and a free label, for AI usage.
    person = params.get("person")
    if person is not None and not isinstance(person, str):
        raise AskError(AI_ERROR_INVALID, "person must be a person id.")
    label = params.get("label")
    if label is not None and (not isinstance(label, str) or len(label.strip()) > MAX_LABEL):
        raise AskError(AI_ERROR_INVALID, f"label must be text of at most {MAX_LABEL} characters.")
    folder = params.get("folder")
    if folder is not None and not isinstance(folder, str):
        raise AskError(AI_ERROR_INVALID, "folder must be a path as text.")
    if folder and (raw_pictures or sound is not None):
        raise AskError(AI_ERROR_INVALID, "An ask that names a folder can't carry pictures or sound.")
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
        person_id=(person or "").strip(),
        label=(label or "").strip(),
        folder=(folder or "").strip(),  # not yet checked: ai_for_extensions resolves it against what is allowed
    )


ROLES = ("system", "user", "assistant", "tool")
MAX_MESSAGES = 200  # a recall loop is a few dozen turns at most
MAX_TOOLS = 32


def chat_request_from_params(params: dict[str, Any], *, use_key: str | None, who: str) -> AskRequest:
    """``ai.chat``'s params → an ``AskRequest`` carrying the conversation and the tools (refusals are ``invalid``)."""
    messages = [_message(m, i) for i, m in enumerate(_listed(params.get("messages"), "messages", MAX_MESSAGES))]
    tools = [_tool(t, i) for i, t in enumerate(_listed(params.get("tools") or [], "tools", MAX_TOOLS))]
    schema = params.get("schema")
    if schema is not None and not isinstance(schema, dict):
        raise AskError(AI_ERROR_INVALID, "schema must be a JSON schema object.")
    if schema is not None and tools:
        raise AskError(AI_ERROR_INVALID, "A conversation asks for tools or for a schema, not both.")
    timeout = params.get("timeout")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, (int, float))):
        raise AskError(AI_ERROR_INVALID, "timeout must be a number of seconds.")
    profile = params.get("profile")
    if profile is not None and not isinstance(profile, str):
        raise AskError(AI_ERROR_INVALID, "profile must be a profile id.")
    label = params.get("label")
    if label is not None and (not isinstance(label, str) or len(label.strip()) > MAX_LABEL):
        raise AskError(AI_ERROR_INVALID, f"label must be text of at most {MAX_LABEL} characters.")
    return AskRequest(
        prompt="",
        use=use_key,
        profile_id=profile or None,
        schema=schema,
        timeout=float(timeout) if timeout is not None else None,
        who=who,
        label=(label or "").strip(),
        messages=messages,
        tools=tools or None,
    )


def _listed(value: Any, what: str, most: int) -> list[Any]:
    if not isinstance(value, list) or (what == "messages" and not value):
        raise AskError(AI_ERROR_INVALID, f"{what} must be a list" + (" of at least one message." if what == "messages" else "."))
    if len(value) > most:
        raise AskError(AI_ERROR_INVALID, f"At most {most} {what} in one conversation.")
    return value


def _message(m: Any, i: int) -> dict[str, Any]:
    where = f"messages[{i}]"
    if not isinstance(m, dict) or m.get("role") not in ROLES:
        raise AskError(AI_ERROR_INVALID, f"{where} needs a role: one of {', '.join(ROLES)}.")
    content = m.get("content", "")
    if not isinstance(content, str):
        raise AskError(AI_ERROR_INVALID, f"{where}.content must be text.")
    out: dict[str, Any] = {"role": m["role"], "content": content}
    if m["role"] == "assistant" and m.get("tool_calls"):
        calls = m["tool_calls"]
        if not isinstance(calls, list) or not all(
            isinstance(c, dict) and isinstance(c.get("id"), str) and isinstance(c.get("name"), str)
            and isinstance(c.get("args", {}), dict) for c in calls
        ):
            raise AskError(AI_ERROR_INVALID, f"{where}.tool_calls must be [{{id, name, args}}].")
        out["tool_calls"] = [{"id": c["id"], "name": c["name"], "args": c.get("args") or {}} for c in calls]
    if m["role"] == "tool":
        if not isinstance(m.get("tool_call_id"), str) or not m["tool_call_id"]:
            raise AskError(AI_ERROR_INVALID, f"{where} answers a tool call: it needs its tool_call_id.")
        out["tool_call_id"] = m["tool_call_id"]
    return out


def _tool(t: Any, i: int) -> dict[str, Any]:
    if not (isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"].strip()
            and isinstance(t.get("parameters"), dict)):
        raise AskError(AI_ERROR_INVALID, f"tools[{i}] needs a name and its parameters (a JSON schema).")
    description = t.get("description", "")
    if not isinstance(description, str):
        raise AskError(AI_ERROR_INVALID, f"tools[{i}].description must be text.")
    return {"name": t["name"].strip(), "description": description, "parameters": t["parameters"]}
