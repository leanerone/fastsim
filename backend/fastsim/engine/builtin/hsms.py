"""HSMS-SS (SEMI E37) transport over asyncio.

Single-session model: one TCP connection, Select/Deselect/Linktest/Separate
control messages, T3/T5/T6/T7/T8 timers, W-bit transactions matched by
system bytes. Active (client) and Passive (server) modes.
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import random
import struct
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

from .secs2 import Item, SecsError

log = logging.getLogger("fastsim.hsms")

# HSMS select status codes
SELECT_OK = 0x00
SELECT_NOT_READY = 0x01
SELECT_ALREADY_ACTIVE = 0x02
SELECT_REJECT_NOT_SELECTED = 0x03

# reject reasons (Reject.req header byte 2)
REJECT_NOT_SELECTED = 0x03

STYPE_DATA = 0x00
STYPE_SELECT_REQ = 0x01
STYPE_SELECT_RSP = 0x02
STYPE_DESELECT_REQ = 0x03
STYPE_DESELECT_RSP = 0x04
STYPE_LINKTEST_REQ = 0x05
STYPE_LINKTEST_RSP = 0x06
STYPE_REJECT_REQ = 0x07
STYPE_SEPARATE_REQ = 0x09


class HsmsState(str, Enum):
    NOT_CONNECTED = "NOT_CONNECTED"
    CONNECTED_NOT_SELECTED = "CONNECTED_NOT_SELECTED"
    SELECTED = "SELECTED"


class HsmsError(SecsError):
    """HSMS transport error."""


class T3Timeout(HsmsError):
    pass


class T6Timeout(HsmsError):
    pass


class T7Timeout(HsmsError):
    pass


class ConnectionLost(HsmsError):
    pass


@dataclass
class HsmsConfig:
    mode: str = "PASSIVE"            # ACTIVE | PASSIVE
    host: str = "127.0.0.1"
    port: int = 5000
    device_id: int = 0
    t3: float = 45.0
    t5: float = 10.0
    t6: float = 5.0
    t7: float = 10.0
    t8: float = 5.0
    linktest_interval: float = 30.0
    max_reconnect: int = 0           # 0 = retry forever (active mode)
    name: str = "hsms"


@dataclass
class HsmsMessage:
    """Parsed HSMS message (data or control)."""
    session_id: int = 0
    stream: int = 0
    function: int = 0
    wbit: bool = False
    stype: int = STYPE_DATA
    header2: int = 0
    header3: int = 0
    system_bytes: int = 0
    body: bytes = b""

    @property
    def is_data(self) -> bool:
        return self.stype == STYPE_DATA

    @property
    def sf(self) -> str:
        return f"S{self.stream}F{self.function}"

    def to_bytes(self) -> bytes:
        if self.stype == STYPE_DATA:
            b2 = (0x80 if self.wbit else 0) | self.stream
            b3 = self.function
        else:
            b2 = self.header2
            b3 = self.header3
        head = struct.pack(
            ">HBBBBI",
            self.session_id, b2, b3, 0x00, self.stype, self.system_bytes,
        )
        return struct.pack(">I", len(head) + len(self.body)) + head + self.body

    @classmethod
    def parse(cls, frame: bytes) -> "HsmsMessage":
        if len(frame) < 14:
            raise HsmsError(f"frame too short ({len(frame)})")
        sid, b2, b3, ptype, stype, sysbytes = struct.unpack(">HBBBBI", frame[4:14])
        body = frame[14:]
        if stype == STYPE_DATA:
            return cls(session_id=sid, stream=b2 & 0x7F, function=b3,
                       wbit=bool(b2 & 0x80), stype=stype, system_bytes=sysbytes,
                       body=body)
        return cls(session_id=sid, header2=b2, header3=b3, stype=stype,
                   system_bytes=sysbytes, body=body)

    def describe(self) -> str:
        if self.is_data:
            w = " W" if self.wbit else ""
            return f"{self.sf}{w} sys={self.system_bytes:#x}"
        names = {STYPE_SELECT_REQ: "Select.req", STYPE_SELECT_RSP: "Select.rsp",
                 STYPE_DESELECT_REQ: "Deselect.req", STYPE_DESELECT_RSP: "Deselect.rsp",
                 STYPE_LINKTEST_REQ: "Linktest.req", STYPE_LINKTEST_RSP: "Linktest.rsp",
                 STYPE_REJECT_REQ: "Reject.req", STYPE_SEPARATE_REQ: "Separate.req"}
        return f"{names.get(self.stype, f'SType{self.stype}')} status={self.header2} sys={self.system_bytes:#x}"


DataCallback = Callable[[HsmsMessage], Awaitable[None]]
EventCallback = Callable[[str, Any], Awaitable[None]]


class HsmsProtocol:
    """One HSMS-SS connection (active or passive)."""

    def __init__(self, config: HsmsConfig):
        self.config = config
        self.state = HsmsState.NOT_CONNECTED
        self._server: Optional[asyncio.AbstractServer] = None
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._send_lock = asyncio.Lock()
        self._txns: "dict[int, asyncio.Future[HsmsMessage]]" = {}
        self._control_txns: "dict[int, asyncio.Future[HsmsMessage]]" = {}
        self._sysbytes = itertools.count(random.randint(1, 0xFFFFF))
        self._reader_task: Optional[asyncio.Task] = None
        self._run_task: Optional[asyncio.Task] = None
        self._linktest_task: Optional[asyncio.Task] = None
        self._t7_handle: Optional[asyncio.TimerHandle] = None
        self._running = False
        self._tasks: "set[asyncio.Task]" = set()
        self.on_data: Optional[DataCallback] = None
        self.on_event: Optional[EventCallback] = None    # (event, payload)
        self.on_frame: Optional[Callable[[str, bytes, HsmsMessage], None]] = None
        self._selected_event = asyncio.Event()

    # ---------------- lifecycle ----------------
    async def start(self) -> None:
        self._running = True
        self._run_task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        self._cancel_t7()
        if self._linktest_task:
            self._linktest_task.cancel()
            self._linktest_task = None
        await self._close_connection()
        if self._server:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                pass
            self._server = None
        for task in (self._run_task, self._reader_task):
            if task:
                task.cancel()
        self._fail_all_txns(ConnectionLost("session stopped"))
        self._set_state(HsmsState.NOT_CONNECTED)

    async def _run(self) -> None:
        if self.config.mode.upper() == "ACTIVE":
            await self._run_active()
        else:
            await self._run_passive()

    async def _run_active(self) -> None:
        attempts = 0
        while self._running:
            if self.config.max_reconnect and attempts >= self.config.max_reconnect:
                self._emit("connect_failed", {"reason": "max reconnect attempts reached"})
                break
            try:
                t0 = time.monotonic()
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.config.host, self.config.port),
                    timeout=max(self.config.t5, 1.0))
                self._emit("connected", {"peer": f"{self.config.host}:{self.config.port}"})
                await self._after_connected(is_active=True)
                attempts = 0
            except (OSError, asyncio.TimeoutError, ConnectionLost, HsmsError) as exc:
                self._emit("connect_retry", {"error": str(exc)})
                await self._close_connection()
                self._set_state(HsmsState.NOT_CONNECTED)
                elapsed = time.monotonic() - t0
                delay = max(self.config.t5 - elapsed, 0.5)
                await asyncio.sleep(delay)
                attempts += 1

    async def _run_passive(self) -> None:
        while self._running:
            if self._server is None:
                try:
                    self._server = await asyncio.start_server(
                        self._on_passive_client, self.config.host, self.config.port)
                    self._emit("listening", {"addr": f"{self.config.host}:{self.config.port}"})
                except OSError as exc:
                    self._emit("listen_failed", {"error": str(exc)})
                    await asyncio.sleep(self.config.t5)
                    continue
            await asyncio.sleep(0.2)

    async def _on_passive_client(
            self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.state == HsmsState.SELECTED or self._reader is not None:
            # single session: reject additional connections
            try:
                writer.close()
            except Exception:
                pass
            self._emit("connection_rejected", {"reason": "session busy"})
            return
        self._reader, self._writer = reader, writer
        peer = writer.get_extra_info("peername")
        self._emit("connected", {"peer": str(peer)})
        try:
            await self._after_connected(is_active=False)
        except (ConnectionLost, HsmsError, asyncio.IncompleteReadError, OSError):
            pass
        finally:
            await self._close_connection()
            self._set_state(HsmsState.CONNECTED_NOT_SELECTED if self._running
                            else HsmsState.NOT_CONNECTED)
            # passive listener keeps serving new connections via _run_passive

    async def _after_connected(self, is_active: bool) -> None:
        self._set_state(HsmsState.CONNECTED_NOT_SELECTED)
        self._reader_task = asyncio.create_task(self._read_loop())
        if is_active:
            await self.select()
        else:
            # T7: passive side must receive Select.req within T7
            loop = asyncio.get_running_loop()
            self._t7_handle = loop.call_later(
                self.config.t7, lambda: asyncio.create_task(self._t7_expired()))
        # wait until selected or connection lost
        try:
            await asyncio.wait_for(self._selected_event.wait(), timeout=None)
        except asyncio.TimeoutError:  # pragma: no cover
            pass
        self._cancel_t7()
        if self.state != HsmsState.SELECTED:
            raise ConnectionLost("not selected")
        # linktest loop while selected
        if self.config.linktest_interval > 0:
            self._linktest_task = asyncio.create_task(self._linktest_loop())
        # wait for reader loop to finish (connection closed)
        if self._reader_task:
            try:
                await self._reader_task
            except (HsmsError, OSError, asyncio.IncompleteReadError):
                pass
        raise ConnectionLost("connection closed")

    async def _t7_expired(self) -> None:
        if self.state != HsmsState.SELECTED:
            self._emit("t7_timeout", {})
            await self._close_connection()

    async def select(self) -> None:
        sysb = next(self._sysbytes)
        msg = HsmsMessage(session_id=0xFFFF, stype=STYPE_SELECT_REQ, system_bytes=sysb)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._control_txns[sysb] = fut
        await self._send_raw(msg)
        try:
            rsp = await asyncio.wait_for(fut, timeout=self.config.t6)
        except asyncio.TimeoutError:
            self._control_txns.pop(sysb, None)
            raise T6Timeout("T6 timeout waiting Select.rsp")
        status = rsp.header2
        if status != SELECT_OK:
            raise HsmsError(f"Select.rsp status={status:#x}")
        self._enter_selected()

    async def linktest(self) -> None:
        sysb = next(self._sysbytes)
        msg = HsmsMessage(session_id=0xFFFF, stype=STYPE_LINKTEST_REQ, system_bytes=sysb)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._control_txns[sysb] = fut
        await self._send_raw(msg)
        try:
            await asyncio.wait_for(fut, timeout=self.config.t6)
        except asyncio.TimeoutError:
            self._control_txns.pop(sysb, None)
            raise T6Timeout("T6 timeout waiting Linktest.rsp")

    async def _linktest_loop(self) -> None:
        try:
            while self._running and self.state == HsmsState.SELECTED:
                await asyncio.sleep(self.config.linktest_interval)
                if self.state == HsmsState.SELECTED:
                    await self.linktest()
        except asyncio.CancelledError:
            pass
        except (HsmsError, OSError):
            await self._close_connection()

    async def separate(self) -> None:
        msg = HsmsMessage(session_id=0xFFFF, stype=STYPE_SEPARATE_REQ,
                          system_bytes=next(self._sysbytes))
        await self._send_raw(msg)
        await self._close_connection()
        self._set_state(HsmsState.NOT_CONNECTED)

    async def deselect(self) -> None:
        sysb = next(self._sysbytes)
        msg = HsmsMessage(session_id=0xFFFF, stype=STYPE_DESELECT_REQ, system_bytes=sysb)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._control_txns[sysb] = fut
        await self._send_raw(msg)
        try:
            await asyncio.wait_for(fut, timeout=self.config.t6)
        except asyncio.TimeoutError:
            self._control_txns.pop(sysb, None)
            raise T6Timeout("T6 timeout waiting Deselect.rsp")

    # ---------------- data ----------------
    def new_system_bytes(self) -> int:
        return next(self._sysbytes)

    async def send_data(self, stream: int, function: int, body: Optional[Item] = None,
                        wbit: bool = False, system_bytes: Optional[int] = None,
                        wait_reply: bool = True) -> Optional[HsmsMessage]:
        """Send a data message. If wbit, wait for the reply (T3) and return it.

        Raises T3Timeout when no reply (per SEMI E30 a S9F9 is then sent to
        the peer carrying the original message header), ConnectionLost on link drop.
        """
        if self.state != HsmsState.SELECTED:
            raise ConnectionLost(f"cannot send in state {self.state.value}")
        sysb = system_bytes if system_bytes is not None else next(self._sysbytes)
        payload = body.encode() if isinstance(body, Item) else (body or b"")
        msg = HsmsMessage(session_id=self.config.device_id, stream=stream,
                          function=function, wbit=wbit, stype=STYPE_DATA,
                          system_bytes=sysb, body=payload)
        fut: Optional[asyncio.Future] = None
        if wbit:
            fut = asyncio.get_running_loop().create_future()
            self._txns[sysb] = fut
        await self._send_raw(msg)
        if not wbit or fut is None:
            return None
        try:
            return await asyncio.wait_for(fut, timeout=self.config.t3)
        except asyncio.TimeoutError:
            self._txns.pop(sysb, None)
            await self._send_s9f9(msg)
            raise T3Timeout(f"T3 timeout waiting reply for {msg.sf} sys={sysb:#x}")

    async def _send_s9f9(self, primary: HsmsMessage) -> None:
        """E30: notify peer of transaction timeout with original header."""
        try:
            b2 = (0x80 if primary.wbit else 0) | primary.stream
            head = primary.session_id.to_bytes(2, "big") + bytes(
                [b2, primary.function, 0, 0]) + primary.system_bytes.to_bytes(4, "big")
            body = Item.L([Item.from_value("B", list(head)), Item.from_value("A", "")])
            await self.send_data(9, 9, body, wbit=False)
        except Exception:
            pass  # best effort; link may be down already

    async def reply_data(self, primary: HsmsMessage, stream: int, function: int,
                         body: Optional[Item] = None) -> None:
        """Send a reply for a primary data message (echo system bytes)."""
        payload = body.encode() if isinstance(body, Item) else (body or b"")
        msg = HsmsMessage(session_id=primary.session_id, stream=stream,
                          function=function, wbit=False, stype=STYPE_DATA,
                          system_bytes=primary.system_bytes, body=payload)
        await self._send_raw(msg)

    async def send_abort(self, primary: HsmsMessage) -> None:
        """Abort a transaction: reply SxF0."""
        await self.reply_data(primary, primary.stream, 0, None)

    # ---------------- internals ----------------
    async def _send_raw(self, msg: HsmsMessage) -> None:
        if self._writer is None:
            raise ConnectionLost("no connection")
        frame = msg.to_bytes()
        async with self._send_lock:
            self._writer.write(frame)
            try:
                await self._writer.drain()
            except (ConnectionResetError, OSError) as exc:
                await self._close_connection()
                raise ConnectionLost(f"send failed: {exc}") from None
        if self.on_frame:
            self.on_frame("out", frame, msg)

    async def _read_loop(self) -> None:
        try:
            while True:
                assert self._reader is not None
                # SEMI E37: T8 is the INTERCHARACTER timeout inside a frame.
                # Inter-frame silence is legitimate (e.g. T3 > T8 waiting for a
                # slow reply); idle-link deadness is covered by Linktest+T6.
                head = await self._reader.readexactly(4)
                length = struct.unpack(">I", head)[0]
                if length < 10 or length > 16 * 1024 * 1024:
                    raise HsmsError(f"invalid frame length {length}")
                rest = await asyncio.wait_for(self._reader.readexactly(length),
                                              timeout=self.config.t8)
                frame = head + rest
                msg = HsmsMessage.parse(frame)
                if self.on_frame:
                    self.on_frame("in", frame, msg)
                await self._dispatch(msg)
        except asyncio.IncompleteReadError:
            self._emit("disconnected", {})
            await self._teardown_connection("peer closed")
        except asyncio.TimeoutError:
            self._emit("t8_timeout", {})
            await self._teardown_connection("T8 timeout")
        except (HsmsError, OSError, ConnectionResetError) as exc:
            self._emit("read_error", {"error": str(exc)})
            await self._teardown_connection(str(exc))

    async def _dispatch(self, msg: HsmsMessage) -> None:
        if msg.is_data:
            fut = self._txns.pop(msg.system_bytes, None)
            if fut and not fut.done():
                fut.set_result(msg)
            if self.on_data:
                task = asyncio.create_task(self._safe_on_data(msg))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
            return
        st = msg.stype
        if st == STYPE_SELECT_REQ:
            if self.state == HsmsState.CONNECTED_NOT_SELECTED:
                rsp = HsmsMessage(session_id=0xFFFF, stype=STYPE_SELECT_RSP,
                                  header2=SELECT_OK, system_bytes=msg.system_bytes)
                await self._send_raw(rsp)
                self._enter_selected()
            else:
                rsp = HsmsMessage(session_id=0xFFFF, stype=STYPE_SELECT_RSP,
                                  header2=SELECT_ALREADY_ACTIVE, system_bytes=msg.system_bytes)
                await self._send_raw(rsp)
        elif st == STYPE_SELECT_RSP:
            fut = self._control_txns.pop(msg.system_bytes, None)
            if fut and not fut.done():
                fut.set_result(msg)
            if msg.header2 != SELECT_OK and self.state != HsmsState.SELECTED:
                self._emit("select_rejected", {"status": msg.header2})
        elif st == STYPE_LINKTEST_REQ:
            rsp = HsmsMessage(session_id=0xFFFF, stype=STYPE_LINKTEST_RSP,
                              system_bytes=msg.system_bytes)
            await self._send_raw(rsp)
        elif st == STYPE_LINKTEST_RSP:
            fut = self._control_txns.pop(msg.system_bytes, None)
            if fut and not fut.done():
                fut.set_result(msg)
        elif st == STYPE_DESELECT_REQ:
            rsp = HsmsMessage(session_id=0xFFFF, stype=STYPE_DESELECT_RSP,
                              header2=SELECT_OK, system_bytes=msg.system_bytes)
            await self._send_raw(rsp)
            self._set_state(HsmsState.CONNECTED_NOT_SELECTED)
            self._emit("deselected", {})
        elif st == STYPE_DESELECT_RSP:
            fut = self._control_txns.pop(msg.system_bytes, None)
            if fut and not fut.done():
                fut.set_result(msg)
            self._set_state(HsmsState.CONNECTED_NOT_SELECTED)
            self._emit("deselected", {})
        elif st == STYPE_SEPARATE_REQ:
            self._emit("separate", {})
            await self._teardown_connection("separate received")
        elif st == STYPE_REJECT_REQ:
            self._emit("rejected", {"reason": msg.header2})
            self._fail_all_txns(HsmsError(f"peer rejected: reason={msg.header2:#x}"))

    async def _safe_on_data(self, msg: HsmsMessage) -> None:
        try:
            if self.on_data:
                await self.on_data(msg)
        except Exception:
            log.exception("on_data handler error")

    def _enter_selected(self) -> None:
        self._cancel_t7()
        self._set_state(HsmsState.SELECTED)
        self._selected_event.set()
        self._emit("selected", {})

    def _set_state(self, new: HsmsState) -> None:
        if self.state != new:
            self.state = new
            self._emit("state_changed", {"state": new.value})

    def _emit(self, event: str, payload: Any) -> None:
        if self.on_event:
            task = asyncio.create_task(self._safe_event(event, payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _safe_event(self, event: str, payload: Any) -> None:
        try:
            if self.on_event:
                await self.on_event(event, payload)
        except Exception:
            log.exception("event handler error for %s", event)

    def _cancel_t7(self) -> None:
        if self._t7_handle:
            self._t7_handle.cancel()
            self._t7_handle = None

    def _fail_all_txns(self, exc: Exception) -> None:
        for fut in list(self._txns.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._txns.clear()
        for fut in list(self._control_txns.values()):
            if not fut.done():
                fut.set_exception(exc)
        self._control_txns.clear()

    async def _teardown_connection(self, reason: str) -> None:
        self._fail_all_txns(ConnectionLost(reason))
        await self._close_connection()
        if self.state == HsmsState.SELECTED:
            self._set_state(HsmsState.CONNECTED_NOT_SELECTED)

    async def _close_connection(self) -> None:
        self._selected_event.clear()
        self._cancel_t7()
        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None
        if self._linktest_task:
            self._linktest_task.cancel()
            self._linktest_task = None
        if self.state != HsmsState.NOT_CONNECTED:
            self._set_state(HsmsState.CONNECTED_NOT_SELECTED)
