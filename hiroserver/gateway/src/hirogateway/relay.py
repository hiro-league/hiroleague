"""Device connection registry and message relay logic.

Connections are authenticated with a nonce challenge:
1) gateway sends {"type":"auth_challenge","nonce":"..."}
2) peer responds with {"type":"auth_response", ...}
3) on success, the socket is registered with its authenticated device_id

Messages are JSON objects with an optional `target_device_id` field:
  - Present  -> unicast to that specific device
  - Absent   -> broadcast to all OTHER connected devices

Message envelope:
{
    "target_device_id": "<uuid>",   # optional
    "sender_device_id": "<uuid>",   # injected by gateway
    "payload": { ... }              # arbitrary application data
}
"""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import websockets
from websockets.asyncio.server import ServerConnection
from hiro_commons.nonces import generate_nonce
from hiro_commons.log import Logger

from hiro_channel_sdk.constants import (
    AUTH_ROLE_DESKTOP,
    AUTH_ROLE_DEVICE,
    WS_CLOSE_AUTH_FAILED,
    WS_CLOSE_DESKTOP_NOT_CONNECTED,
    WS_CLOSE_DUPLICATE_DEVICE,
    WS_CLOSE_NORMAL,
    WS_CLOSE_PAIRING_FIELD_MISSING,
    WS_CLOSE_PAIRING_TIMEOUT,
)
from hiro_commons.constants.timing import DEFAULT_AUTH_TIMEOUT_SECONDS, DEFAULT_PAIRING_WAIT_SECONDS

from .auth import GatewayAuthManager
from .config import GatewayState, load_state, save_state
from .constants import PAIRING_REQUEST_ID_BYTES, WS_REASON_MAX_LENGTH

log = Logger.get("RELAY")

# --------------------------------------------------------------------------
# Direction convention (server-centric, mirrors communication_manager.py):
#   ⬇️  Inbound  — device → gateway → HiroServer
#   ⬆️  Outbound — HiroServer → gateway → device
# --------------------------------------------------------------------------
_LOG_IN = "⬇️"
_LOG_OUT = "⬆️"
_HIRO_SERVER = "HiroServer"
_TEXT_SNIPPET_MAX = 120

# device_id -> websocket
_registry: Dict[str, ServerConnection] = {}
_registry_lock = asyncio.Lock()

# device_id -> auth role (AUTH_ROLE_DESKTOP | AUTH_ROLE_DEVICE)
_device_roles: Dict[str, str] = {}

# device_id -> friendly name (runtime cache populated from payload metadata)
_device_names: Dict[str, str] = {}

AUTH_TIMEOUT_SECONDS = DEFAULT_AUTH_TIMEOUT_SECONDS
_auth_manager: GatewayAuthManager | None = None
_desktop_ws: ServerConnection | None = None
_pairing_pending: Dict[str, ServerConnection] = {}
_pairing_lock = asyncio.Lock()
PAIRING_WAIT_SECONDS = DEFAULT_PAIRING_WAIT_SECONDS

_instance_path: "Path | None" = None


# --------------------------------------------------------------------------
# Log helper: device label
# --------------------------------------------------------------------------

def _device_label(device_id: str) -> str:
    """Return friendly name if cached, else abbreviated device_id."""
    name = _device_names.get(device_id)
    if name:
        return name
    # Short suffix so logs stay scannable without exposing the full UUID.
    return f"device:{device_id[-8:]}" if len(device_id) > 8 else device_id


# --------------------------------------------------------------------------
# Log helpers: message kind + content hint (mirrors _comm_kind/_comm_content_hint)
# --------------------------------------------------------------------------

