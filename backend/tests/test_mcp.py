"""MCP server protocol tests (offline selftest + live backend roundtrip)."""
import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent


def test_mcp_offline_selftest():
    r = subprocess.run(
        [sys.executable, "-m", "fastsim.mcp_server", "--selftest"],
        cwd=str(BACKEND), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "tools_listed=True" in r.stdout
    assert "sml_explain=True" in r.stdout


def test_mcp_tools_list_shape():
    import fastsim.mcp_server.main as m
    req = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    rsp = m.handle(req)
    tools = rsp["result"]["tools"]
    names = [t["name"] for t in tools]
    # doc chapter 8 core tool set present
    for expected in ("fs_send_sml", "fs_set_alarm", "fs_trigger_event",
                     "fs_remote_command", "fs_run_scenario", "fs_get_log",
                     "fs_sml_explain", "fs_subscribe", "fs_query_sv"):
        assert expected in names, names
    # every tool has a valid input schema
    for t in tools:
        assert t["inputSchema"]["type"] == "object"


def test_mcp_initialize_and_ping():
    import fastsim.mcp_server.main as m
    r1 = m.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2024-11-05"}})
    assert r1["result"]["serverInfo"]["name"] == "fastsim-mcp"
    assert m.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert m.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
    err = m.handle({"jsonrpc": "2.0", "id": 3, "method": "no/such"})
    assert err["error"]["code"] == -32601


def test_mcp_sml_explain_direct():
    import fastsim.mcp_server.main as m
    text = m._dispatch_tool("fs_sml_explain",
                            {"sml": 'S1F13 W <L [2] <A "X"> <A "Y">>'})
    data = json.loads(text)
    assert data["sf"] == "S1F13" and data["w_bit"] is True
    assert data["body"]["value"][0]["value"] == ["X"]
