"""REST API + WebSocket end-to-end tests."""
import asyncio

import httpx
import pytest
import yaml

from fastsim.app import create_app
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
    raw = yaml.safe_load((PROFILES_DIR / "etcher-001.yaml").read_text(encoding="utf-8"))
    raw["connection"]["mode"] = "ACTIVE"
    raw["connection"]["port"] = port
    raw["connection"]["timeouts"] = {"t3": 10, "t5": 2, "t6": 3, "t7": 5, "t8": 5, "linktest": 0}
    (PROFILES_DIR / "_api_host.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return "_api_host.yaml"


def test_health_and_profiles(client, event_loop):
    async def run():
        r = await client.get("/api/v1/health")
        assert r.status_code == 200 and r.json()["status"] == "ok"
        r = await client.get("/api/v1/profiles")
        assert "etcher-001.yaml" in r.json()
    event_loop.run_until_complete(run())


def test_overview_and_source_endpoints(client, event_loop):
    async def run():
        r = await client.get("/api/v1/overview")
        assert r.status_code == 200
        body = r.json()
        assert {"sessions", "connected", "communicating", "messages"} <= set(body["totals"])
        assert body["sessions"] == []

        r = await client.get("/api/v1/profiles/etcher-001.yaml/text")
        assert r.status_code == 200 and "profile:" in r.json()["text"]

        r = await client.get("/api/v1/scenarios")
        names = r.json()
        assert names
        r = await client.get(f"/api/v1/scenarios/{names[0]}/text")
        assert r.status_code == 200 and "steps" in r.json()["text"]

        r = await client.get("/api/v1/profiles/missing.yaml/text")
        assert r.status_code == 404
    event_loop.run_until_complete(run())


def test_role_derives_transport_mode_for_builtin_pair(client, event_loop):
    port = free_port()

    async def run():
        r = await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": port, "session_id": "PAIR-EQ"})
        assert r.status_code == 200, r.text
        assert r.json()["connection"]["mode"] == "PASSIVE"

        r = await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "host",
            "port": port, "session_id": "PAIR-HOST"})
        assert r.status_code == 200, r.text
        assert r.json()["connection"]["mode"] == "ACTIVE"

        deadline = asyncio.get_event_loop().time() + 8
        state = {}
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get("/api/v1/sessions/PAIR-HOST/state")
            state = r.json()
            if state.get("communication") == "COMMUNICATING":
                break
            await asyncio.sleep(0.15)
        assert state.get("communication") == "COMMUNICATING", state

        await client.delete("/api/v1/sessions/PAIR-HOST")
        await client.delete("/api/v1/sessions/PAIR-EQ")

    event_loop.run_until_complete(run())


def test_log_kind_filter_applies_before_tail(client, app, event_loop):
    session_id = "LOG-FILTER"

    async def run():
        r = await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": free_port(), "session_id": session_id})
        assert r.status_code == 200, r.text
        wrapper = app.state.manager.get(session_id)
        wrapper.logs.extend([
            {"ts": 1, "kind": "data", "dir": "in", "sf": "S1F1"},
            {"ts": 2, "kind": "control", "dir": "in", "desc": "Linktest.req"},
            {"ts": 3, "kind": "control", "dir": "out", "desc": "Linktest.rsp"},
        ])

        r = await client.get(f"/api/v1/sessions/{session_id}/logs",
                             params={"kind": "data", "tail": 1})
        assert r.status_code == 200
        assert [item["sf"] for item in r.json()] == ["S1F1"]

        r = await client.get(f"/api/v1/sessions/{session_id}/logs",
                             params={"kind": "control", "tail": 1})
        assert [item["desc"] for item in r.json()] == ["Linktest.rsp"]
        await client.delete(f"/api/v1/sessions/{session_id}")

    event_loop.run_until_complete(run())


def test_full_session_lifecycle(client, event_loop):
    port = free_port()
    host_profile = _make_host_profile(port)

    async def run():
        # create equipment + host
        r = await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": port, "session_id": "EQ-A"})
        assert r.status_code == 200, r.text
        r = await client.post("/api/v1/sessions", json={
            "profile": host_profile, "role": "host",
            "port": port, "session_id": "HOST-A"})
        assert r.status_code == 200, r.text

        # wait for communication
        deadline = asyncio.get_event_loop().time() + 8
        states = {}
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get("/api/v1/sessions/EQ-A/state")
            states = r.json()
            if states.get("communication") == "COMMUNICATING":
                break
            await asyncio.sleep(0.15)
        assert states.get("communication") == "COMMUNICATING", states

        # duplicate id rejected
        r = await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": port, "session_id": "EQ-A"})
        assert r.status_code == 400

        # subscribe via API
        r = await client.post("/api/v1/sessions/HOST-A/subscribe", json={
            "ceid": 6001, "rptid": 7001, "svids": [1001, 1002, 1003]})
        assert r.status_code == 200

        # alarm via API -> logs show S5F1/S6F11 on host
        r = await client.post("/api/v1/sessions/EQ-A/alarms/5001/set")
        assert r.status_code == 200
        await asyncio.sleep(1.2)
        r = await client.get("/api/v1/sessions/HOST-A/logs", params={"tail": 100})
        sfs = [l.get("sf") for l in r.json()]
        assert "S5F1" in sfs and "S6F11" in sfs

        # SML send via API
        r = await client.post("/api/v1/sessions/HOST-A/send", json={
            "sml": 'S1F3 W <L [1] <U4 1002>>'})
        j = r.json()
        assert j["reply"]["sf"] == "S1F4"

        # variables
        r = await client.get("/api/v1/sessions/EQ-A/variables")
        v = r.json()
        assert v["status_variables"]["1002"]["value"] == "IDLE"
        r = await client.put("/api/v1/sessions/EQ-A/variables",
                             json={"vid": 1002, "value": "RUNNING"})
        assert r.status_code == 200
        r = await client.get("/api/v1/sessions/EQ-A/variables")
        assert r.json()["status_variables"]["1002"]["value"] == "RUNNING"
        r = await client.put("/api/v1/sessions/EQ-A/variables",
                             json={"vid": 99999, "value": 1})
        assert r.status_code == 404

        # trigger_event API
        r = await client.post("/api/v1/sessions/EQ-A/events/6005/trigger",
                              json={"values": {"2002": "LOT-9"}})
        assert r.status_code == 200

        # control state
        r = await client.post("/api/v1/sessions/EQ-A/control-state",
                              json={"target": "HOST_OFFLINE"})
        assert r.json()["control"] == "HOST_OFFLINE"
        r = await client.post("/api/v1/sessions/EQ-A/control-state",
                              json={"target": "ONLINE_REMOTE"})
        assert r.json()["control"] == "ONLINE_REMOTE"

        # delete sessions
        r = await client.delete("/api/v1/sessions/HOST-A")
        assert r.status_code == 200
        r = await client.delete("/api/v1/sessions/EQ-A")
        assert r.status_code == 200
        r = await client.get("/api/v1/sessions/EQ-A/state")
        assert r.status_code == 404

    event_loop.run_until_complete(run())
    # cleanup temp profile
    (PROFILES_DIR / "_api_host.yaml").unlink(missing_ok=True)