def _relay_kind(payload: dict[str, Any]) -> str:
    """Short type summary from a raw UnifiedMessage payload dict.

    Mirrors communication_manager._comm_kind() but operates on the plain dict
    since the gateway never deserialises payloads into UnifiedMessage objects.
    """
    mt = payload.get("message_type") if isinstance(payload, dict) else None
    if mt == "message":
        content = payload.get("content") or []
        if not content:
            return "message[]"
        types = [c.get("content_type", "?") for c in content if isinstance(c, dict)]
        return f"message[{','.join(types)}]"
    if mt == "event":
        event = payload.get("event") or {}
        et = event.get("type", "?") if isinstance(event, dict) else "?"
        return f"event:{et}"
    if mt == "request":
        for item in (payload.get("content") or []):
            if isinstance(item, dict) and item.get("content_type") == "json":
                try:
                    body = json.loads(item.get("body", ""))
                    if "method" in body:
                        return f"request:{body['method']}"
                except (json.JSONDecodeError, TypeError):
                    pass
        return "request"
    if mt == "response":
        for item in (payload.get("content") or []):
            if isinstance(item, dict) and item.get("content_type") == "json":
                try:
                    body = json.loads(item.get("body", ""))
                    return f"response[{body.get('status', '?')}]"
                except (json.JSONDecodeError, TypeError):
                    pass
        return "response"
    return str(mt) if mt else "?"


def _relay_snippet(body: str, max_len: int = _TEXT_SNIPPET_MAX) -> str:
    t = " ".join(body.split())
    return t if len(t) <= max_len else t[: max_len - 1] + "…"


def _relay_content_hint(payload: dict[str, Any]) -> str | None:
    """Text snippet or content-type label from payload content items.

    Only meaningful for message_type == "message". Mirrors _comm_content_hint().
    """
    if not isinstance(payload, dict) or payload.get("message_type") != "message":
        return None
    parts: list[str] = []
    for item in (payload.get("content") or []):
        if not isinstance(item, dict):
            continue
        ct = item.get("content_type", "?")
        body = item.get("body", "")
        if ct == "text":
            parts.append(_relay_snippet(body) if isinstance(body, str) and body.strip() else "text:(empty)")
        elif ct == "audio":
            parts.append("audio")
        elif ct == "json":
            parts.append(_relay_snippet(body, 80) if isinstance(body, str) and body.strip() else "json:(empty)")
        else:
            parts.append(str(ct))
    return " | ".join(parts) if parts else None


def _update_name_cache(
    sender_id: str,
    target_id: str | None,
    payload: dict[str, Any],
    *,
    is_from_server: bool,
) -> None:
    """Cache device_name from payload routing metadata.

    HiroServer injects device_name into routing.metadata on outbound messages
    so the recipient device_id → name can be cached here for future log lines.
    For inbound messages the sender may also carry their own name.
    """
    routing = payload.get("routing") if isinstance(payload, dict) else None
    if not isinstance(routing, dict):
        return
    meta = routing.get("metadata")
    if not isinstance(meta, dict):
        return
    name = meta.get("device_name")
    if not isinstance(name, str) or not name.strip():
        return
    # Outbound: device_name describes the recipient; inbound: it describes the sender.
    if is_from_server and target_id:
        _device_names[target_id] = name.strip()
    elif not is_from_server:
        _device_names[sender_id] = name.strip()


def _message_id(msg: dict[str, object]) -> str | None:
    payload = msg.get("payload")
    if not isinstance(payload, dict):
        return None
    # Try routing.id first (UnifiedMessage), fall back to top-level id.
    routing = payload.get("routing")
    if isinstance(routing, dict):
        rid = routing.get("id")
        if isinstance(rid, str) and rid:
            return rid
    msg_id = payload.get("id")
    return msg_id if isinstance(msg_id, str) and msg_id else None


def configure_auth(auth_manager: GatewayAuthManager) -> None:
    """Inject the auth manager configured at gateway startup."""
    global _auth_manager
    _auth_manager = auth_manager


def configure_instance_path(instance_path: Path) -> None:
    """Inject the instance path so relay can persist connection state."""
    global _instance_path
    _instance_path = instance_path


def _write_desktop_connected() -> None:
    if _instance_path is None:
        return
    state = load_state(_instance_path)
    state.desktop_connected = True
    state.last_connected = datetime.now(timezone.utc).isoformat()
    state.last_auth_error = None
    save_state(_instance_path, state)


def _write_desktop_disconnected() -> None:
    if _instance_path is None:
        return
    state = load_state(_instance_path)
    state.desktop_connected = False
    save_state(_instance_path, state)


def _write_auth_error(reason: str) -> None:
    if _instance_path is None:
        return
    state = load_state(_instance_path)
    state.desktop_connected = False
    state.last_auth_error = reason
    save_state(_instance_path, state)


