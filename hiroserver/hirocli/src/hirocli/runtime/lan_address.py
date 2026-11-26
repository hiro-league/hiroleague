"""This machine's address on its LAN, for announcing the core's names when nobody set one (``site_names_ip``).

The address is the one the system would send from toward the rest of the network: a UDP socket "connected" to a
documentation address (RFC 5737) makes the system pick its outgoing interface by its routing table, and sends nothing.
A laptop on DHCP gets a new address now and then, so the core asks again each round (runtime/site_names.py).
"""

from __future__ import annotations

import ipaddress
import socket

from hiro_commons.log import Logger

log = Logger.get("SITE_NAMES")

_PROBE = ("192.0.2.1", 9)  # TEST-NET-1: never routed anywhere real, and a UDP connect sends no packet


def usable(address: str) -> str:
    """``address`` when other devices could reach this machine on it, else "": an IPv4 address that isn't loopback,
    link-local (169.254.x.x: no DHCP answered) or unspecified."""
    try:
        ip = ipaddress.IPv4Address(address)
    except ValueError:
        return ""
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
        return ""
    return address


def find() -> str:
    """This machine's LAN address, "" when it has none (no network, or no route out)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(_PROBE)
            address = probe.getsockname()[0]
    except OSError as exc:
        # No route out (unplugged, Wi-Fi off): the caller says once that names aren't announced
        log.debug("No LAN address: the system has no route out", error=str(exc))
        return ""
    return usable(address)
