"""The front door's whole configuration (docs/site-names-design.md): pure, built from the names the core serves.

The front door is Caddy, a service of its own set up by ``hiro service install`` (hirocli/front_door_setup.py). The
core never writes a Caddy file or runs a reload: at its start and on every change to a name it loads this whole
configuration through Caddy's admin API (runtime/site_names.py). Each load replaces everything Caddy has, its admin
listener included, so every load carries the same admin block: a load without one moves the API to Caddy's default
``localhost:2019`` (seen Nov 25, 2026), where another Caddy may listen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .site_names import DOMAIN, Site

# What `hiro service install` gives the core's service (HIRO_FRONT_DOOR): Caddy's admin address as Caddy writes it.
# Linux and Mac: a unix socket only Caddy's and the core's accounts open; Windows: loopback (Caddy takes no socket
# there, and Python has no AF_UNIX on Windows), where Caddy checks the Host of every call.
ENV_FRONT_DOOR = "HIRO_FRONT_DOOR"
_UNIX = "unix/"


class FrontDoorAddressError(ValueError):
    """``HIRO_FRONT_DOOR`` isn't an address the core can reach Caddy's admin API on."""


@dataclass(frozen=True)
class AdminAddress:
    """Where Caddy's admin API listens: ``caddy`` as its admin block writes it, and how the core reaches it."""

    caddy: str
    socket: str = ""  # a unix socket's path
    host_port: str = ""  # 127.0.0.1:18079

    @property
    def base_url(self) -> str:
        # Over a socket the host is a name only; Caddy checks a loopback listener's Host against its origins.
        return f"http://{self.host_port}" if self.host_port else "http://localhost"


def parse_admin(text: str) -> AdminAddress:
    """``unix//run/hiro-caddy/admin.sock|0660`` or ``127.0.0.1:18079``; anything else raises FrontDoorAddressError."""
    value = (text or "").strip()
    if value.startswith(_UNIX):
        path = value[len(_UNIX):].split("|", 1)[0]
        if path.startswith("/") and len(path) > 1:
            return AdminAddress(caddy=value, socket=path)
    else:
        host, sep, port = value.rpartition(":")
        if sep and host in ("127.0.0.1", "localhost") and port.isdigit() and 1 <= int(port) <= 65535:
            return AdminAddress(caddy=value, host_port=value)
    raise FrontDoorAddressError(
        f"The front door's address “{text}” is neither a unix socket (unix//path) nor a loopback port "
        "(127.0.0.1:port). Run `hiro service install` again."
    )


# The page for a name nobody serves (Caddy answered an empty 200 without one: phase 1, Nov 24, 2026).
_UNKNOWN_PAGE = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>No app here</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 32rem; margin: 4rem auto; padding: 0 1rem">
<h1 style="font-size: 1.4rem">No app answers to this name</h1>
<p>This server runs Hiro League, but no app uses this name. The apps and their names are in
<a href="http://{DOMAIN}">Hiro League's admin</a>.</p>
</body></html>"""


def _proxy(upstream: str, indent: str) -> list[str]:
    return [
        f"{indent}reverse_proxy {upstream} {{",
        f"{indent}\tflush_interval -1 # pass live updates (SSE) through at once",
        f"{indent}}}",
    ]


def render(sites: list[Site], admin: AdminAddress, *, http_port: int = 80, bind: str = "") -> str:
    """Caddy's whole configuration, as a Caddyfile: the admin block, one block per proxied name (an announced-only
    name has none), and the page for any other name. Names are sorted, so the same names give the same text (the
    core loads only what changed). ``http_port`` and ``bind`` change where it listens: port 80 on every address
    unless a test or an environment on the PC asks for another."""
    lines = [
        "# Loaded by Hiro League through Caddy's admin API (docs/site-names-design.md): the whole configuration, built",
        "# from the names the core serves. Change names with `hiro sites`; the core loads this again on each change.",
        "{",
        # Quoted: the Mac's socket is under "Application Support", and an unquoted space splits the address.
        f'\tadmin "{admin.caddy}"',
        "\tauto_https off",
    ]
    if http_port != 80:
        lines.append(f"\thttp_port {http_port}")
    if bind:
        lines.append(f"\tdefault_bind {bind}")
    lines.append("}")
    for s in sorted(sites, key=lambda s: s.name):
        if not s.upstream:
            continue
        lines += ["", f"http://{s.name} {{"]
        if s.paths:
            lines += [f"\t@paths path {' '.join(s.paths)}", "\thandle @paths {", *_proxy(s.upstream, "\t\t"), "\t}",
                      "\trespond 404"]
        else:
            lines += _proxy(s.upstream, "\t")
        lines.append("}")
    lines += [
        "",
        "# Any other name.",
        "http:// {",
        '\theader Content-Type "text/html; charset=utf-8"',
        "\trespond <<PAGE",
        *[f"\t\t{line}" for line in _UNKNOWN_PAGE.splitlines()],
        "\t\tPAGE 404",
        "}",
    ]
    return "\n".join(lines) + "\n"


def initial_config(admin: AdminAddress) -> str:
    """What Caddy starts with before the core's first load (and after a lost autosave): the admin API only, so it
    binds no port 80 until the core says what to serve. JSON, Caddy's own format (no adapter needed)."""
    return json.dumps({"admin": {"listen": admin.caddy}}, indent=2) + "\n"
