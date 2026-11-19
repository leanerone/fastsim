"""HSMS-SS protocol layer tests: loopback, control messages, T7, transactions."""
import asyncio

import pytest

from fastsim.engine.builtin.hsms import (HsmsConfig, HsmsProtocol, HsmsState,
                                         T3Timeout)
from tests.conftest import free_port


def _pair(port):
    passive = HsmsProtocol(HsmsConfig(mode="PASSIVE", port=port, t3=5, t5=2, t7=5,
                                      linktest_interval=0, name="passive"))
    active = HsmsProtocol(HsmsConfig(mode="ACTIVE", port=port, t3=5, t5=1, t7=5,
                                     linktest_interval=0, name="active"))
    return passive, active


def test_select_and_data_loopback(event_loop):
    port = free_port()
    passive, active = _pair(port)

    async def run():
        await passive.start()
        await active.start()
        for _ in range(50):
            if active.state == HsmsState.SELECTED and passive.state == HsmsState.SELECTED:
                break
            await asyncio.sleep(0.1)
        assert active.state == HsmsState.SELECTED
        assert passive.state == HsmsState.SELECTED

        # W-bit transaction loopback: active sends S1F1 W, passive auto-reply via handler
        from fastsim.engine.builtin.secs2 import Item

        async def on_data(msg):
            from fastsim.engine.builtin.secs2 import Item as I
            body = I.decode(msg.body, 0) if msg.body else None
            await passive.reply_data(msg, msg.stream, msg.function + 1,
                                     I.L([I.from_value("A", "world")]))
        passive.on_data = on_data
        rsp = await active.send_data(1, 1, Item.from_value("A", "hello"), wbit=True)
        assert rsp is not None and rsp.function == 2
        text = Item.decode(rsp.body, 0)[0].first()
        assert text == "world"

        # non-W send: no reply wait
        fut = asyncio.create_task(active.send_data(1, 1, None, wbit=False))
        await asyncio.wait_for(fut, timeout=2)
        await asyncio.sleep(0.2)  # let passive handler run (reply with W? no - our handler replies anyway)

        # deselect
        await active.deselect()
        assert active.state == HsmsState.CONNECTED_NOT_SELECTED

        # re-select
        await active.select()
        assert active.state == HsmsState.SELECTED

        # linktest
        await active.linktest()

        # separate
        await active.separate()
        await asyncio.sleep(0.3)
        assert active.state == HsmsState.NOT_CONNECTED

        await active.stop()
        await passive.stop()

    event_loop.run_until_complete(run())


def test_t3_timeout(event_loop):
    port = free_port()
    passive, active = _pair(port)

    async def run():
        passive.config.t3 = 1
        active.config.t3 = 1
        await passive.start()
        await active.start()
        for _ in range(50):
            if active.state == HsmsState.SELECTED:
                break
            await asyncio.sleep(0.1)
        with pytest.raises(T3Timeout):
            await active.send_data(1, 1, None, wbit=True)
        await active.stop()
        await passive.stop()

    event_loop.run_until_complete(run())


def test_t7_passive_no_select(event_loop):
    """Passive side must drop connection if no Select.req within T7."""
    import socket as _s
    port = free_port()
    server_started = asyncio.Event()

    async def run():
        cfg = HsmsConfig(mode="PASSIVE", port=port, t7=1, linktest_interval=0)
        passive = HsmsProtocol(cfg)
        await passive.start()
        for _ in range(30):
            if passive._server:
                break
            await asyncio.sleep(0.05)

        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        # send nothing; wait for server to close (T7=1s + margin)
        got_eof = False
        try:
            await asyncio.wait_for(reader.read(), timeout=4)
            got_eof = True
        except asyncio.TimeoutError:
            pass
        writer.close()
        assert got_eof, "passive should close on T7 expiry"
        await passive.stop()

    event_loop.run_until_complete(run())


def test_system_bytes_matching(event_loop):
    port = free_port()
    passive, active = _pair(port)

    async def run():
        await passive.start()
        await active.start()
        for _ in range(50):
            if active.state == HsmsState.SELECTED:
                break
            await asyncio.sleep(0.1)

        # interleave two transactions; replies must match by system bytes
        from fastsim.engine.builtin.secs2 import Item

        async def on_data(msg):
            body = Item.decode(msg.body, 0)
            await passive.reply_data(msg, msg.stream, msg.function + 1,
                                     Item.L([body]))
        passive.on_data = on_data

        t1 = asyncio.create_task(active.send_data(1, 1, Item.from_value("A", "first"), wbit=True))
        await asyncio.sleep(0.05)
        t2 = asyncio.create_task(active.send_data(1, 3, Item.from_value("A", "second"), wbit=True))
        r1 = await asyncio.wait_for(t1, timeout=3)
        r2 = await asyncio.wait_for(t2, timeout=3)
        assert Item.decode(r1.body, 0)[0].first() == "first"
        assert Item.decode(r2.body, 0)[0].first() == "second"

        await active.stop()
        await passive.stop()

    event_loop.run_until_complete(run())
