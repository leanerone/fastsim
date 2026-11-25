"""Scenario runner: declarative YAML step DSL with assertions.

Steps (each may set `session:` to override the bound session):
  - send:        {sml: "S1F3 W <L [1] <U4 1002>>"}
  - subscribe:   {ceid, rptid, svids}
  - remote_command: {rcmd, params}
  - set_alarm:   {alid, on: true|false}
  - trigger_event: {ceid, values?}
  - set_variable:{vid, value}
  - query_sv:    {svids, expect?}      expect: {svid: value} assertions
  - wait_event:  {event, timeout, where?}   event in collection_event|alarm|remote_command|terminal_display|established|state
  - control_state: {target}
  - pp_upload:   {ppid, body_b64}
  - pp_download: {ppid}
  - terminal:    {text}
  - connect / disconnect / sleep: {seconds}

Scenario-level metadata (optional):
  role: host | equipment | any   # which session role the scenario runs on.
                                 # A mismatch fails fast with code ROLE_MISMATCH
                                 # instead of a confusing first-step error.

Report: {ok, role, steps: [{index, action, summary, ok, detail, duration}]}
  `summary` is a one-line Chinese description of the step. A failed step's
  detail is {error, message, hint?, expected?, actual?}; the report also
  repeats error/message/hint at the top level for API and MCP clients.
"""
from __future__ import annotations

import asyncio
import pathlib
import time
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .errors import explain_exception
from .manager import SessionManager

ROLE_LABELS = {"host": "主机端", "equipment": "设备端", "any": "任意会话"}

HCACK_HINTS = {
    1: "设备不认识这条命令（HCACK=1）。请检查机台 Profile 的 remote_commands 是否定义了该命令。",
    2: "设备当前无法执行该命令（HCACK=2），通常与控制状态有关，例如设备处于离线。",
    3: "命令参数不合法（HCACK=3），请检查参数名与取值。",
    4: "命令已启动但尚未完成（HCACK=4）。",
    5: "命令被设备拒绝（HCACK=5）。",
}


