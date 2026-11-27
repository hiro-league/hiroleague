"""The Hiro home: the one machine-wide folder per system where the core and the apps it installs keep their programs,
and each app its data (the design's §7). Pure: paths only, nothing made here.

    /opt/hiroleague                            Linux (Simone's deploy: HIRO_HOME, deploy/deploy.sh)
    %ProgramData%\\HiroLeague                   Windows (windows_service.default_home)
    /Library/Application Support/HiroLeague    Mac (mac_service.HOME)

``HIRO_HOME`` in the environment names another (a test environment's scratch home, a Windows service installed with
``--home``). The elevated system part reads it the same way and never from a job, so a job can't point it elsewhere.

``<home>/cache/downloads/`` keeps one checked copy of each pinned download (WinSW, Caddy), named by its hash, for
every service on the machine (``hiro_commons.fetch``).

One app's folder, ``<home>/apps/<key>/``:

    releases/<version>/   the app's environment for that version (three kept)
    current               the release that runs (a link; a junction on Windows)
    app.env               the service's environment (DATA_DIR, PORT, HIRO_CORE_URL, the install's pairing code)
    data/                 the app's DATA_DIR: its databases, its key, its files
    service/              Windows: the service's own WinSW and its configuration

A service core's channels, ``<home>/channels/`` (a core a person runs keeps them as uv's tools in their profile):

    tools/                each channel's tool environment (UV_TOOL_DIR), on the core's own Python
    bin/                  each channel's command (UV_TOOL_BIN_DIR), on the service's PATH
    cache/                uv's cache for them (UV_CACHE_DIR)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

ENV_HIRO_HOME = "HIRO_HOME"
APPS = "apps"
CHANNELS = "channels"


def default_home(platform: str = sys.platform) -> Path:
    if platform == "win32":
        return Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "HiroLeague"
    if platform == "darwin":
        return Path("/Library/Application Support/HiroLeague")
    return Path("/opt/hiroleague")


def hiro_home() -> Path:
    """This machine's Hiro home: HIRO_HOME, else the system's default."""
    named = os.environ.get(ENV_HIRO_HOME, "").strip()
    return Path(named) if named else default_home()


@dataclass(frozen=True)
class AppFolder:
    """Where one installed app keeps its parts, under a Hiro home."""

    home: Path
    key: str

    @property
    def root(self) -> Path:
        return self.home / APPS / self.key

    @property
    def releases(self) -> Path:
        return self.root / "releases"

    def release(self, version: str) -> Path:
        return self.releases / version

    @property
    def current(self) -> Path:
        return self.root / "current"

    @property
    def env_file(self) -> Path:
        return self.root / "app.env"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def service_dir(self) -> Path:
        return self.root / "service"


def app_folder(key: str, home: Path | None = None) -> AppFolder:
    return AppFolder(home=home or hiro_home(), key=key)


@dataclass(frozen=True)
class ChannelsFolder:
    """Where a service core keeps its channels' programs, under a Hiro home."""

    home: Path

    @property
    def root(self) -> Path:
        return self.home / CHANNELS

    @property
    def tools(self) -> Path:
        return self.root / "tools"

    @property
    def bin(self) -> Path:
        return self.root / "bin"

    @property
    def cache(self) -> Path:
        return self.root / "cache"


def channels_folder(home: Path | None = None) -> ChannelsFolder:
    return ChannelsFolder(home=home or hiro_home())
