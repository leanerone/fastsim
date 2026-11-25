"""Local port probing for the session wizard.

A PASSIVE session can only start when its port is free. Probing before the
wizard creates a session turns "created but never connects" into an explicit,
actionable message (or an automatically picked free port).
"""
from __future__ import annotations

import os
import socket
from typing import Optional

PROBE_RANGE = 50


def _probe_host(host: Optional[str]) -> str:
    """Wildcard addresses cannot be connected to; probe the loopback instead."""
    value = (host or "").strip()
    if value in ("", "0.0.0.0", "::", "*"):
        return "127.0.0.1"
    return value


def _new_probe_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Mirror the options asyncio.start_server() applies on this platform, so a
    # successful probe means the real listener will bind too.
    if os.name == "nt":
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    return sock


def port_is_free(host: Optional[str], port: int) -> bool:
    """True when a PASSIVE session can bind host:port right now."""
    sock = _new_probe_socket()
    try:
        sock.bind((_probe_host(host), int(port)))
        return True
    except (OSError, ValueError):
        return False
    finally:
        sock.close()


def find_free_port(host: Optional[str], start: int,
                   count: int = PROBE_RANGE) -> int:
    """First port at or after `start` that is free; falls back to an OS-assigned one."""
    start = max(1, min(int(start), 65535))
    for port in range(start, min(start + max(count, 1), 65536)):
        if port_is_free(host, port):
            return port
    sock = _new_probe_socket()
    try:
        sock.bind((_probe_host(host), 0))
        return sock.getsockname()[1]
    except OSError:
        return start
    finally:
        sock.close()
