"""PluginRunner — runs a channel plugin as an extension the core starts.

A channel plugin is an extension like any app: it signs in on the core's one extension socket with its own key
(ExtensionClient). What the runner adds is the plugin's API (base.ChannelPlugin), tied to that client:

- the first time, or when its key is lost, it pairs with the code the core put in its environment
  (constants.ENV_PAIRING_CODE); the key and the id the core gave it stay in its key folder;
- ``extension.configure`` hands the plugin its settings, then starts it (``on_configure``, then ``on_start`` once);
  ``extension.status`` answers, ``extension.stop`` ends the run;
- a request the core sends for one of the plugin's own methods goes to ``on_call``; an event (an admin action,
  ``channel.logout``) to ``on_event``;
- what the plugin emits (a phone's or a WhatsApp contact's message) goes to the core as it is, their sender and the
  plugin's channel; what the core sends for someone else (a reply to that phone) goes to ``send``, in order.

Usage, in a plugin's ``main.py``::

    log_setup.run(PluginRunner(MyChannel(), hiro_ws, Path(key_dir)).run())
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from .base import ChannelCallNotSupported, ChannelCallRefused, ChannelPlugin
from .constants import (
    ENV_PAIRING_CODE,
    METHOD_EXTENSION_CONFIGURE,
    METHOD_EXTENSION_STATUS,
    METHOD_EXTENSION_STOP,
)
from .extension import (
    STATUS_CONNECTED,
    STATUS_NOT_PAIRED,
    ExtensionClient,
    ExtensionCredentials,
    ExtensionInfo,
    ExtensionRequestError,
)
from .models import UnifiedMessage

log = Logger.get("CH_RUNNER")


class PluginRunner:
    """Keeps a channel plugin signed in on the core's extension socket and drives its API."""

    def __init__(
        self, plugin: ChannelPlugin, hiro_ws: str, key_dir: Path, *, pairing_code: str | None = None
    ) -> None:
        self._plugin = plugin
        info = plugin.info
        self._client = ExtensionClient(
            hiro_ws,
            ExtensionInfo(
                name=info.name,
                version=info.version,
                description=info.description,
                config_schema=info.config_schema,
                capabilities=info.capabilities,
            ),
            ExtensionCredentials(key_dir),
            on_status=self._on_status,
            on_relay=self._relay,
        )
        # The core's code, kept for when the key it signs in with is refused (lost, or the core forgot it).
        code = pairing_code if pairing_code is not None else os.environ.get(ENV_PAIRING_CODE, "")
        self._code: str | None = code.strip() or None
        self._started = False
        self._done = asyncio.Event()
        self._client.register_request(METHOD_EXTENSION_CONFIGURE, self._configure)
        self._client.register_request(METHOD_EXTENSION_STATUS, self._status)
        self._client.register_request(METHOD_EXTENSION_STOP, self._stop)
        self._client.register_any_request(self._call)
        self._client.on_any_event(self._event)

    @property
    def client(self) -> ExtensionClient:
        return self._client

    async def run(self) -> None:
        """Stay signed in until the core says stop (or the key can't be replaced)."""
        self._plugin._emit_callback = self._emit
        self._plugin._event_callback = self._emit_event
        if self._code is not None and self._client_unpaired():
            self._use_code()
        client_task = asyncio.ensure_future(self._client.run())
        try:
            await self._done.wait()
        finally:
            await self._stop_plugin()
            await self._client.stop()
            try:
                await asyncio.wait_for(client_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                client_task.cancel()
            self._plugin._emit_callback = None
            self._plugin._event_callback = None

    def stop(self) -> None:
        self._done.set()

    # -- sign-in ---------------------------------------------------------------

    def _client_unpaired(self) -> bool:
        return ExtensionCredentials(self._client_folder()).extension_id() is None

    def _client_folder(self) -> Path:
        return self._client._credentials.folder  # noqa: SLF001 — the runner owns its client

    def _use_code(self) -> None:
        code, self._code = self._code, None
        if code:
            self._client.pair(code)

    async def _on_status(self, status: str, detail: dict[str, Any]) -> None:
        if status != STATUS_CONNECTED and self._started:
            # Disconnected: the plugin stops until the core configures it again on the next sign-in.
            await self._stop_plugin()
        if status == STATUS_NOT_PAIRED:
            if self._code is not None:
                log.info(f"🔑 Channel ({self._plugin.info.name}) pairs with the core's code", reason=detail.get("error"))
                self._use_code()
            else:
                log.error(
                    f"❌ Channel ({self._plugin.info.name}) can't sign in and has no pairing code left — "
                    "it stops; switching it on in the admin, or the core's next start, gives it a new code",
                    reason=detail.get("error"),
                )
                self._done.set()

    # -- the core's requests and events -------------------------------------------

    async def _configure(self, params: dict[str, Any]) -> dict[str, Any]:
        config = params.get("config") or {}
        if not isinstance(config, dict):
            raise ExtensionRequestError("invalid_params", "config must be an object")
        await self._plugin.on_configure(config)
        if not self._started:
            await self._plugin.on_start()
            self._started = True
        return {}

    async def _status(self, _params: dict[str, Any]) -> dict[str, Any]:
        info = self._plugin.info
        return {"name": info.name, "version": info.version, "status": "running"}

    async def _stop(self, _params: dict[str, Any]) -> dict[str, Any]:
        # Answered first; the run ends right after.
        asyncio.get_running_loop().call_soon(self._done.set)
        return {}

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self._plugin.on_call(method, params)
        except ChannelCallNotSupported as exc:
            raise ExtensionRequestError("method_not_found", str(exc)) from exc
        except ChannelCallRefused as exc:
            raise ExtensionRequestError(exc.reason, exc.message) from exc
        return result if isinstance(result, dict) else {"value": result}

    async def _event(self, event_type: str, data: dict[str, Any]) -> None:
        await self._plugin.on_event(event_type, data)

    # -- frames both ways -----------------------------------------------------------

    async def _relay(self, msg: UnifiedMessage) -> None:
        await self._plugin.send(msg)

    async def _emit(self, msg: UnifiedMessage) -> None:
        if not await self._client.send_frame(msg):
            log.warning(f"⚠️ Channel ({self._plugin.info.name}) not connected — a message was dropped")

    async def _emit_event(self, event: str, data: dict[str, Any]) -> None:
        await self._client.send_event(event, data)

    async def _stop_plugin(self) -> None:
        if self._started:
            self._started = False
            try:
                await self._plugin.on_stop()
            except Exception as exc:
                log.error(f"❌ Channel ({self._plugin.info.name}) failed to stop", error=str(exc), exc_info=True)
