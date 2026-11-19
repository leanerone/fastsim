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
Report: {ok, steps: [{index, action, ok, detail, duration}]}
"""
from __future__ import annotations

import asyncio
import pathlib
import time
from typing import Any, Dict, List, Optional

import yaml

from .manager import SessionManager


class ScenarioError(Exception):
    pass


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

    async def run_file(self, name: str, session_id: str, scenarios_dir: str) -> dict:
        spec = self.load(name, scenarios_dir)
        sc = spec.get("scenario", spec)
        steps = sc.get("steps", [])
        return await self.run_steps(steps, session_id, sc.get("name", name))

    async def run_steps(self, steps: List[dict], session_id: str,
                        scenario_name: str = "") -> dict:
        results: List[dict] = []
        ok_all = True
        t0 = time.time()
        ctx: Dict[str, Any] = {"events": []}
        # scenario-wide event tap: capture every bus event from the start so
        # wait_event can match events emitted before the step runs
        q = self.mgr.bus.subscribe(None)
        collector = asyncio.create_task(self._collect(q, ctx))
        try:
            for i, step in enumerate(steps):
                action = step.get("action") or next(iter(step.keys()))
                params = step.get(action, step) if "action" in step else step
                sid = step.get("session", session_id)
                t1 = time.time()
                entry = {"index": i, "action": action, "session": sid, "ok": False}
                try:
                    detail = await self._run_step(action, params, sid, ctx, entry)
                    entry["ok"] = True
                    entry["detail"] = detail
                except Exception as exc:
                    entry["ok"] = False
                    entry["detail"] = {"error": str(exc)}
                    entry["duration"] = round(time.time() - t1, 3)
                    results.append(entry)
                    ok_all = False
                    break
                entry["duration"] = round(time.time() - t1, 3)
                results.append(entry)
        finally:
            collector.cancel()
            self.mgr.bus.unsubscribe(q)
        return {"scenario": scenario_name, "ok": ok_all,
                "duration": round(time.time() - t0, 3), "steps": results}

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
                        ctx: dict, entry: dict) -> Any:
        m = self.mgr
        if action == "send":
            r = await m.send_sml(sid, p.get("sml", ""))
            if not r.get("sent"):
                raise ScenarioError("send failed")
            return r
        if action == "subscribe":
            return await m.subscribe_events(sid, p["ceid"], p["rptid"],
                                            p.get("svids", []))
        if action == "remote_command":
            r = await m.remote_command(sid, p["rcmd"], p.get("params", {}))
            if "expect_hcack" in p and r.get("hcack") != p["expect_hcack"]:
                raise ScenarioError(f"hcack={r.get('hcack')} expect {p['expect_hcack']}")
            return r
        if action == "set_alarm":
            return await m.set_alarm(sid, p["alid"], bool(p.get("on", True)))
        if action == "trigger_event":
            return await m.trigger_event(sid, p["ceid"], p.get("values"))
        if action == "set_variable":
            return await m.set_variable(sid, p["vid"], p["value"])
        if action == "query_sv":
            vals = await m.query_sv(sid, p["svids"])
            expect = p.get("expect") or {}
            for k, want in expect.items():
                got = vals.get(str(k), vals.get(k))
                if str(got) != str(want):
                    raise ScenarioError(f"SV {k}: got {got!r}, expect {want!r}")
            ctx["last_query"] = vals
            return vals
        if action == "wait_event":
            where = p.get("where") or {}
            # first check events already captured since scenario start
            buffered = self._find_buffered_event(ctx, p["event"], where, sid)
            if buffered is not None:
                if not p.get("expect_found", True):
                    raise ScenarioError(f"event {p['event']} unexpectedly seen: {buffered}")
                ctx["last_event"] = buffered
                return buffered

            def pred(payload: dict) -> bool:
                for k, want in where.items():
                    if str(payload.get(k)) != str(want):
                        return False
                return True

            got = await m.wait_for_event(sid, p["event"], pred,
                                         timeout=float(p.get("timeout", 10)))
            if p.get("expect_found", True) and got is None:
                raise ScenarioError(f"event {p['event']} {where} not seen in time")
            if not p.get("expect_found", True) and got is not None:
                raise ScenarioError(f"event {p['event']} unexpectedly seen: {got}")
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
        raise ScenarioError(f"unknown action: {action}")
