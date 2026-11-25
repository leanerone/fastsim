"""Regression tests for the UX-oriented backend changes.

Covers: port probing, surfaced connection issues (no silent failures),
friendly send errors, structured reply data, variables_changed events,
scenario manifest + role mismatch + failure hints.
"""
import asyncio
import socket

import httpx
import pytest

from fastsim.app import create_app
from fastsim.core.scenario import ScenarioRunner, describe_step
from tests.conftest import PROFILES_DIR, free_port


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
def client(app, event_loop):
    transport = httpx.ASGITransport(app=app)
    c = httpx.AsyncClient(transport=transport, base_url="http://test")
    yield c
    event_loop.run_until_complete(c.aclose())
    event_loop.run_until_complete(app.state.manager.shutdown())


def _make_host_profile(port: int) -> str:
    import yaml
    raw = yaml.safe_load((PROFILES_DIR / "etcher-001.yaml").read_text(encoding="utf-8"))
    raw["connection"]["mode"] = "ACTIVE"
    raw["connection"]["port"] = port
    raw["connection"]["timeouts"] = {"t3": 10, "t5": 2, "t6": 3, "t7": 5, "t8": 5, "linktest": 0}
    (PROFILES_DIR / "_ux_host.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return "_ux_host.yaml"


async def _wait_communicating(client, sid, timeout=8.0):
    deadline = asyncio.get_event_loop().time() + timeout
    state = {}
    while asyncio.get_event_loop().time() < deadline:
        state = (await client.get(f"/api/v1/sessions/{sid}/state")).json()
        if state.get("communication") == "COMMUNICATING":
            return state
        await asyncio.sleep(0.15)
    return state


def test_port_probe_endpoints(client, event_loop):
    async def run():
        port = free_port()
        r = await client.get("/api/v1/ports/check", params={"port": port})
        assert r.status_code == 200 and r.json()["free"] is True

        blocker = socket.socket()
        blocker.bind(("127.0.0.1", port))
        blocker.listen(1)
        try:
            r = await client.get("/api/v1/ports/check", params={"port": port})
            assert r.json()["free"] is False
            r = await client.get("/api/v1/ports/free",
                                 params={"start": port, "count": 10})
            chosen = r.json()["port"]
            assert chosen != port
            r = await client.get("/api/v1/ports/check", params={"port": chosen})
            assert r.json()["free"] is True
        finally:
            blocker.close()
    event_loop.run_until_complete(run())


def test_port_in_use_issue_is_surfaced(client, app, event_loop):
    """A PASSIVE session on a busy port must report PORT_IN_USE, not stay silent."""
    port = free_port()
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)

    async def run():
        r = await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": port, "session_id": "UX-BUSY"})
        assert r.status_code == 200
        deadline = asyncio.get_event_loop().time() + 4
        issue = None
        while asyncio.get_event_loop().time() < deadline:
            d = (await client.get("/api/v1/sessions/UX-BUSY")).json()
            issue = d.get("issue")
            if issue:
                break
            await asyncio.sleep(0.1)
        assert issue and issue["code"] == "PORT_IN_USE", issue
        assert issue["hint"]
        # overview carries the same issue for the dashboard cards
        ov = (await client.get("/api/v1/overview")).json()
        row = next(s for s in ov["sessions"] if s["id"] == "UX-BUSY")
        assert row["issue"]["code"] == "PORT_IN_USE"
        await client.delete("/api/v1/sessions/UX-BUSY")
    try:
        event_loop.run_until_complete(run())
    finally:
        blocker.close()


def test_friendly_send_error_when_not_connected(client, event_loop):
    async def run():
        await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": free_port(), "session_id": "UX-NC"})
        r = await client.post("/api/v1/sessions/UX-NC/send", json={"sml": "S1F1 W"})
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert detail["code"] == "NOT_CONNECTED"
        assert "连接" in detail["message"] and detail["hint"]
        await client.delete("/api/v1/sessions/UX-NC")
    event_loop.run_until_complete(run())