class ScenarioError(Exception):
    """Step failure carrying a readable message, a fix hint and expected/actual."""

    def __init__(self, raw: str, message: str = "", hint: str = "",
                 expected: Any = None, actual: Any = None):
        super().__init__(raw)
        self.message = message or raw
        self.hint = hint
        self.expected = expected
        self.actual = actual

    def detail(self) -> dict:
        out: Dict[str, Any] = {"error": str(self), "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        if self.expected is not None:
            out["expected"] = self.expected
        if self.actual is not None:
            out["actual"] = self.actual
        return out


def scenario_role(sc: dict) -> str:
    role = str(sc.get("role") or "any").lower()
    return role if role in ROLE_LABELS else "any"


def parse_step(step: Any) -> Tuple[str, dict]:
    """Return (action, params) for either the flat or the nested step style."""
    if not isinstance(step, dict):
        raise ScenarioError(f"invalid step: {step!r}", f"步骤格式有误：{step!r}",
                            "每个步骤需要是一个包含 action 的对象")
    action = step.get("action") or next(iter(step.keys()))
    params = step.get(action) if "action" in step else step
    if params is None:
        # flat style: `- action: subscribe` with ceid/rptid at the same level
        params = step
    return str(action), (params if isinstance(params, dict) else {})


def _fmt_ids(values: Any) -> str:
    if isinstance(values, (list, tuple)):
        return ", ".join(str(v) for v in values)
    return str(values)


def _fmt_val(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _on_flag(p: dict) -> bool:
    # PyYAML (YAML 1.1) parses the bare key `on:` as boolean True, so the
    # value lands under p[True] rather than p["on"]. Accept both spellings.
    return bool(p.get("on", p.get(True, True)))


def describe_step(action: str, p: dict) -> str:
    """One-line Chinese summary of a step, shared by scenario cards and reports."""
    p = p if isinstance(p, dict) else {}
    if action == "send":
        sml = str(p.get("sml", "")).strip().split("\n")[0]
        return f"发送消息 {sml}" if sml else "发送消息"
    if action == "subscribe":
        return f"订阅事件 {_fmt_ids(p.get('ceid'))}（报告 {_fmt_ids(p.get('rptid'))}）"
    if action == "remote_command":
        detail = "，".join(f"{k}={_fmt_val(v)}" for k, v in (p.get("params") or {}).items())
        return f"发送远程命令 {p.get('rcmd')}" + (f"（{detail}）" if detail else "")
    if action == "set_alarm":
        return f"{'触发' if _on_flag(p) else '清除'}报警 {_fmt_ids(p.get('alid'))}"
    if action == "trigger_event":
        return f"触发采集事件 {_fmt_ids(p.get('ceid'))}"
    if action == "set_variable":
        return f"设置变量 {_fmt_ids(p.get('vid'))} = {_fmt_val(p.get('value'))}"
    if action == "query_sv":
        expect = "，".join(f"{k}={_fmt_val(v)}" for k, v in (p.get("expect") or {}).items())
        return f"查询变量 {_fmt_ids(p.get('svids'))}" + (f" 并校验 {expect}" if expect else "")
    if action == "wait_event":
        where = "，".join(f"{k}={_fmt_val(v)}" for k, v in (p.get("where") or {}).items())
        return (f"等待事件 {p.get('event')}" + (f"（{where}）" if where else "")
                + f"，最长 {_fmt_val(p.get('timeout', 10))} 秒")
    if action == "control_state":
        return f"切换控制状态为 {p.get('target')}"
    if action == "pp_upload":
        return f"上传配方 {_fmt_ids(p.get('ppid'))}"
    if action == "pp_download":
        return f"下载配方 {_fmt_ids(p.get('ppid'))}"
    if action == "terminal":
        return f"发送终端消息：{p.get('text')}"
    if action == "connect":
        return "启动链路"
    if action == "disconnect":
        return "断开并重启链路"
    if action == "sleep":
        return f"等待 {_fmt_val(p.get('seconds', p.get('sleep', 1)))} 秒"
    return action


class ScenarioRunner:
    def __init__(self, manager: SessionManager):
        self.mgr = manager

    # ------------- loading -------------
    def load(self, name: str, scenarios_dir: str) -> dict:
        path = pathlib.Path(scenarios_dir) / name
        if not path.exists() and not name.endswith(".yaml"):
            path = pathlib.Path(scenarios_dir) / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"scenario not found: {name}")
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    def manifest(self, scenarios_dir: str) -> List[dict]:
        """Structured index of every scenario: role, description, step summaries."""
        d = pathlib.Path(scenarios_dir)
        out: List[dict] = []
        for path in sorted(d.glob("*.yaml")) if d.exists() else []:
            item: Dict[str, Any] = {"file": path.name, "name": path.stem,
                                    "description": "", "role": "any", "steps": [],
                                    "error": None}
            try:
                spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                sc = spec.get("scenario", spec) if isinstance(spec, dict) else {}
                sc = sc if isinstance(sc, dict) else {}
                item["name"] = str(sc.get("name", path.stem))
                item["description"] = str(sc.get("description", ""))
                item["role"] = scenario_role(sc)
                for i, raw in enumerate(sc.get("steps") or []):
                    try:
                        action, params = parse_step(raw)
                        item["steps"].append({"index": i, "action": action,
                                              "summary": describe_step(action, params)})
                    except ScenarioError as exc:
                        item["steps"].append({"index": i, "action": "", "summary": exc.message})
            except Exception as exc:
                item["error"] = str(exc)
            out.append(item)
        return out

    async def run_file(self, name: str, session_id: str, scenarios_dir: str) -> dict:
        spec = self.load(name, scenarios_dir)
        sc = spec.get("scenario", spec)
        scenario_name = sc.get("name", name)
        role = scenario_role(sc)
        if role != "any":
            # A host-only scenario bound to the equipment session used to die in
            # step 2 with "hcack=None expect 0"; reject it up front instead.
            wrapper = self.mgr.sessions.get(session_id)
            actual = wrapper.role if wrapper is not None else None
            if actual is not None and actual != role:
                return {"scenario": scenario_name, "ok": False, "code": "ROLE_MISMATCH",
                        "role": role, "expected_role": role, "session_role": actual,
                        "error": f"scenario requires a {role} session, got {actual}",
                        "message": (f"该场景需要在{ROLE_LABELS[role]}会话上运行，"
                                    f"当前选择的是{ROLE_LABELS.get(actual, actual)}会话"),
                        "hint": f"请在{ROLE_LABELS[role]}会话上运行本场景",
                        "steps": [], "duration": 0.0}
        return await self.run_steps(sc.get("steps", []), session_id, scenario_name, role)

    async def run_steps(self, steps: List[dict], session_id: str,
                        scenario_name: str = "", role: str = "any") -> dict:
        results: List[dict] = []
        ok_all = True
        t0 = time.time()
        ctx: Dict[str, Any] = {"events": []}
        # scenario-wide event tap: capture every bus event from the start so
        # wait_event can match events emitted before the step runs
        q = self.mgr.bus.subscribe(None)
        collector = asyncio.create_task(self._collect(q, ctx))
        try:
            for i, raw in enumerate(steps):
                action, params = "", {}
                sid = session_id
                entry: Dict[str, Any] = {"index": i, "action": "", "summary": "",
                                         "session": sid, "ok": False}
                t1 = time.time()
                try:
                    action, params = parse_step(raw)
                    sid = params.get("session", session_id)
                    entry.update({"action": action, "session": sid,
                                  "summary": describe_step(action, params)})
                    entry["detail"] = await self._run_step(action, params, sid, ctx)
                    entry["ok"] = True
                except ScenarioError as exc:
                    entry["detail"] = exc.detail()
                except Exception as exc:
                    info = explain_exception(exc)
                    entry["detail"] = {**info, "error": str(exc)}
                entry["duration"] = round(time.time() - t1, 3)
                results.append(entry)
                if not entry["ok"]:
                    ok_all = False
                    break
        finally:
            collector.cancel()
            self.mgr.bus.unsubscribe(q)
        report: Dict[str, Any] = {"scenario": scenario_name, "ok": ok_all, "role": role,
                                  "duration": round(time.time() - t0, 3), "steps": results}
        if not ok_all:
            failed = results[-1]["detail"] if results else {}
            for key in ("error", "message", "hint"):
                if failed.get(key):
                    report[key] = failed[key]
        return report

    async def _collect(self, q: asyncio.Queue, ctx: dict) -> None:
        try:
            while True:
                item = await q.get()
                ctx["events"].append(item)
        except asyncio.CancelledError:
            pass

    def _find_buffered_event(self, ctx: dict, event_type: str, where: dict,
                             sid: Optional[str] = None) -> Optional[dict]:
        for item in ctx.get("events", []):
            if item["type"] != event_type:
                continue
            if sid is not None and item.get("session") != sid:
                continue
            payload = item.get("payload") or {}
            if all(str(payload.get(k)) == str(v) for k, v in where.items()):
                return payload
        return None

    # ------------- step dispatch -------------
    async def _run_step(self, action: str, p: dict, sid: str,
                        ctx: dict) -> Any:
        m = self.mgr
        if action == "send":
            r = await m.send_sml(sid, p.get("sml", ""))
            if not r.get("sent"):
                raise ScenarioError("send failed", "消息没有发出",
                                    "请确认会话已建立通信")
            return r
        if action == "subscribe":
            return await m.subscribe_events(sid, p["ceid"], p["rptid"],
                                            p.get("svids", []))
        if action == "remote_command":
            rcmd = p["rcmd"]
            r = await m.remote_command(sid, rcmd, p.get("params", {}))
            if "expect_hcack" in p and r.get("hcack") != p["expect_hcack"]:
                hcack, want = r.get("hcack"), p["expect_hcack"]
                if hcack is None:
                    message = "设备没有返回远程命令应答（S2F42）"
                    hint = ("请确认本场景绑定在主机端会话上，且主机已与设备建立通信。"
                            "在设备端会话上运行该步骤也会出现这个结果。")
                else:
                    message = f"设备返回 HCACK={hcack}，期望 {want}"
                    hint = HCACK_HINTS.get(hcack, "HCACK 非 0 表示命令未被接受。")
                raise ScenarioError(f"hcack={hcack} expect {want}", message, hint,
                                    expected={"hcack": want}, actual={"hcack": hcack})
            return r
        if action == "set_alarm":
            return await m.set_alarm(sid, p["alid"], _on_flag(p))
        if action == "trigger_event":
            return await m.trigger_event(sid, p["ceid"], p.get("values"))
        if action == "set_variable":
            return await m.set_variable(sid, p["vid"], p["value"])
        if action == "query_sv":
            svids = p["svids"]
            vals = await m.query_sv(sid, svids)
            expect = p.get("expect") or {}
            for k, want in expect.items():
                got = vals.get(str(k), vals.get(k))
                if str(got) != str(want):
                    raise ScenarioError(
                        f"SV {k}: got {got!r}, expect {want!r}",
                        f"变量 {k} 的实际值为 {got!r}，期望 {want!r}",
                        "请检查机台 Profile 的 behavior 是否为该命令或事件设置了对应变量，"
                        "以及场景是否在正确的会话上运行。",
                        expected={str(k): want}, actual={str(k): got})
            ctx["last_query"] = vals
            return vals
        if action == "wait_event":
            where = p.get("where") or {}
            timeout = float(p.get("timeout", 10))
            # first check events already captured since scenario start
            buffered = self._find_buffered_event(ctx, p["event"], where, sid)
            if buffered is not None:
                if not p.get("expect_found", True):
                    raise ScenarioError(f"event {p['event']} unexpectedly seen: {buffered}",
                                        f"出现了预期不应出现的事件 {p['event']}")
                ctx["last_event"] = buffered
                return buffered

            def pred(payload: dict) -> bool:
                for k, want in where.items():
                    if str(payload.get(k)) != str(want):
                        return False
                return True

            got = await m.wait_for_event(sid, p["event"], pred, timeout=timeout)
            if p.get("expect_found", True) and got is None:
                raise ScenarioError(
                    f"event {p['event']} {where} not seen in time",
                    f"在 {timeout:g} 秒内没有收到事件 {p['event']}",
                    "请确认主机已订阅并使能该事件（S2F33 / S2F35 / S2F37），"
                    "且设备端确实触发了它。")
            if not p.get("expect_found", True) and got is not None:
                raise ScenarioError(f"event {p['event']} unexpectedly seen: {got}",
                                    f"出现了预期不应出现的事件 {p['event']}")
            if got is not None:
                ctx["last_event"] = got
            return got
        if action == "control_state":
            return await m.switch_control_state(sid, p["target"])
        if action == "pp_upload":
            return await m.pp_upload(sid, p["ppid"], p["body_b64"])
        if action == "pp_download":
            return await m.pp_download(sid, p["ppid"])
        if action == "terminal":
            return await m.terminal(sid, p["text"])
        if action == "connect":
            return await m.connect(sid)
        if action == "disconnect":
            return await m.disconnect(sid)
        if action == "sleep":
            await asyncio.sleep(float(p.get("seconds", p.get("sleep", 1))))
            return {"slept": p.get("seconds", p.get("sleep", 1))}
        raise ScenarioError(f"unknown action: {action}",
                            f"未知的步骤类型：{action}",
                            "可用动作见 DEVELOPER.md 的场景 DSL 说明。")