async def register(device_id: str, ws: ServerConnection, *, role: str = "") -> bool:
    async with _registry_lock:
        if device_id in _registry:
            old_ws = _registry[device_id]
            if old_ws is ws:
                return True
            label = _HIRO_SERVER if role == AUTH_ROLE_DESKTOP else _device_label(device_id)
            log.warning(f"⚠️ Duplicate connection rejected — {label}", device_id=device_id)
            try:
                await ws.close(code=WS_CLOSE_DUPLICATE_DEVICE, reason="device already connected")
            except Exception:
                pass
            return False
        _registry[device_id] = ws
        if role:
            _device_roles[device_id] = role
        label = _HIRO_SERVER if role == AUTH_ROLE_DESKTOP else _device_label(device_id)
        log.info(f"✅ Device connected — {label}", device_id=device_id, role=role or "?", total=len(_registry))
        return True


async def unregister(device_id: str, ws: ServerConnection) -> None:
    async with _registry_lock:
        if _registry.get(device_id) is ws:
            _registry.pop(device_id, None)
            role = _device_roles.pop(device_id, "")
            # Resolve label before evicting the name so the disconnect log still shows it.
            label = _HIRO_SERVER if role == AUTH_ROLE_DESKTOP else _device_label(device_id)
            _device_names.pop(device_id, None)
            log.info(f"🔌 Device disconnected — {label}", device_id=device_id, role=role or "?", total=len(_registry))


async def relay_message(sender_id: str, raw: str) -> None:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("⚠️ Non-JSON message ignored", sender_id=sender_id)
        return

    msg["sender_device_id"] = sender_id
    target_id: str | None = msg.get("target_device_id")
    msg_id = _message_id(msg)

    # Determine direction from sender role.
    sender_role = _device_roles.get(sender_id, "")
    is_from_server = sender_role == AUTH_ROLE_DESKTOP
    arrow = _LOG_OUT if is_from_server else _LOG_IN
    sender_label = _HIRO_SERVER if is_from_server else _device_label(sender_id)

    # Peek into the UnifiedMessage payload for kind + content hint.
    payload = msg.get("payload")
    if isinstance(payload, dict):
        kind = _relay_kind(payload)
        hint = _relay_content_hint(payload)
        _update_name_cache(sender_id, target_id, payload, is_from_server=is_from_server)
    else:
        kind = "?"
        hint = None

    route = "unicast" if target_id else "broadcast"
    log_extras: dict[str, Any] = {}
    if hint:
        log_extras["content_hint"] = hint
    log_extras["sender_id"] = sender_id
    log_extras["msg_id"] = msg_id or "-"
    if target_id:
        log_extras["target_id"] = target_id
    log.info(
        f"{arrow} Message received — {sender_label} · {kind} ({route})",
        **log_extras,
    )
    out = json.dumps(msg)

    async with _registry_lock:
        if target_id:
            target_ws = _registry.get(target_id)
            if target_ws is None:
                log.warning(
                    f"⚠️ Message dropped — target not connected · {kind}",
                    sender_id=sender_id,
                    target_id=target_id,
                    msg_id=msg_id or "-",
                )
                return
            recipients = [(target_id, target_ws)]
        else:
            recipients = [(did, ws) for did, ws in _registry.items() if did != sender_id]

    for did, ws in recipients:
        try:
            await ws.send(out)
            recipient_role = _device_roles.get(did, "")
            recipient_label = _HIRO_SERVER if recipient_role == AUTH_ROLE_DESKTOP else _device_label(did)
            log.info(
                f"{arrow} Message relayed — {sender_label} → {recipient_label} · {kind}",
                msg_id=msg_id or "-",
                sender_id=sender_id,
                recipient_id=did,
            )
        except Exception as exc:
            log.warning(
                f"⚠️ Failed to relay — {sender_label} → {_device_label(did)} · {kind}",
                recipient_id=did,
                msg_id=msg_id or "-",
                error=str(exc),
            )