def test_reply_data_and_variables_changed(client, app, event_loop):
    port = free_port()
    host_profile = _make_host_profile(port)

    async def run():
        await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": port, "session_id": "UX-EQ"})
        await client.post("/api/v1/sessions", json={
            "profile": host_profile, "role": "host",
            "port": port, "session_id": "UX-HOST"})
        assert (await _wait_communicating(client, "UX-HOST")).get("communication") == "COMMUNICATING"

        # structured reply data (no SML parsing needed by clients)
        r = await client.post("/api/v1/sessions/UX-HOST/send", json={"sml": "S1F1 W"})
        reply = r.json()["reply"]
        assert reply["sf"] == "S1F2" and reply["data"] == ["ETCH300", "2.1.0"]

        # remote command -> variables_changed event on the equipment session
        q = app.state.manager.bus.subscribe("UX-EQ")
        try:
            r = await client.post("/api/v1/sessions/UX-HOST/remote-command",
                                  json={"rcmd": "START", "params": {"RECIPE": "R-UX"}})
            assert r.json()["hcack"] == 0
            changes = None
            deadline = asyncio.get_event_loop().time() + 3
            while asyncio.get_event_loop().time() < deadline:
                try:
                    item = await asyncio.wait_for(q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if item["type"] == "variables_changed":
                    changes = item["payload"]["changes"]
                    break
            assert changes and changes["1002"]["to"] == "RUNNING", changes
            assert changes["2001"]["to"] == "R-UX"
        finally:
            app.state.manager.bus.unsubscribe(q, "UX-EQ")

        v = (await client.get("/api/v1/sessions/UX-EQ/variables")).json()
        assert v["status_variables"]["1002"]["value"] == "RUNNING"

        # overview marks the pair verified once a user W-primary was exchanged
        ov = (await client.get("/api/v1/overview")).json()
        assert ov["totals"]["verified"] >= 1
        assert ov["totals"]["data_messages"] > 0

        await client.delete("/api/v1/sessions/UX-HOST")
        await client.delete("/api/v1/sessions/UX-EQ")
    event_loop.run_until_complete(run())
    (PROFILES_DIR / "_ux_host.yaml").unlink(missing_ok=True)


def test_scenario_manifest_and_role_mismatch(client, event_loop):
    port = free_port()

    async def run():
        r = await client.get("/api/v1/scenarios/manifest")
        assert r.status_code == 200
        manifest = {m["file"]: m for m in r.json()}
        flow = manifest["remote-command-flow.yaml"]
        assert flow["role"] == "host" and flow["description"]
        assert flow["steps"][1]["summary"].startswith("发送远程命令 START")
        assert manifest["alarm-flow.yaml"]["role"] == "equipment"

        await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": port, "session_id": "UX-ROLE-EQ"})
        # host-only scenario on an equipment session -> explicit ROLE_MISMATCH
        r = await client.post(
            "/api/v1/sessions/UX-ROLE-EQ/scenario/remote-command-flow.yaml/run", json={})
        rep = r.json()
        assert rep["ok"] is False and rep["code"] == "ROLE_MISMATCH"
        assert "主机端" in rep["message"] and rep["hint"]
        await client.delete("/api/v1/sessions/UX-ROLE-EQ")
    event_loop.run_until_complete(run())


def test_scenario_failure_has_hint(manager, gem_pair, event_loop):
    runner = ScenarioRunner(manager)
    steps = [{"action": "query_sv", "svids": [1002], "expect": {"1002": "WRONG"}}]
    rep = event_loop.run_until_complete(runner.run_steps(steps, "HOST", "neg"))
    assert rep["ok"] is False
    detail = rep["steps"][0]["detail"]
    assert "expect" in detail["error"]          # raw text kept for compatibility
    assert detail["hint"] and detail["expected"] == {"1002": "WRONG"}
    assert rep["hint"] == detail["hint"]        # surfaced at report level too


def test_describe_step_summaries():
    assert describe_step("set_alarm", {"alid": 5001, "on": True}) == "触发报警 5001"
    assert describe_step("sleep", {"seconds": 0.5}) == "等待 0.5 秒"
    assert describe_step("remote_command", {"rcmd": "START", "params": {"RECIPE": "R-1"}}) \
        == "发送远程命令 START（RECIPE=R-1）"
    assert describe_step("subscribe", {"ceid": 6003, "rptid": 7002}) == "订阅事件 6003（报告 7002）"
