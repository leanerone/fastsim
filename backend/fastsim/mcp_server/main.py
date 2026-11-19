"""FastSim MCP Server (stdio, JSON-RPC 2.0, zero-dependency).

Expose the FastSim simulator to AI clients (ZCode / Claude / GLM / any MCP host):
    python -m fastsim.mcp_server            # needs FastSim backend running
Env: FASTSIM_API (default http://127.0.0.1:8000/api/v1)

Run `python -m fastsim.mcp_server --selftest` for an offline protocol check.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

API = os.environ.get("FASTSIM_API", "http://127.0.0.1:8000/api/v1")
SERVER_INFO = {"name": "fastsim-mcp", "version": "0.1.0"}


# ------------------------------------------------------------------ helpers
def _call(method: str, path: str, body: Optional[dict] = None) -> Any:
    url = API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode() or "null")
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:300]
        raise RuntimeError(f"HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"FastSim backend not reachable at {API}: {e}") from None


def _num(x):
    if isinstance(x, str):
        try:
            return int(x)
        except ValueError:
            return x
    return x


# ------------------------------------------------------------------ tools
def _tool(name: str, desc: str, schema: dict) -> dict:
    return {"name": name, "description": desc, "inputSchema": schema}


def obj(props: Dict[str, Any], required: List[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


TOOLS = [
    _tool("fs_health", "FastSim 后端健康检查与版本", obj({}, [])),
    _tool("fs_list_sessions", "列出全部模拟会话及其状态", obj({}, [])),
    _tool("fs_list_profiles", "列出可用机台 Profile", obj({}, [])),
    _tool("fs_get_profile", "读取机台 Profile（GEM 数据字典）",
          obj({"name": {"type": "string"}}, ["name"])),
    _tool("fs_create_session", "创建模拟会话（equipment=模拟机台 / host=模拟主机）",
          obj({"profile": {"type": "string", "description": "profile 文件名"},
               "role": {"type": "string", "enum": ["equipment", "host"]},
               "name": {"type": "string"},
               "port": {"type": "integer"},
               "session_id": {"type": "string"}}, ["profile"])),
    _tool("fs_close_session", "删除会话",
          obj({"session": {"type": "string"}}, ["session"])),
    _tool("fs_connect", "启动连接（host 角色发起 ACTIVE 连接）",
          obj({"session": {"type": "string"}}, ["session"])),
    _tool("fs_get_state", "查询三层状态（HSMS/通讯/控制）",
          obj({"session": {"type": "string"}}, ["session"])),
    _tool("fs_send_sml", "发送任意 SECS 消息（SML 文本，W 位自动等待应答并返回应答 SML）",
          obj({"session": {"type": "string"},
               "sml": {"type": "string", "description": "如 S1F3 W <L [1] <U4 1002>>"}},
          ["session", "sml"])),
    _tool("fs_get_log", "拉取会话通信日志（SML 格式，可过滤）",
          obj({"session": {"type": "string"},
               "sf": {"type": "string"}, "direction": {"type": "string"},
               "tail": {"type": "integer"}}, ["session"])),
    _tool("fs_trigger_event", "设备端触发采集事件（S6F11 上报）",
          obj({"session": {"type": "string"}, "ceid": {"type": "string"},
               "values": {"type": "object"}}, ["session", "ceid"])),
    _tool("fs_set_alarm", "设备端触发/清除报警（S5F1，自动联动 ceid_on/ceid_off）",
          obj({"session": {"type": "string"}, "alid": {"type": "string"},
               "on": {"type": "boolean"}}, ["session", "alid", "on"])),
    _tool("fs_set_variable", "设置 SV/DV/EC 变量值",
          obj({"session": {"type": "string"}, "vid": {"type": "string"},
               "value": {}}, ["session", "vid", "value"])),
    _tool("fs_get_variables", "读取全部 SV/DV/EC 定义与当前值",
          obj({"session": {"type": "string"}}, ["session"])),
    _tool("fs_remote_command", "主机端发送远程命令 S2F41，返回 HCACK",
          obj({"session": {"type": "string"}, "rcmd": {"type": "string"},
               "params": {"type": "object"}}, ["session", "rcmd"])),
    _tool("fs_subscribe", "主机端订阅事件报告（S2F33+S2F35+S2F37 一键完成）",
          obj({"session": {"type": "string"}, "ceid": {"type": "string"},
               "rptid": {"type": "string"}, "svids": {"type": "array", "items": {"type": "string"}}},
          ["session", "ceid", "rptid", "svids"])),
    _tool("fs_query_sv", "主机端 S1F3 查询变量值",
          obj({"session": {"type": "string"},
               "svids": {"type": "array", "items": {"type": "string"}}},
          ["session", "svids"])),
    _tool("fs_run_scenario", "运行 YAML 场景并返回步骤报告（含断言结果）",
          obj({"session": {"type": "string"}, "scenario": {"type": "string"}},
          ["session", "scenario"])),
    _tool("fs_list_scenarios", "列出可用场景", obj({}, [])),
    _tool("fs_terminal", "主机端发送终端消息 S10F3",
          obj({"session": {"type": "string"}, "text": {"type": "string"}},
          ["session", "text"])),
    _tool("fs_sml_explain", "解析 SML 文本为结构化说明（AI 自校验用）",
          obj({"sml": {"type": "string"}}, ["sml"])),
]

PROMPTS = [
    {"name": "build-gem-scenario",
     "description": "引导 AI 从测试需求生成 FastSim 场景 YAML（subscribe/remote_command/wait_event/query_sv 断言）"},
    {"name": "diagnose-timeout",
     "description": "T3/T7 超时排查：拉取日志、检查状态机与对端配置"},
]


def _dispatch_tool(name: str, args: dict) -> str:
    if name == "fs_health":
        return _json(_call("GET", "/health"))
    if name == "fs_list_sessions":
        return _json(_call("GET", "/sessions"))
    if name == "fs_list_profiles":
        return _json(_call("GET", "/profiles"))
    if name == "fs_get_profile":
        return _json(_call("GET", "/profiles/" + str(args["name"])))
    if name == "fs_create_session":
        return _json(_call("POST", "/sessions", args))
    if name == "fs_close_session":
        return _json(_call("DELETE", "/sessions/" + str(args["session"])))
    if name == "fs_connect":
        return _json(_call("POST", f"/sessions/{args['session']}/connect"))
    if name == "fs_get_state":
        return _json(_call("GET", f"/sessions/{args['session']}/state"))
    if name == "fs_send_sml":
        return _json(_call("POST", f"/sessions/{args['session']}/send",
                           {"sml": args["sml"]}))
    if name == "fs_get_log":
        q = []
        if args.get("sf"):
            q.append("sf=" + args["sf"])
        if args.get("direction"):
            q.append("direction=" + args["direction"])
        q.append("tail=" + str(args.get("tail", 50)))
        return _json(_call("GET", f"/sessions/{args['session']}/logs?" + "&".join(q)))
    if name == "fs_trigger_event":
        return _json(_call("POST", f"/sessions/{args['session']}/events/{_num(args['ceid'])}/trigger",
                           {"values": args.get("values")}))
    if name == "fs_set_alarm":
        action = "set" if args.get("on", True) else "clear"
        return _json(_call("POST", f"/sessions/{args['session']}/alarms/{_num(args['alid'])}/{action}"))
    if name == "fs_set_variable":
        return _json(_call("PUT", f"/sessions/{args['session']}/variables",
                           {"vid": _num(args["vid"]), "value": args["value"]}))
    if name == "fs_get_variables":
        return _json(_call("GET", f"/sessions/{args['session']}/variables"))
    if name == "fs_remote_command":
        return _json(_call("POST", f"/sessions/{args['session']}/remote-command",
                           {"rcmd": args["rcmd"], "params": args.get("params", {})}))
    if name == "fs_subscribe":
        return _json(_call("POST", f"/sessions/{args['session']}/subscribe",
                           {"ceid": _num(args["ceid"]), "rptid": _num(args["rptid"]),
                            "svids": [_num(s) for s in args.get("svids", [])]}))
    if name == "fs_query_sv":
        return _json(_call("POST", f"/sessions/{args['session']}/query-sv",
                           {"svids": [_num(s) for s in args["svids"]]}))
    if name == "fs_run_scenario":
        return _json(_call("POST", f"/sessions/{args['session']}/scenario/{args['scenario']}/run", {}))
    if name == "fs_list_scenarios":
        return _json(_call("GET", "/scenarios"))
    if name == "fs_terminal":
        return _json(_call("POST", f"/sessions/{args['session']}/terminal",
                           {"text": args["text"]}))
    if name == "fs_sml_explain":
        return _sml_explain(args["sml"])
    raise RuntimeError(f"unknown tool {name}")


def _sml_explain(sml: str) -> str:
    sys.path.insert(0, str(_backend_root()))
    from fastsim.engine.builtin import sml as smlmod
    msg = smlmod.parse(sml)
    out = {
        "stream": msg.stream, "function": msg.function, "sf": msg.sf,
        "w_bit": msg.w_bit, "name": msg.name,
        "body": msg.body.to_dict() if msg.body is not None else None,
        "body_sml": msg.body.to_sml() if msg.body is not None else None,
    }
    return _json(out)


def _backend_root() -> "os.PathLike":
    return __file__.rsplit("fastsim", 1)[0]


def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, indent=1, default=str)


# ------------------------------------------------------------------ MCP loop
def handle(req: dict) -> Optional[dict]:
    method = req.get("method", "")
    rid = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": rid, "result": {
            "protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}, "prompts": {}},
            "serverInfo": SERVER_INFO}}
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": rid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}}
    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"prompts": PROMPTS}}
    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": rid, "result": {"resources": []}}
    if method == "tools/call":
        name = req["params"]["name"]
        args = req["params"].get("args") or req["params"].get("arguments") or {}
        try:
            text = _dispatch_tool(name, args)
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": text}], "isError": False}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": rid, "result": {
                "content": [{"type": "text", "text": f"ERROR: {exc}"}], "isError": True}}
    if rid is not None:
        return {"jsonrpc": "2.0", "id": rid, "error": {
            "code": -32601, "message": f"method not found: {method}"}}
    return None


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            rsp = handle(req)
        except Exception as exc:
            rsp = {"jsonrpc": "2.0", "id": req.get("id"),
                   "error": {"code": -32603, "message": str(exc)}}
        if rsp is not None:
            sys.stdout.write(json.dumps(rsp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


def selftest() -> int:
    """Offline protocol check (no backend needed)."""
    import io
    reqs = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05"}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                    "params": {"name": "fs_sml_explain",
                               "args": {"sml": "S1F13 W <L [2] <A \"X\"> <A \"Y\">>"}}} ),
    ]
    inp = io.StringIO("\n".join(reqs) + "\n")
    old = sys.stdin
    sys.stdin = inp
    out = io.StringIO()
    oldout = sys.stdout
    sys.stdout = out
    try:
        serve()
    finally:
        sys.stdin = old
        sys.stdout = oldout
    lines = [json.loads(x) for x in out.getvalue().splitlines() if x.strip()]
    ok = len(lines) == 3 and any("tools" in l.get("result", {}) for l in lines)
    sml_ok = any("S1F13" in json.dumps(l) for l in lines)
    print(f"responses={len(lines)} tools_listed={ok} sml_explain={sml_ok}")
    return 0 if (ok and sml_ok) else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    serve()
