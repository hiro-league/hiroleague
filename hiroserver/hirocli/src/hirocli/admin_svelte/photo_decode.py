"""Decode ``data:…;base64,…`` payloads from the admin UI."""

from __future__ import annotations

import base64
import binascii


def _decode_photo_data_url(data_url: str) -> bytes:
    if not data_url.startswith("data:"):
        raise ValueError("Photo upload must be a data URL.")
    try:
        meta, b64 = data_url.split(",", 1)
    except ValueError as exc:
        raise ValueError("Invalid photo data URL.") from exc
    if "base64" not in meta:
        raise ValueError("Photo data URL must be base64 encoded.")
    try:
        return base64.standard_b64decode(b64)
    except binascii.Error as exc:
        raise ValueError("Invalid photo image data.") from exc
