"""Announcing the names the core serves on the LAN (mDNS), each system's own way (docs/site-names-design.md).

- **Linux:** one ``avahi-publish -a -R <name> <ip>`` per name, kept running while the name is served (an ordinary
  user may: no sudo); restarted when it ends (avahi restarted).
- **Windows and Mac:** python-zeroconf inside the core, beside the system's own responder (tried on the PC beside
  Windows' own mDNS, Nov 24, 2026): each name is a host record, carried by an HTTP service record whose host it is.

Either way ``sync(names)`` makes the announced names exactly ``names``; a name that can't be announced is logged and
the others go on.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import socket
import sys
from typing import Any, Protocol

from hiro_commons.log import Logger

log = Logger.get("SITE_NAMES")

RESTART_PUBLISHER_S = 5.0  # an avahi-publish that ended (avahi restarted) is started again after this long


class NamePublisher(Protocol):
    """Announces names on the LAN, pointing at one address."""

    note: str  # why names aren't announced here (empty when they are)

    @property
    def announced(self) -> set[str]: ...

    async def sync(self, names: set[str]) -> None: ...

    async def close(self) -> None: ...


class AvahiPublisher:
    """Linux: one avahi-publish per name."""

    def __init__(self, ip: str) -> None:
        self.ip = ip
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self.note = "" if shutil.which("avahi-publish") else "avahi-publish isn't installed here, so names aren't announced on the LAN."

    @property
    def announced(self) -> set[str]:
        return set(self._tasks)

    async def sync(self, names: set[str]) -> None:
        for name in list(self._tasks):
            if name not in names:
                self._tasks.pop(name).cancel()
        if self.note:
            log.warning(f"⚠️ Site names — {self.note}")
            return
        for name in names - set(self._tasks):
            self._tasks[name] = asyncio.create_task(self._publish(name), name=f"site-name:{name}")

    async def close(self) -> None:
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def _publish(self, name: str) -> None:
        """Keep ``name`` announced: avahi-publish runs as long as the name is served, restarted if it ends."""
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "avahi-publish", "-a", "-R", name, self.ip,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
            except OSError as exc:
                log.error(f"❌ Site name not announced — {name}", error=str(exc))
                return
            log.info(f"⬆️ Site name announced — {name} · {self.ip}")
            try:
                _, err = await proc.communicate()
            except asyncio.CancelledError:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(proc.wait(), timeout=5)
                log.info(f"Site name no longer announced — {name}")
                raise
            log.warning(
                f"⚠️ Site name publisher ended — {name} · restarting in {RESTART_PUBLISHER_S:.0f}s",
                code=proc.returncode,
                error=(err or b"").decode(errors="replace").strip()[:300],
            )
            await asyncio.sleep(RESTART_PUBLISHER_S)


_SERVICE_TYPE = "_http._tcp.local."


class ZeroconfPublisher:
    """Windows and Mac: python-zeroconf inside the core, on the LAN address only."""

    def __init__(self, ip: str) -> None:
        self.ip = ip
        self.note = ""
        self._zc: Any = None
        self._infos: dict[str, Any] = {}
        try:
            import zeroconf  # noqa: F401 — present on Windows and Mac (the core's dependencies)
        except ImportError:
            self.note = "python-zeroconf isn't installed here, so names aren't announced on the LAN."

    @property
    def announced(self) -> set[str]:
        return set(self._infos)

    def _info(self, name: str) -> Any:
        from zeroconf import ServiceInfo

        # One HTTP service per name, whose host is the name: announcing it announces the name's address.
        return ServiceInfo(
            _SERVICE_TYPE,
            f"{name.replace('.', '-')}.{_SERVICE_TYPE}",
            port=80,
            server=f"{name}.",
            addresses=[socket.inet_aton(self.ip)],
            properties={"path": "/"},
        )

    async def sync(self, names: set[str]) -> None:
        if self.note:
            log.warning(f"⚠️ Site names — {self.note}")
            return
        if self._zc is None:
            from zeroconf import IPVersion
            from zeroconf.asyncio import AsyncZeroconf

            try:
                self._zc = AsyncZeroconf(interfaces=[self.ip], ip_version=IPVersion.V4Only)
            except OSError as exc:
                # The address isn't this machine's (the network changed), or port 5353 can't be opened.
                self.note = f"Names can't be announced on {self.ip}: {exc.strerror or exc}."
                log.warning(f"⚠️ Site names — {self.note}")
                return
        for name in [n for n in self._infos if n not in names]:
            info = self._infos.pop(name)
            try:
                await (await self._zc.async_unregister_service(info))
                log.info(f"Site name no longer announced — {name}")
            except Exception as exc:  # noqa: BLE001 — one name's failure must not stop the rest; logged
                log.warning(f"⚠️ Site name couldn't be withdrawn — {name}", error=str(exc), error_type=type(exc).__name__)
        from zeroconf import NonUniqueNameException

        for name in sorted(names - set(self._infos)):
            info = self._info(name)
            try:
                # Probing for the name takes a few seconds: on the loop, never blocking it.
                await (await self._zc.async_register_service(info))
            except NonUniqueNameException:
                log.warning(f"⚠️ Site name not announced — {name}: another device on the LAN already answers to it")
                continue
            except Exception:  # noqa: BLE001 — one name's failure must not stop the rest; logged with its traceback
                log.error(f"❌ Site name not announced — {name}", exc_info=True)
                continue
            self._infos[name] = info
            log.info(f"⬆️ Site name announced — {name} · {self.ip}")

    async def close(self) -> None:
        if self._zc is None:
            return
        try:
            await self._zc.async_unregister_all_services()
            await self._zc.async_close()
        except Exception as exc:  # noqa: BLE001 — stopping: say it, never stop the server's other parts stopping
            log.warning("⚠️ Site names — zeroconf didn't close cleanly", error=str(exc), error_type=type(exc).__name__)
        self._zc = None
        self._infos.clear()


def make_publisher(ip: str) -> NamePublisher:
    """This system's way of announcing names."""
    if sys.platform.startswith("linux"):
        return AvahiPublisher(ip)
    return ZeroconfPublisher(ip)