async def _authenticate_connection(
    nonce: str,
    msg: dict[str, object],
) -> tuple[bool, str | None, str, str | None]:
    auth = _auth_manager
    if auth is None:
        return False, None, "auth not configured", None
    if msg.get("type") != "auth_response":
        return False, None, "first message must be auth_response", None

    mode = msg.get("auth_mode")
    if not isinstance(mode, str):
        return False, None, "auth_mode is required", None

    if mode == AUTH_ROLE_DESKTOP:
        device_id = msg.get("device_id")
        signature = msg.get("nonce_signature") or msg.get("signature")
        if not isinstance(device_id, str) or not device_id:
            return False, None, "desktop auth requires device_id", None
        if not isinstance(signature, str) or not signature:
            return False, None, "desktop auth requires nonce_signature", None
        result = auth.verify_desktop_auth(
            nonce_hex=nonce,
            nonce_signature_b64=signature,
        )
        return (
            result.ok,
            device_id if result.ok else None,
            result.reason or "auth failed",
            AUTH_ROLE_DESKTOP,
        )

    if mode == AUTH_ROLE_DEVICE:
        attestation = msg.get("attestation")
        nonce_signature = msg.get("nonce_signature") or msg.get("signature")
        if not isinstance(attestation, dict):
            return False, None, "device auth requires attestation object", None
        if not isinstance(nonce_signature, str) or not nonce_signature:
            return False, None, "device auth requires nonce_signature", None
        blob = attestation.get("blob")
        desktop_signature = attestation.get("desktop_signature")
        if not isinstance(blob, str) or not blob:
            return False, None, "attestation.blob is required", None
        if not isinstance(desktop_signature, str) or not desktop_signature:
            return False, None, "attestation.desktop_signature is required", None
        result = auth.verify_device_auth(
            nonce_hex=nonce,
            attestation_blob=blob,
            desktop_signature_b64=desktop_signature,
            nonce_signature_b64=nonce_signature,
        )
        return result.ok, result.device_id, result.reason or "auth failed", "device"

    return False, None, f"unsupported auth_mode: {mode}", None


async def _register_desktop_ws(ws: ServerConnection) -> None:
    global _desktop_ws
    async with _pairing_lock:
        _desktop_ws = ws
    _write_desktop_connected()


async def _unregister_desktop_ws(ws: ServerConnection) -> None:
    global _desktop_ws
    async with _pairing_lock:
        if _desktop_ws is ws:
            _desktop_ws = None
    _write_desktop_disconnected()


async def _get_desktop_ws() -> ServerConnection | None:
    async with _pairing_lock:
        return _desktop_ws


async def _forward_pairing_request(ws: ServerConnection, msg: dict[str, object]) -> None:
    pairing_code = msg.get("pairing_code")
    device_public_key = msg.get("device_public_key")
    if not isinstance(pairing_code, str) or not pairing_code:
        await ws.close(code=WS_CLOSE_PAIRING_FIELD_MISSING, reason="pairing_code is required")
        return
    if not isinstance(device_public_key, str) or not device_public_key:
        await ws.close(code=WS_CLOSE_PAIRING_FIELD_MISSING, reason="device_public_key is required")
        return

    desktop_ws = await _get_desktop_ws()
    if desktop_ws is None:
        await ws.close(code=WS_CLOSE_DESKTOP_NOT_CONNECTED, reason="desktop not connected")
        return

    request_id = secrets.token_hex(PAIRING_REQUEST_ID_BYTES)
    async with _pairing_lock:
        _pairing_pending[request_id] = ws

    # Forward device_name if provided — used for admin UI device list labelling.
    device_name = msg.get("device_name")
    forward_payload: dict[str, object] = {
        "type": "pairing_request",
        "request_id": request_id,
        "pairing_code": pairing_code,
        "device_public_key": device_public_key,
    }
    if isinstance(device_name, str) and device_name:
        forward_payload["device_name"] = device_name

    await desktop_ws.send(json.dumps(forward_payload))
    await ws.send(json.dumps({"type": "pairing_pending", "request_id": request_id}))

    try:
        await asyncio.wait_for(ws.wait_closed(), timeout=PAIRING_WAIT_SECONDS)
    except asyncio.TimeoutError:
        async with _pairing_lock:
            _pairing_pending.pop(request_id, None)
        await ws.close(code=WS_CLOSE_PAIRING_TIMEOUT, reason="pairing timeout")


