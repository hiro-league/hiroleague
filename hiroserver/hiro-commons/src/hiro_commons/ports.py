"""Whether a port is free on this machine: a bind test, the one every port check uses (issue 455).

A bind on 127.0.0.1 fails when something listens there and, on Windows, inside a range the system reserves (Hyper-V
and WSL take whole blocks): both show only by trying. On Linux and macOS the test sets SO_REUSEADDR as the servers
do, so a port a server just closed (TIME_WAIT) still counts as free; on Windows it doesn't, since there that option
lets a second socket take a port in use.
"""

from __future__ import annotations

import socket
import sys

from .constants.network import DEFAULT_LOCALHOST


def port_free(port: int, host: str = DEFAULT_LOCALHOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if sys.platform != "win32":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True
