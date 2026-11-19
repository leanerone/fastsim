"""Shared fixtures: session pairs on random free ports."""
import asyncio
import random
import sys
import time
from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from fastsim.core.manager import SessionManager  # noqa: E402

PROFILES_DIR = BACKEND / "profiles"
SCENARIOS_DIR = BACKEND / "scenarios"


def free_port() -> int:
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture()
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture()
def manager(event_loop):
    m = SessionManager(profiles_dir=str(PROFILES_DIR), scenarios_dir=str(SCENARIOS_DIR))
    yield m
    loop = event_loop
    loop.run_until_complete(m.shutdown())


@pytest.fixture()
def gem_pair(manager, event_loop):
    """Equipment (passive) + host (active) connected & communicating."""
    port = free_port()
    loop = event_loop

    async def setup():
        await manager.create_session("etcher-001.yaml", role="equipment",
                                     port=port, session_id="EQ")
        raw = yaml.safe_load((PROFILES_DIR / "etcher-001.yaml").read_text(encoding="utf-8"))
        raw["connection"]["mode"] = "ACTIVE"
        raw["connection"]["port"] = port
        raw["connection"]["timeouts"]["t3"] = 10
        (PROFILES_DIR / "_test_host.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
        await manager.create_session("_test_host.yaml", role="host",
                                     port=port, session_id="HOST")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            st = manager.get("EQ").states()
            if st["hsms"] == "SELECTED" and st["communication"] == "COMMUNICATING":
                break
            await asyncio.sleep(0.1)
        return manager.get("EQ"), manager.get("HOST")

    eq, host = loop.run_until_complete(setup())
    yield eq, host
    # cleanup temp profile
    p = PROFILES_DIR / "_test_host.yaml"
    if p.exists():
        p.unlink()
