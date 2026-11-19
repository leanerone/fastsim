"""GEM session: profile-driven equipment/host simulation on top of the builtin
HSMS-SS transport.

Equipment side implements the E30 core handler set (S1/S2/S5/S6/S7/S9/S10);
host side provides the subscription/remote-command/query helpers and parses
upcoming reports. Behavior rules from the machine profile make the simulated
tool react "like a real one" (remote command -> variable changes -> event).
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import sml as smlmod
from .hsms import (HsmsConfig, HsmsError, HsmsMessage, HsmsProtocol, HsmsState,
                   ConnectionLost, T3Timeout)
from .secs2 import Item

log = logging.getLogger("fastsim.session")

# ALCD bit: alarm set indicator (bit 7)
ALCD_SET = 0x80

# HCACK codes
HCACK_OK = 0
HCACK_INVALID_COMMAND = 1
HCACK_INVALID_PARAMETER = 2
HCACK_NOT_READY = 3
HCACK_WILL_PERFORM = 4
HCACK_NO_SUCH_PARAMETER = 5

CONTROL_STATES = ("EQUIPMENT_OFFLINE", "ATTEMPT_ONLINE", "HOST_OFFLINE",
                  "ONLINE_LOCAL", "ONLINE_REMOTE")


class CommunicationState:
    DISABLED = "DISABLED"
    NOT_COMMUNICATING = "NOT_COMMUNICATING"
    WAIT_CRA = "WAIT_CRA"
    WAIT_DELAY = "WAIT_DELAY"
    COMMUNICATING = "COMMUNICATING"


class GemSession:
    """One simulated SECS/GEM endpoint (role: equipment | host)."""

    def __init__(self, session_id: str, profile: dict, role: str,
                 emit: Callable[[str, dict], Any],
                 host: Optional[str] = None, port_override: Optional[int] = None):
        self.session_id = session_id
        self.profile = profile
        self.role = role  # 'equipment' | 'host'
        self.emit = emit  # async callback(event_type, payload)

        prof = profile.get("profile", {})
        conn = profile.get("connection", {})
        to = conn.get("timeouts", {})
        cfg = HsmsConfig(
            mode=conn.get("mode", "PASSIVE"),
            host=host if host is not None else conn.get("host", "127.0.0.1"),
            port=port_override if port_override is not None else conn.get("port", 5000),
            device_id=conn.get("device_id", 0),
            t3=to.get("t3", 45), t5=to.get("t5", 10), t6=to.get("t6", 5),
            t7=to.get("t7", 10), t8=to.get("t8", 5),
            linktest_interval=to.get("linktest", 30),
            name=session_id,
        )
        self.protocol = HsmsProtocol(cfg)
        self.protocol.on_data = self._on_data
        self.protocol.on_event = self._on_hsms_event
        self.protocol.on_frame = self._on_frame

        self.mdln = prof.get("mdln", "FASTSIM")
        self.softrev = prof.get("softrev", "1.0.0")

        # GEM object stores (ids normalized to int when numeric)
        self.sv_defs: Dict[Any, dict] = _norm_keys(profile.get("status_variables", {}) or {})
        self.dv_defs: Dict[Any, dict] = _norm_keys(profile.get("data_variables", {}) or {})
        self.ec_defs: Dict[Any, dict] = _norm_keys(profile.get("equipment_constants", {}) or {})
        self.alarm_defs: Dict[Any, dict] = _norm_keys(profile.get("alarms", {}) or {})
        self.ceid_defs: Dict[Any, dict] = _norm_keys(profile.get("collection_events", {}) or {})
        self.report_defs: Dict[Any, list] = {
            k: (v.get("variables") if isinstance(v, dict) else v)
            for k, v in _norm_keys(profile.get("reports", {}) or {}).items()}
        self.rcmd_defs: Dict[str, dict] = profile.get("remote_commands", {}) or {}
        self.behavior: dict = profile.get("behavior", {}) or {}

        # runtime state
        self.sv_values: Dict[Any, Any] = {}
        self.dv_values: Dict[Any, Any] = {}
        self.ec_values: Dict[Any, Any] = {}
        for k, d in self.ec_defs.items():
            self.ec_values[k] = d.get("default")
        for k, d in self.dv_defs.items():
            self.dv_values[k] = d.get("initial")
        for k, d in self.sv_defs.items():
            self.sv_values[k] = d.get("initial", d.get("default"))
        self.clock = datetime.now()
        self.alarms_set: Dict[Any, bool] = {k: False for k in self.alarm_defs}
        self.alarms_enabled: Dict[Any, bool] = {k: True for k in self.alarm_defs}
        self.events_enabled: Dict[Any, bool] = {k: False for k in self.ceid_defs}
        self.registered_reports: Dict[Any, List[Any]] = {}   # RPTID -> [SVID]
        self.ceid_links: Dict[Any, Dict[Any, List[Any]]] = {}  # CEID -> {RPTID: [SVID]}
        self.pps: Dict[str, bytes] = {}
        self.hsms_state: str = HsmsState.NOT_CONNECTED.value
        self.communication_state = CommunicationState.NOT_COMMUNICATING
        self.control_state = conn.get("initial_control_state", "ONLINE_REMOTE" if role == "equipment" else "ONLINE")
        self.established = False
        self._handlers: Dict[str, Any] = {}
        self._register_handlers()
        self.recorder = None  # set by recorder module
        self._last_selected_since: Optional[float] = None

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self.protocol.start()

    async def stop(self) -> None:
        await self.protocol.stop()

    @property
    def connected(self) -> bool:
        return self.protocol.state == HsmsState.SELECTED

    def states(self) -> dict:
        return {
            "hsms": self.protocol.state.value,
            "communication": self.communication_state,
            "control": self.control_state,
        }

    # ------------------------------------------------------------- events
    def _on_frame(self, direction: str, frame: bytes, msg: HsmsMessage) -> None:
        """Raw frame logging: decode to SML for data messages."""
        entry = {
            "ts": time.time(),
            "dir": direction,          # 'in' | 'out'
            "role": self.role,
            "session": self.session_id,
        }
        if msg.is_data:
            try:
                item = Item.decode(msg.body, 0) if msg.body else Item.L([])
            except Exception:
                item = None
            entry.update({
                "sf": msg.sf, "w": msg.wbit, "system_bytes": msg.system_bytes,
                "sml": item.to_sml() if item is not None else None,
                "hex": frame.hex(),
                "kind": "data",
            })
        else:
            entry.update({"kind": "control", "desc": msg.describe(),
                          "hex": frame.hex(), "sf": None})
        if self.recorder is not None:
            try:
                self.recorder.record(entry)
            except Exception:
                log.exception("recorder error")
        asyncio.get_running_loop().create_task(self.emit("log", entry))

    async def _on_hsms_event(self, event: str, payload: Any) -> None:
        if event == "state_changed":
            self.hsms_state = payload.get("state", self.hsms_state)
            await self.emit("state", {"states": self.states()})
            if payload.get("state") == HsmsState.SELECTED.value:
                self._last_selected_since = time.time()
        elif event == "connected":
            if self.role == "equipment" and self.communication_state == CommunicationState.NOT_COMMUNICATING:
                self.communication_state = CommunicationState.WAIT_CRA
                await self.emit("state", {"states": self.states()})
        elif event in ("disconnected", "t7_timeout", "t8_timeout", "read_error",
                       "select_rejected", "separate", "rejected", "deselected"):
            if self.connected is False and self.communication_state == CommunicationState.COMMUNICATING:
                self.communication_state = CommunicationState.NOT_COMMUNICATING
                self.established = False
                await self.emit("state", {"states": self.states()})
            await self.emit("hsms_" + event, payload)
            if event in ("t7_timeout", "t8_timeout"):
                await self.emit("error", {"message": f"{event.upper()} occurred", "detail": payload})
        elif event == "t3_timeout":
            pass  # raised as exception to caller
        # auto establish communications for host role
        if event == "selected" and self.role == "host":
            if self.behavior.get("auto_establish", True):
                asyncio.get_running_loop().create_task(self._host_auto_establish())

    async def _host_auto_establish(self) -> None:
        try:
            await asyncio.sleep(0.1)
            await self.host_establish_communication()
        except (T3Timeout, ConnectionLost, HsmsError):
            pass

    # ------------------------------------------------------------- dispatch
    def _register_handlers(self) -> None:
        eq = {
            "S1F1": self._h_s1f1, "S1F3": self._h_s1f3, "S1F11": self._h_s1f11,
            "S1F13": self._h_s1f13, "S1F15": self._h_s1f15, "S1F17": self._h_s1f17,
            "S2F13": self._h_s2f13, "S2F15": self._h_s2f15, "S2F17": self._h_s2f17,
            "S2F29": self._h_s2f29, "S2F31": self._h_s2f31, "S2F33": self._h_s2f33,
            "S2F35": self._h_s2f35, "S2F37": self._h_s2f37, "S2F41": self._h_s2f41,
            "S5F3": self._h_s5f3, "S5F5": self._h_s5f5, "S5F7": self._h_s5f7,
            "S6F15": self._h_s6f15, "S6F19": self._h_s6f19,
            "S7F1": self._h_s7f1, "S7F3": self._h_s7f3, "S7F5": self._h_s7f5,
            "S7F17": self._h_s7f17, "S7F19": self._h_s7f19,
            "S10F3": self._h_s10f3, "S10F5": self._h_s10f5,
        }
        host = {
            "S1F13": self._h_s1f13_from_equipment,
            "S1F2": self._h_s1f2,  # host receiving online data unsolicited (no W usually)
            "S5F1": self._h_s5f1,
            "S6F11": self._h_s6f11,
            "S10F1": self._h_s10f1,
            "S7F6": self._h_s7f6_host,
        }
        self._handlers = eq if self.role == "equipment" else host

    async def _on_data(self, msg: HsmsMessage) -> None:
        sf = msg.sf
        handler = self._handlers.get(sf)
        if handler is None:
            # unknown function
            if msg.wbit:
                await self._send_s9f5(msg)
            await self.emit("unhandled", {"sf": sf})
            return
        try:
            body = Item.decode(msg.body, 0) if msg.body else None
        except Exception:
            if msg.wbit:
                await self._send_s9f7(msg)
            await self.emit("error", {"message": f"malformed body for {sf}"})
            return
        try:
            await handler(msg, body)
        except Exception as exc:
            log.exception("handler error %s", sf)
            await self.emit("error", {"message": f"handler error for {sf}: {exc}"})
            if msg.wbit:
                await self.protocol.reply_data(msg, msg.stream, 0, None)

    async def _send_s9f5(self, primary: HsmsMessage) -> None:
        head = _encode_header_bytes(primary)
        body = Item.L([Item.from_value("B", list(head)), Item.from_value("A", "")])
        await self.protocol.reply_data(primary, 9, 5, body)

    async def _send_s9f7(self, primary: HsmsMessage) -> None:
        head = _encode_header_bytes(primary)
        body = Item.L([Item.from_value("B", list(head)), Item.from_value("A", "")])
        await self.protocol.reply_data(primary, 9, 7, body)

    @staticmethod
    def _decode_rsp(rsp: Optional[HsmsMessage]) -> Optional[Item]:
        """Decode reply message body into Item (HsmsMessage.body is raw bytes)."""
        if rsp is None or not rsp.body:
            return None
        try:
            return Item.decode(rsp.body, 0)
        except Exception:
            return None

    # ------------------------------------------------------------- equipment handlers
    async def _h_s1f1(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        await self.protocol.reply_data(
            msg, 1, 2, Item.L([Item.from_value("A", self.mdln),
                               Item.from_value("A", self.softrev)]))

    async def _h_s1f2(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        await self.emit("online_data", {"mdln": _item_str(body, 0),
                                        "softrev": _item_str(body, 1)})

    async def _h_s1f3(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        svids = _id_list(body)
        if not svids:
            svids = list(self.sv_defs.keys())
        vals = [self._encode_var(self._defs_for(s), self._values_for(s), s)
                for s in svids]
        await self.protocol.reply_data(msg, 1, 4, Item.L(vals))

    async def _h_s1f11(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        svids = _id_list(body)
        if not svids:
            svids = list(self.sv_defs.keys())
        out = []
        for svid in svids:
            d = self._defs_for(svid).get(svid, {})
            out.append(Item.L([Item.from_value("U4", _as_int_id(svid)),
                               Item.from_value("A", str(d.get("name", str(svid)))),
                               Item.from_value("A", str(d.get("unit", "")))]))
        await self.protocol.reply_data(msg, 1, 12, Item.L(out))

    async def _h_s1f13(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        # equipment receiving CR from host
        auto = self.behavior.get("auto_reply_s1f13", True)
        commack = 0 if auto else 1
        if commack == 0:
            self.communication_state = CommunicationState.COMMUNICATING
            self.established = True
        reply = Item.L([Item.from_value("B", commack),
                        Item.L([Item.from_value("A", self.mdln),
                                Item.from_value("A", self.softrev)])])
        await self.protocol.reply_data(msg, 1, 14, reply)
        await self.emit("state", {"states": self.states()})
        await self.emit("established", {"ok": commack == 0})

    async def _h_s1f13_from_equipment(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        # host receiving CR from equipment
        commack = 0
        reply = Item.L([Item.from_value("B", commack),
                        Item.L([Item.from_value("A", self.mdln),
                                Item.from_value("A", self.softrev)])])
        await self.protocol.reply_data(msg, 1, 14, reply)
        self.established = True
        self.communication_state = CommunicationState.COMMUNICATING
        await self.emit("state", {"states": self.states()})
        await self.emit("established", {"ok": True})

    async def _h_s1f15(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        if self.control_state.startswith("ONLINE"):
            self.control_state = "HOST_OFFLINE"
            onlack = 0
        else:
            onlack = 2  # already offline
        await self.protocol.reply_data(msg, 1, 16, Item.from_value("B", onlack))
        await self.emit("state", {"states": self.states()})

    async def _h_s1f17(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        target = self.behavior.get("online_mode", "ONLINE_REMOTE")
        if self.control_state in ("EQUIPMENT_OFFLINE", "ATTEMPT_ONLINE", "HOST_OFFLINE"):
            self.control_state = target if target.startswith("ONLINE") else "ONLINE_REMOTE"
            onlack = 0
        else:
            onlack = 2
        await self.protocol.reply_data(msg, 1, 18, Item.from_value("B", onlack))
        await self.emit("state", {"states": self.states()})

    async def _h_s2f13(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        ecids = _id_list(body)
        if not ecids:
            ecids = list(self.ec_defs.keys())
        vals = [self._encode_var(self.ec_defs, self.ec_values, ecid) for ecid in ecids]
        await self.protocol.reply_data(msg, 2, 14, Item.L(vals))

    async def _h_s2f15(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        eacs = []
        if body is not None:
            for pair in body.value:
                ecid = _first_int(pair[0])
                val = _item_to_py(pair[1])
                d = self.ec_defs.get(ecid)
                if d is None:
                    eacs.append(1)  # no such EC
                    continue
                ok = _check_range(d, val)
                if ok:
                    self.ec_values[ecid] = val
                eacs.append(0 if ok else 3)  # 3 = invalid value
        await self.emit("ec_updated", {"values": dict(self.ec_values)})
        # SEMI E30: S2F16 = L[n] {<EAC B>} per EC entry
        await self.protocol.reply_data(
            msg, 2, 16, Item.L([Item.from_value("B", e) for e in eacs]))

    async def _h_s2f17(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        await self.protocol.reply_data(
            msg, 2, 18, Item.from_value("A", self.clock.strftime("%y%m%d%H%M%S")))

    async def _h_s2f29(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        ecids = _id_list(body)
        if not ecids:
            ecids = list(self.ec_defs.keys())
        out = [Item.L([Item.from_value("U4", _as_int_id(ecid)),
                       Item.from_value("A", str(self.ec_defs.get(ecid, {}).get("name", str(ecid))))])
               for ecid in ecids]
        await self.protocol.reply_data(msg, 2, 30, Item.L(out))

    async def _h_s2f31(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        ackc2 = 1
        if body is not None and body.kind == "A":
            text = body.first()
            for fmt in ("%y%m%d%H%M%S", "%Y%m%d%H%M%S%f", "%Y%m%d%H%M%S"):
                try:
                    self.clock = datetime.strptime(str(text), fmt)
                    ackc2 = 0
                    break
                except ValueError:
                    continue
        await self.protocol.reply_data(msg, 2, 32, Item.from_value("B", ackc2))
        await self.emit("clock_set", {"clock": self.clock.isoformat()})

    async def _h_s2f33(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        dataid = 0
        if body is not None and len(body.value) >= 2:
            dataid = _first_int(body[0])
            for entry in body[1].value:
                rptid = _first_int(entry[0])
                svids = [_first_int(v) for v in entry[1].value]
                self.registered_reports[rptid] = svids
        lrack = 0
        await self.protocol.reply_data(
            msg, 2, 34, Item.L([Item.from_value("U4", dataid), Item.from_value("B", lrack)]))
        await self.emit("reports_defined", {"reports": {str(k): v for k, v in self.registered_reports.items()}})

    async def _h_s2f35(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        dataid = 0
        if body is not None and len(body.value) >= 2:
            dataid = _first_int(body[0])
            for entry in body[1].value:
                ceid = _first_int(entry[0])
                links = {}
                for rpt in entry[1].value:
                    rptid = _first_int(rpt[0])
                    svids = [_first_int(v) for v in rpt[1].value] if len(rpt.value) > 1 else None
                    if svids:
                        links[rptid] = svids
                    else:
                        links[rptid] = self.registered_reports.get(rptid, [])
                self.ceid_links[ceid] = links
        await self.protocol.reply_data(
            msg, 2, 36, Item.L([Item.from_value("U4", dataid), Item.from_value("B", 0)]))
        await self.emit("events_linked", {"links": {str(k): {str(r): v for r, v in links.items()}
                                                    for k, links in self.ceid_links.items()}})

    async def _h_s2f37(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        drack = 0
        if body is not None and len(body.value) >= 3:
            ceed = bool(body[1].first())
            for ceid_item in body[2].value:
                ceid = _first_int(ceid_item)
                self.events_enabled[ceid] = ceed
        await self.protocol.reply_data(
            msg, 2, 38, Item.L([Item.from_value("U4", _first_int(body[0]) if body else 0),
                                Item.from_value("B", drack)]))
        await self.emit("events_enabled_change", {"enabled": {str(k): v for k, v in self.events_enabled.items()}})

    async def _h_s2f41(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        rcmd = str(body[0].first()) if body is not None and len(body.value) else ""
        params: Dict[str, Any] = {}
        param_items: List[Tuple[str, Any]] = []
        if body is not None and len(body.value) >= 2:
            for pair in body[1].value:
                name = str(pair[0].first())
                val = _item_to_py(pair[1])
                params[name] = val
                param_items.append((name, val))
        hcack, ackc_list = await self._execute_remote_command(rcmd, params, param_items)
        reply = Item.L([Item.from_value("B", hcack),
                        Item.L([Item.L([Item.from_value("A", n), Item.from_value("B", a)])
                                for n, a in ackc_list])])
        await self.protocol.reply_data(msg, 2, 42, reply)
        await self.emit("remote_command", {"rcmd": rcmd, "params": params, "hcack": hcack})

    async def _h_s5f3(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        ackc5 = 1
        if body is not None and len(body.value) >= 2:
            alcd = int(body[0].first())
            alid = _first_int(body[1])
            enable = bool(alcd & ALCD_SET)
            self.alarms_enabled[alid] = enable
            ackc5 = 0
        await self.protocol.reply_data(msg, 5, 4, Item.from_value("B", ackc5))
        await self.emit("alarm_enabled_change", {"enabled": {str(k): v for k, v in self.alarms_enabled.items()}})

    def _alarm_entry(self, alid: Any) -> Optional[Item]:
        d = self.alarm_defs.get(alid)
        if d is None:
            return None
        alcd = ALCD_SET if self.alarms_set.get(alid) else 0
        alcd |= int(d.get("category", 0)) & 0x7F
        return Item.L([Item.from_value("B", alcd), Item.from_value("U4", _as_int_id(alid)),
                       Item.from_value("A", str(d.get("text", "")))])

    async def _h_s5f5(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        alids = _id_list(body) or [k for k, v in self.alarms_set.items() if v]
        out = [self._alarm_entry(a) for a in alids if self.alarms_set.get(a)]
        await self.protocol.reply_data(msg, 5, 6, Item.L([o for o in out if o]))

    async def _h_s5f7(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        alids = _id_list(body) or list(self.alarm_defs.keys())
        out = [self._alarm_entry(a) for a in alids
               if self.alarms_enabled.get(a) and self._alarm_entry(a)]
        await self.protocol.reply_data(msg, 5, 8, Item.L(out))

    async def _h_s6f15(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        dataid = _first_int(body[0]) if body else 0
        ceid = _first_int(body[1]) if body else 0
        report_body = self._build_event_body(dataid, ceid)
        await self.protocol.reply_data(msg, 6, 16, report_body)

    async def _h_s6f19(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        dataid = _first_int(body[0]) if body else 0
        rptid = _first_int(body[1]) if body else 0
        svids = self.registered_reports.get(rptid, [])
        values = Item.L([self._encode_var(self._defs_for(svid), self._values_for(svid), svid)
                         for svid in svids])
        await self.protocol.reply_data(
            msg, 6, 20, Item.L([Item.from_value("U4", dataid), values]))

    async def _h_s7f1(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        ppid = str(body[0].first()) if body else ""
        pgrpn = 0 if ppid in self.pps else 1
        await self.protocol.reply_data(msg, 7, 2, Item.from_value("B", pgrpn))

    async def _h_s7f3(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        ackc7 = 0
        if body is not None and len(body.value) >= 2:
            ppid = str(body[0].first())
            ppbody = bytes(body[1].value) if body[1].kind == "B" else b""
            self.pps[ppid] = ppbody
        else:
            ackc7 = 3  # malformed
        await self.protocol.reply_data(msg, 7, 4, Item.from_value("B", ackc7))
        await self.emit("pp_uploaded", {"ppid": ppid, "size": len(ppbody)})

    async def _h_s7f5(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        ppid = str(body[0].first()) if body else ""
        ppbody = self.pps.get(ppid, b"")
        await self.protocol.reply_data(
            msg, 7, 6, Item.L([Item.from_value("A", ppid), Item.from_value("B", list(ppbody))]))

    async def _h_s7f17(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        if body is not None:
            for p in body.value:
                self.pps.pop(str(p.first()), None)
        await self.protocol.reply_data(msg, 7, 18, Item.from_value("B", 0))
        await self.emit("pp_deleted", {})

    async def _h_s7f19(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        await self.protocol.reply_data(
            msg, 7, 20, Item.L([Item.from_value("A", p) for p in self.pps.keys()]))

    async def _h_s10f3(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        tid = 0
        text = ""
        if body is not None and len(body.value) >= 2:
            tid = int(body[0].first())
            text = str(body[1].first())
        await self.protocol.reply_data(
            msg, 10, 4, Item.L([Item.from_value("B", 0), Item.from_value("B", tid)]))
        await self.emit("terminal_display", {"tid": tid, "text": text})

    async def _h_s10f5(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        texts = []
        if body is not None:
            for t in body.value:
                texts.append(str(t[1].first()) if len(t.value) >= 2 else "")
        await self.protocol.reply_data(msg, 10, 6, Item.from_value("B", [0] * max(len(texts), 1)))
        await self.emit("terminal_display", {"text": "\n".join(texts)})

    # ------------------------------------------------------------- host-side handlers
    async def _h_s5f1(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        await self.protocol.reply_data(msg, 5, 2, Item.from_value("B", 0))
        alcd = int(body[0].first()) if body else 0
        alid = _first_int(body[1]) if body else 0
        altx = str(body[2].first()) if body else ""
        await self.emit("alarm", {"alid": alid, "set": bool(alcd & ALCD_SET),
                                  "alcd": alcd, "text": altx})

    async def _h_s6f11(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        dataid = _first_int(body[0]) if body else 0
        ceid = _first_int(body[1]) if body else 0
        reports = {}
        if body is not None and len(body.value) >= 3:
            for rpt in body[2].value:
                rptid = _first_int(rpt[0])
                svids = self.registered_reports.get(rptid, [])
                vals = [_item_to_py(v) for v in rpt[1].value]
                if svids and len(svids) == len(vals):
                    reports[str(rptid)] = {str(s): v for s, v in zip(svids, vals)}
                else:
                    reports[str(rptid)] = vals
        await self.protocol.reply_data(
            msg, 6, 12, Item.L([Item.from_value("B", 0), Item.from_value("U4", dataid)]))
        await self.emit("collection_event", {"ceid": ceid, "reports": reports})

    async def _h_s10f1(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        await self.protocol.reply_data(
            msg, 10, 2, Item.L([Item.from_value("B", 0), Item.from_value("B", 0)]))
        text = str(body[1].first()) if body and len(body.value) >= 2 else ""
        await self.emit("terminal", {"text": text})

    async def _h_s7f6_host(self, msg: HsmsMessage, body: Optional[Item]) -> None:
        ppid = str(body[0].first()) if body else ""
        ppbody = bytes(body[1].value) if body and len(body.value) >= 2 else b""
        await self.emit("pp_downloaded", {"ppid": ppid, "body": ppbody.decode("latin-1", "replace")})

    # ------------------------------------------------------------- GEM helpers
    def _defs_for(self, svid: Any) -> dict:
        if svid in self.sv_defs:
            return self.sv_defs
        if svid in self.dv_defs:
            return self.dv_defs
        return self.ec_defs

    def _values_for(self, svid: Any) -> dict:
        if svid in self.sv_defs:
            return self.sv_values
        if svid in self.dv_defs:
            return self.dv_values
        return self.ec_values

    def _encode_var(self, defs: dict, values: dict, vid: Any) -> Item:
        d = defs.get(vid, {})
        vtype = str(d.get("type", "A")).upper()
        value = values.get(vid)
        if value is None:
            value = d.get("default", d.get("initial", ""))
        if d.get("enum") and str(value) in d["enum"]:
            pass  # keep string
        return Item.from_value(vtype, value)

    def _build_event_body(self, dataid: int, ceid: Any) -> Item:
        links = self.ceid_links.get(ceid, {})
        # fall back: profile-defined reports for this ceid
        if not links:
            rptids = self.ceid_defs.get(ceid, {}).get("reports", [])
            links = {r: self.report_defs.get(r, []) or self.registered_reports.get(r, [])
                     for r in rptids}
        rpt_items = []
        for rptid, svids in links.items():
            vals = [self._encode_var(self._defs_for(s), self._values_for(s), s)
                    for s in svids]
            rpt_items.append(Item.L([Item.from_value("U4", _as_int_id(rptid)), Item.L(vals)]))
        return Item.L([Item.from_value("U4", dataid),
                       Item.from_value("U4", _as_int_id(ceid)), Item.L(rpt_items)])

    async def trigger_collection_event(self, ceid: Any, dataid: int = 0) -> bool:
        """Equipment: send S6F11 for ceid if enabled/defined. Returns sent flag."""
        if not self.connected:
            return False
        if not self.events_enabled.get(ceid, False):
            return False
        body = self._build_event_body(dataid, ceid)
        await self.protocol.send_data(6, 11, body, wbit=True)
        await self.emit("event_sent", {"ceid": ceid})
        return True

    async def set_alarm(self, alid: Any, on: bool, text: Optional[str] = None) -> bool:
        """Equipment: raise/clear alarm, send S5F1(W) and auto-trigger linked events."""
        if alid not in self.alarm_defs:
            return False
        self.alarms_set[alid] = on
        d = self.alarm_defs[alid]
        alcd = (ALCD_SET if on else 0) | (int(d.get("category", 0)) & 0x7F)
        body = Item.L([Item.from_value("B", alcd), Item.from_value("U4", _as_int_id(alid)),
                       Item.from_value("A", text or str(d.get("text", "")))])
        if self.connected:
            await self.protocol.send_data(5, 1, body, wbit=True)
        await self.emit("alarm", {"alid": alid, "set": on, "alcd": alcd,
                                  "text": text or d.get("text", "")})
        ceid = d.get("ceid_on") if on else d.get("ceid_off")
        if ceid is not None:
            await self.trigger_collection_event(ceid)
        return True

    async def _execute_remote_command(self, rcmd: str, params: Dict[str, Any],
                                      param_items: List[Tuple[str, Any]]
                                      ) -> Tuple[int, List[Tuple[str, int]]]:
        behavior = (self.behavior.get("on_remote_command") or {}).get(rcmd)
        d = self.rcmd_defs.get(rcmd)
        if d is None and behavior is None:
            return HCACK_INVALID_COMMAND, [(n, HCACK_INVALID_COMMAND) for n, _ in param_items]
        # validate params
        for name, val in params.items():
            pd = (d or {}).get("params", {}).get(name)
            if pd is None and d is not None:
                return HCACK_NO_SUCH_PARAMETER, [(name, HCACK_NO_SUCH_PARAMETER)]
            if pd and pd.get("required") and (val is None or val == ""):
                return HCACK_INVALID_PARAMETER, [(name, HCACK_INVALID_PARAMETER)]
        ackc_list = [(n, 0) for n, _ in param_items]
        if behavior:
            for vid, val in (behavior.get("set") or {}).items():
                # "@PARAM" syntax: take value from the remote command parameters
                if isinstance(val, str) and val.startswith("@"):
                    val = params.get(val[1:])
                if vid in self.dv_defs:
                    self.dv_values[vid] = val
                elif vid in self.sv_defs:
                    self.sv_values[vid] = val
                elif vid in self.ec_defs:
                    self.ec_values[vid] = val
            for alid in behavior.get("alarm_on") or []:
                await self.set_alarm(alid, True)
            for alid in behavior.get("alarm_off") or []:
                await self.set_alarm(alid, False)
            ceid = behavior.get("trigger_ceid")
            if ceid is not None:
                await self.trigger_collection_event(ceid)
            hcack = int(behavior.get("hcack", HCACK_OK))
        else:
            hcack = HCACK_OK
        return hcack, ackc_list

    async def switch_control_state(self, target: str) -> bool:
        if target not in CONTROL_STATES:
            return False
        self.control_state = target
        await self.emit("state", {"states": self.states()})
        return True

    # ------------------------------------------------------------- host helpers
    async def host_establish_communication(self) -> bool:
        body = Item.L([Item.from_value("A", self.mdln), Item.from_value("A", self.softrev)])
        rsp = await self.protocol.send_data(1, 13, body, wbit=True)
        rb = self._decode_rsp(rsp)
        ok = bool(rb and rsp.function == 14 and rb[0].first() == 0)
        self.established = bool(ok)
        if ok:
            self.communication_state = CommunicationState.COMMUNICATING
            await self.emit("state", {"states": self.states()})
            await self.emit("established", {"ok": True})
        return ok

    async def host_define_report(self, rptid: Any, svids: List[Any], dataid: int = 0) -> None:
        self.registered_reports[rptid] = list(svids)
        body = Item.L([
            Item.from_value("U4", dataid),
            Item.L([Item.L([Item.from_value("U4", _as_int_id(rptid)),
                            Item.L([Item.from_value("U4", _as_int_id(s)) for s in svids])])])])
        await self.protocol.send_data(2, 33, body, wbit=True)

    async def host_link_event(self, ceid: Any, rptid: Any, dataid: int = 0) -> None:
        svids = self.registered_reports.get(rptid, [])
        self.ceid_links.setdefault(ceid, {})[rptid] = svids
        body = Item.L([
            Item.from_value("U4", dataid),
            Item.L([Item.L([Item.from_value("U4", _as_int_id(ceid)),
                            Item.L([Item.L([Item.from_value("U4", _as_int_id(rptid)),
                                            Item.L([])])])])])])
        await self.protocol.send_data(2, 35, body, wbit=True)

    async def host_enable_events(self, ceids: List[Any], on: bool = True, dataid: int = 0) -> None:
        for c in ceids:
            self.events_enabled[c] = on
        body = Item.L([Item.from_value("U4", dataid),
                       Item.from_value("BOOLEAN", on),
                       Item.L([Item.from_value("U4", _as_int_id(c)) for c in ceids])])
        await self.protocol.send_data(2, 37, body, wbit=True)

    async def host_subscribe(self, ceid: Any, rptid: Any, svids: List[Any]) -> None:
        await self.host_define_report(rptid, svids)
        await self.host_link_event(ceid, rptid)
        await self.host_enable_events([ceid], True)

    async def host_send_remote_command(self, rcmd: str, params: Dict[str, Any]) -> dict:
        pairs = [Item.L([Item.from_value("A", name), Item.from_value(
            str((self.rcmd_defs.get(rcmd, {}).get("params", {}) or {}).get(name, {}).get("type", "A")),
            val)]) for name, val in params.items()]
        body = Item.L([Item.from_value("A", rcmd), Item.L(pairs)])
        rsp = await self.protocol.send_data(2, 41, body, wbit=True)
        hcack = None
        rb = self._decode_rsp(rsp)
        if rb is not None and rsp.function == 42:
            hcack = int(rb[0].first())
        return {"hcack": hcack, "rcmd": rcmd, "params": params}

    async def host_query_sv(self, svids: List[Any]) -> dict:
        body = Item.L([Item.from_value("U4", _as_int_id(s)) for s in svids])
        rsp = await self.protocol.send_data(1, 3, body, wbit=True)
        out = {}
        rb = self._decode_rsp(rsp)
        if rb is not None and rsp.function == 4:
            for s, v in zip(svids, rb.value):
                out[str(s)] = _item_to_py(v)
        return out

    async def host_set_ec(self, ecid: Any, value: Any) -> dict:
        d = self.ec_defs.get(ecid, {})
        body = Item.L([Item.L([Item.from_value("U4", _as_int_id(ecid)),
                               Item.from_value(str(d.get("type", "A")), value)])])
        rsp = await self.protocol.send_data(2, 15, body, wbit=True)
        rb = self._decode_rsp(rsp)
        return {"eac": int(rb[0].first()) if rb is not None else None}

    async def host_pp_upload(self, ppid: str, ppbody: bytes) -> dict:
        body = Item.L([Item.from_value("A", ppid), Item.from_value("B", list(ppbody))])
        rsp = await self.protocol.send_data(7, 3, body, wbit=True)
        rb = self._decode_rsp(rsp)
        return {"ackc7": int(rb.first()) if rb is not None else None}

    async def host_pp_download(self, ppid: str) -> Optional[bytes]:
        body = Item.L([Item.from_value("A", ppid)])
        rsp = await self.protocol.send_data(7, 5, body, wbit=True)
        rb = self._decode_rsp(rsp)
        if rb is not None and rsp.function == 6 and len(rb.value) >= 2:
            return bytes(rb[1].value)
        return None

    async def host_terminal(self, text: str, tid: int = 0) -> Optional[int]:
        body = Item.L([Item.from_value("B", tid), Item.from_value("A", text)])
        rsp = await self.protocol.send_data(10, 3, body, wbit=True)
        rb = self._decode_rsp(rsp)
        if rb is not None:
            return int(rb[0].first())
        return None

    async def host_go_online_request(self) -> Optional[int]:
        rb = self._decode_rsp(await self.protocol.send_data(1, 17, None, wbit=True))
        return int(rb.first()) if rb is not None else None

    async def host_go_offline_request(self) -> Optional[int]:
        rb = self._decode_rsp(await self.protocol.send_data(1, 15, None, wbit=True))
        return int(rb.first()) if rb is not None else None

    # ------------------------------------------------------------- generic send API
    async def send_sml(self, text: str, wait_reply: Optional[bool] = None) -> dict:
        msg = smlmod.parse(text)
        wbit = msg.w_bit if wait_reply is None else wait_reply
        rsp = await self.protocol.send_data(msg.stream, msg.function, msg.body, wbit=wbit)
        out = {"sf": msg.sf, "sent": True}
        if rsp is not None:
            try:
                item = Item.decode(rsp.body, 0) if rsp.body else Item.L([])
                out["reply"] = {"sf": rsp.sf, "sml": item.to_sml(),
                                "system_bytes": rsp.system_bytes}
            except Exception:
                out["reply"] = {"sf": rsp.sf, "hex": rsp.body.hex()}
        return out

    async def send(self, stream: int, function: int, body: Optional[Item] = None,
                   wbit: bool = False, system_bytes: Optional[int] = None) -> Optional[HsmsMessage]:
        return await self.protocol.send_data(stream, function, body, wbit=wbit,
                                             system_bytes=system_bytes)

    async def reply(self, primary: HsmsMessage, stream: int, function: int,
                    body: Optional[Item] = None) -> None:
        await self.protocol.reply_data(primary, stream, function, body)


def _norm_keys(d: dict) -> dict:
    """Normalize GEM object ids: numeric-string keys -> int (SECS ids are numeric)."""
    out = {}
    for k, v in d.items():
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            out[k] = v
    return out


def _encode_header_bytes(msg: HsmsMessage) -> bytes:
    if msg.is_data:
        b2 = (0x80 if msg.wbit else 0) | msg.stream
        return msg.session_id.to_bytes(2, "big") + bytes([b2, msg.function, 0, 0]) \
            + msg.system_bytes.to_bytes(4, "big")
    return msg.session_id.to_bytes(2, "big") + bytes([msg.header2, msg.header3, 0, msg.stype]) \
        + msg.system_bytes.to_bytes(4, "big")


def _id_list(body: Optional[Item]) -> List[Any]:
    if body is None or body.kind != "L":
        return []
    return [_first_int(x) for x in body.value]


def _first_int(item: Any) -> Any:
    """Extract numeric id (SVID/CEID/RPTID/ALID...). Returns int when possible."""
    if isinstance(item, Item):
        v = item.first()
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return v
        return v
    return item


def _as_int_id(x: Any) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _item_to_py(item: Optional[Item]) -> Any:
    if item is None:
        return None
    if item.kind == "L":
        return [_item_to_py(c) for c in item.value]
    v = item.first()
    if item.kind == "B" and isinstance(v, bytes):
        return v.hex()
    return v


def _item_str(item: Optional[Item], idx: int) -> str:
    if item is None or len(item.value) <= idx:
        return ""
    return str(item.value[idx].first())


def _check_range(d: dict, val: Any) -> bool:
    try:
        if d.get("min") is not None and val < d["min"]:
            return False
        if d.get("max") is not None and val > d["max"]:
            return False
    except TypeError:
        return True
    return True
