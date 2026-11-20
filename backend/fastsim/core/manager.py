"""SessionManager: multi-session lifecycle + global event bus + log ring buffer.

All events fan out to (a) per-session log buffers (persistence/search),
(b) WebSocket subscribers, (c) scenario runners awaiting conditions.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from typing import Any, AsyncIterator, Dict, List, Optional

from .profile import ProfileLoader

log = logging.getLogger("fastsim.manager")

MAX_LOG_PER_SESSION = 20000


class EventBus:
    """Simple async pub/sub."""

    def __init__(self):
        self._subs: Dict[str, List[asyncio.Queue]] = {}
        self._global_subs: List[asyncio.Queue] = []

    def subscribe(self, session_id: Optional[str] = None) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=10000)
        if session_id is None:
            self._global_subs.append(q)
        else:
            self._subs.setdefault(session_id, []).append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue, session_id: Optional[str] = None) -> None:
        if session_id is None:
            if q in self._global_subs:
                self._global_subs.remove(q)
        else:
            subs = self._subs.get(session_id, [])
            if q in subs:
                subs.remove(q)

    async def publish(self, session_id: str, event_type: str, payload: dict) -> None:
        item = {"session": session_id, "type": event_type, "payload": payload,
                "ts": time.time()}
        subs = list(self._subs.get(session_id, [])) + list(self._global_subs)
        for q in subs:
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                log.warning("event queue full, dropping %s", event_type)


class SessionWrapper:
    def __init__(self, session_id: str, name: str, profile_name: str, role: str,
                 profile: dict, emit):
        from fastsim.engine.builtin.session import GemSession
        self.id = session_id
        self.name = name
        self.profile_name = profile_name
        self.role = role
        self.profile = profile
        self.session = GemSession(session_id, profile, role, emit)
        self.logs: deque = deque(maxlen=MAX_LOG_PER_SESSION)
        self.created_at = time.time()
        self._record_task: Optional[asyncio.Task] = None

    def states(self) -> dict:
        return self.session.states()

    def to_dict(self) -> dict:
        cfg = self.session.protocol.config
        conn = dict(self.profile.get("connection", {}))
        conn.update({"mode": cfg.mode, "host": cfg.host, "port": cfg.port,
                     "device_id": cfg.device_id})
        conn["timeouts"] = {"t3": cfg.t3, "t5": cfg.t5, "t6": cfg.t6,
                            "t7": cfg.t7, "t8": cfg.t8,
                            "linktest": cfg.linktest_interval}
        return {
            "id": self.id,
            "name": self.name,
            "profile": self.profile_name,
            "role": self.role,
            "states": self.states(),
            "profile_meta": self.profile.get("profile", {}),
            "connection": conn,
            "alarms_active": [str(k) for k, v in self.session.alarms_set.items() if v],
            "message_count": len(self.logs),
            "created_at": self.created_at,
        }


class SessionManager:
    def __init__(self, profiles_dir: str = "profiles", scenarios_dir: str = "scenarios"):
        self.loader = ProfileLoader(profiles_dir)
        self.scenarios_dir = scenarios_dir
        self.sessions: Dict[str, SessionWrapper] = {}
        self.bus = EventBus()
        self._bg_tasks: "set[asyncio.Task]" = set()

    # ---------------- emit pipeline ----------------
    async def _emit(self, session_id: str, event_type: str, payload: dict) -> None:
        if event_type == "log":
            w = self.sessions.get(session_id)
            if w is not None:
                w.logs.append(payload)
        await self.bus.publish(session_id, event_type, payload)

    def _make_emit(self, session_id: str):
        async def emit(event_type: str, payload: dict) -> None:
            await self._emit(session_id, event_type, payload)
        return emit

    # ---------------- profiles ----------------
    def list_profiles(self) -> List[str]:
        return self.loader.list_profiles()

    def load_profile(self, name: str) -> dict:
        return self.loader.load(name)

    def validate_profile(self, text: str) -> dict:
        prof = self.loader.validate_text(text)
        return prof.model_dump()

    def save_profile(self, name: str, text: str) -> None:
        self.loader.save(name, text)

    # ---------------- sessions ----------------
    async def create_session(self, profile_name: str, role: Optional[str] = None,
                             name: Optional[str] = None,
                             host: Optional[str] = None,
                             port: Optional[int] = None,
                             session_id: Optional[str] = None,
                             mode: Optional[str] = None) -> dict:
        profile = self.loader.load(profile_name)
        role = (role or ("host" if profile["connection"]["mode"] == "ACTIVE"
                         else "equipment")).lower()
        if role not in ("equipment", "host"):
            raise ValueError("role must be equipment or host")
        mode = str(mode or ("ACTIVE" if role == "host" else "PASSIVE")).upper()
        if mode not in ("ACTIVE", "PASSIVE"):
            raise ValueError("mode must be ACTIVE or PASSIVE")
        profile["connection"]["mode"] = mode
        if session_id is None:
            base = name or profile.get("profile", {}).get("model") or profile_name
            session_id = f"{base}-{uuid.uuid4().hex[:6]}"
        if session_id in self.sessions:
            raise ValueError(f"session {session_id} already exists")
        w = SessionWrapper(session_id, name or session_id, profile_name, role,
                           profile, self._make_emit(session_id))
        if host is not None:
            w.session.protocol.config.host = host
        if port is not None:
            w.session.protocol.config.port = port
        self.sessions[session_id] = w
        await w.session.start()
        await self.bus.publish(session_id, "session_created", w.to_dict())
        return w.to_dict()

    async def destroy_session(self, session_id: str) -> bool:
        w = self.sessions.pop(session_id, None)
        if w is None:
            return False
        await w.session.stop()
        await self.bus.publish(session_id, "session_destroyed", {"id": session_id})
        return True

    def get(self, session_id: str) -> SessionWrapper:
        w = self.sessions.get(session_id)
        if w is None:
            raise KeyError(f"session not found: {session_id}")
        return w

    def list_sessions(self) -> List[dict]:
        return [w.to_dict() for w in self.sessions.values()]

    async def connect(self, session_id: str) -> dict:
        w = self.get(session_id)
        if w.role == "host" or w.profile["connection"]["mode"] == "ACTIVE":
            # for host role, connect = start active loop (already running);
            # ensure protocol is started
            if w.session.protocol._run_task is None or w.session.protocol._run_task.done():
                await w.session.protocol.start()
        return w.states()

    async def disconnect(self, session_id: str) -> dict:
        w = self.get(session_id)
        await w.session.protocol.stop()
        await w.session.protocol.start()
        return w.states()

    # ---------------- GEM operations (proxy to session) ----------------
    async def trigger_event(self, session_id: str, ceid: Any,
                            values: Optional[dict] = None) -> dict:
        w = self.get(session_id)
        if values:
            for vid, val in values.items():
                self._set_var(w, vid, val)
        sent = await w.session.trigger_collection_event(ceid)
        return {"sent": sent, "ceid": ceid}

    async def set_alarm(self, session_id: str, alid: Any, on: bool) -> dict:
        w = self.get(session_id)
        ok = await w.session.set_alarm(alid, on)
        if not ok:
            raise KeyError(f"unknown alarm {alid}")
        return {"alid": alid, "set": on}

    def _set_var(self, w: SessionWrapper, vid: Any, val: Any) -> None:
        s = w.session
        # JSON/YAML ids arrive as strings; engine stores numeric ids as int
        try:
            vid = int(vid)
        except (TypeError, ValueError):
            pass
        if vid in s.dv_defs:
            s.dv_values[vid] = val
        elif vid in s.sv_defs:
            s.sv_values[vid] = val
        elif vid in s.ec_defs:
            s.ec_values[vid] = val
        else:
            raise KeyError(f"unknown variable id {vid}")

    async def set_variable(self, session_id: str, vid: Any, val: Any) -> dict:
        w = self.get(session_id)
        self._set_var(w, vid, val)
        return {"vid": vid, "value": val}

    def get_variables(self, session_id: str) -> dict:
        w = self.get(session_id)
        s = w.session
        return {
            "status_variables": {str(k): {"def": v, "value": s.sv_values.get(k)}
                                 for k, v in s.sv_defs.items()},
            "data_variables": {str(k): {"def": v, "value": s.dv_values.get(k)}
                               for k, v in s.dv_defs.items()},
            "equipment_constants": {str(k): {"def": v, "value": s.ec_values.get(k)}
                                    for k, v in s.ec_defs.items()},
        }

    async def switch_control_state(self, session_id: str, target: str) -> dict:
        w = self.get(session_id)
        ok = await w.session.switch_control_state(target)
        if not ok:
            raise ValueError(f"invalid control state {target}")
        return w.states()

    async def send_sml(self, session_id: str, text: str,
                       wait_reply: Optional[bool] = None) -> dict:
        w = self.get(session_id)
        return await w.session.send_sml(text, wait_reply)

    async def remote_command(self, session_id: str, rcmd: str,
                             params: Optional[dict] = None) -> dict:
        w = self.get(session_id)
        return await w.session.host_send_remote_command(rcmd, params or {})

    async def subscribe_events(self, session_id: str, ceid: Any,
                               rptid: Any, svids: List[Any]) -> dict:
        w = self.get(session_id)
        await w.session.host_subscribe(ceid, rptid, svids)
        return {"ceid": ceid, "rptid": rptid, "svids": svids}

    async def query_sv(self, session_id: str, svids: List[Any]) -> dict:
        w = self.get(session_id)
        return await w.session.host_query_sv(svids)

    async def pp_upload(self, session_id: str, ppid: str, body_b64: str) -> dict:
        import base64
        w = self.get(session_id)
        return await w.session.host_pp_upload(ppid, base64.b64decode(body_b64))

    async def pp_download(self, session_id: str, ppid: str) -> dict:
        import base64
        w = self.get(session_id)
        data = await w.session.host_pp_download(ppid)
        return {"ppid": ppid, "body_b64": base64.b64encode(data or b"").decode()}

    async def terminal(self, session_id: str, text: str, tid: int = 0) -> dict:
        w = self.get(session_id)
        ack = await w.session.host_terminal(text, tid)
        return {"ackc10": ack}

    # ---------------- logs ----------------
    def get_logs(self, session_id: str, direction: Optional[str] = None,
                 sf: Optional[str] = None, text: Optional[str] = None,
                 kind: Optional[str] = None, tail: int = 200) -> List[dict]:
        w = self.get(session_id)
        logs = list(w.logs)
        if direction:
            logs = [l for l in logs if l.get("dir") == direction]
        if sf:
            logs = [l for l in logs if l.get("sf") == sf or
                    (l.get("kind") == "data" and l.get("sf", "").startswith(sf))]
        if text:
            logs = [l for l in logs
                    if text.lower() in json_dumps_safe(l)]
        if kind:
            logs = [l for l in logs if l.get("kind") == kind]
        return logs[-tail:]

    async def wait_for_event(self, session_id: str, event_type: str,
                             predicate: Any = None, timeout: float = 10.0) -> Optional[dict]:
        q = self.bus.subscribe(session_id)
        try:
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                try:
                    item = await asyncio.wait_for(q.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    return None
                if item["type"] == event_type:
                    if predicate is None or predicate(item["payload"]):
                        return item["payload"]
        finally:
            self.bus.unsubscribe(q, session_id)

    async def shutdown(self) -> None:
        for sid in list(self.sessions.keys()):
            await self.destroy_session(sid)


def json_dumps_safe(obj: Any) -> str:
    import json
    try:
        return json.dumps(obj, ensure_ascii=False, default=str).lower()
    except Exception:
        return str(obj).lower()