def test_scenario_via_api(client, event_loop):
    port = free_port()
    host_profile = _make_host_profile(port)

    async def run():
        await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": port, "session_id": "EQ-S"})
        await client.post("/api/v1/sessions", json={
            "profile": host_profile, "role": "host",
            "port": port, "session_id": "HOST-S"})
        deadline = asyncio.get_event_loop().time() + 8
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get("/api/v1/sessions/EQ-S/state")
            if r.json().get("communication") == "COMMUNICATING":
                break
            await asyncio.sleep(0.15)

        r = await client.get("/api/v1/scenarios")
        assert "remote-command-flow.yaml" in r.json()

        r = await client.post("/api/v1/sessions/HOST-S/scenario/remote-command-flow.yaml/run",
                              json={})
        rep = r.json()
        assert rep["ok"] is True, rep
        assert all(s["ok"] for s in rep["steps"])

    event_loop.run_until_complete(run())
    (PROFILES_DIR / "_api_host.yaml").unlink(missing_ok=True)


def test_record_and_replay(client, event_loop):
    port = free_port()
    host_profile = _make_host_profile(port)

    async def run():
        # EQ + HOST pair so real frames flow during recording
        await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": port, "session_id": "EQ-R"})
        await client.post("/api/v1/sessions", json={
            "profile": host_profile, "role": "host",
            "port": port, "session_id": "HOST-R"})
        deadline = asyncio.get_event_loop().time() + 8
        while asyncio.get_event_loop().time() < deadline:
            r = await client.get("/api/v1/sessions/EQ-R/state")
            if r.json().get("communication") == "COMMUNICATING":
                break
            await asyncio.sleep(0.15)
        r = await client.post("/api/v1/sessions/EQ-R/record/start")
        assert r.status_code == 200
        path = r.json()["recording"]
        await client.post("/api/v1/sessions/EQ-R/alarms/5001/set")
        await asyncio.sleep(1.2)
        r = await client.post("/api/v1/sessions/EQ-R/record/stop")
        j = r.json()
        assert j["frames"] > 0

        # compare with itself -> ok
        r = await client.post("/api/v1/recordings/compare",
                              json={"a": j["recording"], "b": j["recording"]})
        assert r.json()["ok"] is True

        # replay into a new equipment session (no host: sends fail gracefully)
        await client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": free_port(), "session_id": "EQ-R2"})
        r = await client.post("/api/v1/sessions/EQ-R2/replay",
                              json={"recording": path, "speed": 2.0})
        assert r.status_code == 200  # replayed count may be 0 (no link)

    event_loop.run_until_complete(run())
    (PROFILES_DIR / "_api_host.yaml").unlink(missing_ok=True)


def test_websocket_stream(app, event_loop):
    """WS stream test using starlette TestClient only (own managed loop)."""
    from starlette.testclient import TestClient

    port = free_port()
    host_profile = _make_host_profile(port)
    sync_client = TestClient(app)
    with sync_client:
        r = sync_client.post("/api/v1/sessions", json={
            "profile": "etcher-001.yaml", "role": "equipment",
            "port": port, "session_id": "EQ-W"})
        assert r.status_code == 200
        import time as _t
        deadline = _t.time() + 6
        while _t.time() < deadline:
            st = sync_client.get("/api/v1/sessions/EQ-W/state").json()
            if st.get("hsms") == "SELECTED":
                break
            _t.sleep(0.2)
        with sync_client.websocket_connect("/ws/EQ-W") as ws:
            first = ws.receive_json()
            assert first["type"] in ("state", "log", "session_created")
            sync_client.post("/api/v1/sessions/EQ-W/alarms/5001/set")
            # no host connected -> expect at least an "alarm" event over WS
            got_alarm = False
            for _ in range(10):
                msg = ws.receive_json()
                if msg["type"] in ("alarm", "log"):
                    got_alarm = True
                    break
            assert got_alarm, "no event pushed over websocket"
        sync_client.delete("/api/v1/sessions/EQ-W")
    (PROFILES_DIR / "_api_host.yaml").unlink(missing_ok=True)
