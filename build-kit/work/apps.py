"""The Hiro League apps, read from apps.toml beside this file: the one place hiro-work, the deploy and the data
copies learn about an app. A new app adds its row there (hiro-docs standards/new-extension.md).

Each environment's block of ports is 7N00-7N49 (env N): the core has 00 (admin API), 01 (extension socket: the channel
plugins and the apps), 02 (admin UI), 13 (HTTP status API) and 17 (its gateway, for device chat); 18 is the device web app
(device-web, the Flutter app for device chat); each app has the two its row names.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

FILE = Path(__file__).with_name("apps.toml")
BLOCK = 50  # ports per environment: 7N00-7N49
CORE_PORTS = {"core-admin": 0, "core-socket": 1, "core-ui": 2, "core-http": 13, "core-gateway": 17,
              "device-web": 18}


@dataclass(frozen=True)
class App:
    repo: str
    name: str
    title: str
    api_port: int
    ui_port: int
    backend: str
    api: str
    frontend: str
    ui_api_env: str
    data: str
    settings_db: str
    site_key: str
    live_port: int
    copy_data: bool
    api_env: dict[str, str] = field(default_factory=dict)


def load(path: Path = FILE) -> list[App]:
    """The apps in the file's order, checked: known fields, "env" or "repo" data, ports inside the block and unique."""
    rows = tomllib.loads(path.read_text(encoding="utf-8"))["app"]
    apps = [App(**row) for row in rows]
    taken = dict((offset, name) for name, offset in CORE_PORTS.items())
    for a in apps:
        if a.data not in ("env", "repo"):
            raise ValueError(f"{path.name}: {a.repo}'s data is 'env' or 'repo', not {a.data!r}")
        for side, offset in (("api", a.api_port), ("ui", a.ui_port)):
            if not 0 <= offset < BLOCK:
                raise ValueError(f"{path.name}: {a.repo}'s {side}_port {offset} is outside 00-{BLOCK - 1}")
            if offset in taken:
                raise ValueError(f"{path.name}: {a.repo}'s {side}_port {offset} is {taken[offset]}'s already")
            taken[offset] = f"{a.repo}-{side}"
    return apps


APPS = load()
BY_REPO = {a.repo: a for a in APPS}


def ports(env: int, apps: list[App] = APPS) -> dict[str, int]:
    """Environment N's ports by name: the core's, then each app's API and UI (7000 + 100 N + offset)."""
    base = 7000 + 100 * env
    out = {name: base + offset for name, offset in CORE_PORTS.items()}
    for a in apps:
        out[f"{a.repo}-api"], out[f"{a.repo}-ui"] = base + a.api_port, base + a.ui_port
    return dict(sorted(out.items(), key=lambda kv: kv[1]))


def env_of_port(port: int) -> int | None:
    """The environment whose block holds *port*, or None."""
    env, offset = divmod(port - 7000, 100)
    return env if 0 <= env <= 5 and 0 <= offset < BLOCK and port >= 7000 else None