async def _handle_pairing_response_from_desktop(msg: dict[str, object]) -> None:
    request_id = msg.get("request_id")
    status = msg.get("status")
    if not isinstance(request_id, str) or not request_id:
        log.warning("⚠️ Pairing response ignored — missing request_id")
        return
    if not isinstance(status, str) or status not in {"approved", "rejected"}:
        log.warning("⚠️ Pairing response ignored — invalid status")
        return

    async with _pairing_lock:
        pending_ws = _pairing_pending.pop(request_id, None)
    if pending_ws is None:
        log.warning("⚠️ Pairing response ignored — no pending request", request_id=request_id)
        return

    outbound: dict[str, object] = {
        "type": "pairing_response",
        "status": status,
    }
    if status == "approved":
        attestation = msg.get("attestation")
        device_id = msg.get("device_id")
        if isinstance(attestation, dict):
            outbound["attestation"] = attestation
        if isinstance(device_id, str) and device_id:
            outbound["device_id"] = device_id
    else:
        reason = msg.get("reason")
        outbound["reason"] = reason if isinstance(reason, str) and reason else "rejected"

    try:
        await pending_ws.send(json.dumps(outbound))
    finally:
        await pending_ws.close(code=WS_CLOSE_NORMAL, reason="pairing complete")


async def handle_connection(ws: ServerConnection) -> None:
    """Handle a single WebSocket connection lifetime."""
    nonce = generate_nonce()
    await ws.send(json.dumps({"type": "auth_challenge", "nonce": nonce}))

    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        log.warning("⚠️ Auth rejected — timeout")
        await ws.close(code=WS_CLOSE_AUTH_FAILED, reason="auth timeout")
        return
    except websockets.ConnectionClosed:
        return

    try:
        first_msg = json.loads(str(raw))
    except json.JSONDecodeError:
        log.warning("⚠️ Auth rejected — invalid JSON")
        await ws.close(code=WS_CLOSE_AUTH_FAILED, reason="invalid json")
        return
    if not isinstance(first_msg, dict):
        log.warning("⚠️ Auth rejected — first message must be object")
        await ws.close(code=WS_CLOSE_AUTH_FAILED, reason="invalid first message")
        return

    if first_msg.get("type") == "pairing_request":
        await _forward_pairing_request(ws, first_msg)
        return

    # device_name is a self-reported display string sent outside the signed blob.
    # It has no effect on access control — used only for log readability.
    handshake_name: str | None = first_msg.get("device_name")  # type: ignore[assignment]
    if not isinstance(handshake_name, str) or not handshake_name.strip():
        handshake_name = None

    ok, device_id, reason, role = await _authenticate_connection(nonce, first_msg)
    if not ok or not device_id:
        mode = first_msg.get("auth_mode", "unknown")
        peer = handshake_name or (f"device_id:{device_id}" if device_id else "unknown")
        log.warning(f"⚠️ Auth rejected — {peer} · {reason}", mode=mode, device_id=device_id or "-")
        # Record auth errors for desktop role so the dashboard can surface them.
        if first_msg.get("auth_mode") == AUTH_ROLE_DESKTOP:
            _write_auth_error(reason)
        await ws.close(code=WS_CLOSE_AUTH_FAILED, reason=reason[:WS_REASON_MAX_LENGTH])
        return

    # Seed the name cache immediately so all subsequent relay logs show the name.
    if handshake_name and role != AUTH_ROLE_DESKTOP:
        _device_names[device_id] = handshake_name

    await ws.send(json.dumps({"type": "auth_ok", "device_id": device_id}))
    label = _HIRO_SERVER if role == AUTH_ROLE_DESKTOP else _device_label(device_id)
    log.info(f"✅ Device authenticated — {label}", device_id=device_id, role=role)

    is_desktop = role == AUTH_ROLE_DESKTOP
    if not await register(device_id, ws, role=role or ""):
        return
    if is_desktop:
        await _register_desktop_ws(ws)
    try:
        async for message in ws:
            if is_desktop:
                try:
                    maybe = json.loads(str(message))
                except json.JSONDecodeError:
                    maybe = None
                if isinstance(maybe, dict) and maybe.get("type") == "pairing_response":
                    await _handle_pairing_response_from_desktop(maybe)
                    continue
            await relay_message(device_id, message)
    except websockets.ConnectionClosed:
        pass
    finally:
        if is_desktop:
            await _unregister_desktop_ws(ws)
        await unregister(device_id, ws)


def get_connected_devices() -> list[str]:
    return list(_registry.keys())
