"""Full GEM loopback tests (equipment handler set + host helpers)."""
import asyncio

import pytest

from fastsim.engine.builtin.secs2 import Item


def _capture_events(wrapper, store):
    """Wrap a SessionWrapper's emit so events are collected into store list."""
    real = wrapper.session.emit

    async def emit(event_type, payload):
        store.append({"type": event_type, "payload": payload})
        await real(event_type, payload)

    wrapper.session.emit = emit
    return store


def test_establish_and_states(gem_pair, event_loop):
    eq, host = gem_pair
    assert eq.states()["hsms"] == "SELECTED"
    assert eq.states()["communication"] == "COMMUNICATING"
    assert host.states()["hsms"] == "SELECTED"


def test_are_you_there(gem_pair, event_loop):
    eq, host = gem_pair

    async def run():
        rsp = await host.session.send(1, 1, None, wbit=True)
        assert rsp is not None and rsp.function == 2
        body = Item.decode(rsp.body, 0)
        assert body[0].first() == "ETCH300"
        assert body[1].first() == "2.1.0"

    event_loop.run_until_complete(run())


def test_alarm_and_event_flow(gem_pair, event_loop):
    eq, host = gem_pair
    eqs, hosts = eq.session, host.session
    events = _capture_events(host, [])

    async def run():
        await hosts.host_subscribe(6001, 7001, [1001, 1002, 1003])
        await hosts.host_define_report(7001, [1001, 1002, 1003])
        await hosts.host_link_event(6002, 7001)
        await hosts.host_enable_events([6002], True)
        await asyncio.sleep(0.3)
        await eqs.set_alarm(5001, True)
        # let S5F1/S6F11 round-trips complete
        await asyncio.sleep(1.5)
        ceids = [e["payload"].get("ceid") for e in events
                 if e["type"] == "collection_event"]
        assert 6001 in ceids, f"expected 6001 in {ceids}"
        alarms = [e["payload"] for e in events if e["type"] == "alarm"]
        assert any(a["alid"] == 5001 and a["set"] for a in alarms)
        # report content check
        rpts = [e["payload"]["reports"] for e in events
                if e["type"] == "collection_event" and e["payload"].get("ceid") == 6001]
        assert rpts[0]["7001"]["1002"] == "IDLE"

        # clear -> ceid 6002
        await eqs.set_alarm(5001, False)
        await asyncio.sleep(1.0)
        ceids = [e["payload"].get("ceid") for e in events
                 if e["type"] == "collection_event"]
        assert 6002 in ceids

    event_loop.run_until_complete(run())


def test_remote_command_behavior(gem_pair, event_loop):
    eq, host = gem_pair
    eqs, hosts = eq.session, host.session
    events = _capture_events(host, [])

    async def run():
        await hosts.host_subscribe(6003, 7002, [2001, 2002, 1003])
        rc = await hosts.host_send_remote_command("START", {"RECIPE": "R-1"})
        assert rc["hcack"] == 0
        await asyncio.sleep(1.2)
        ceids = [e["payload"].get("ceid") for e in events
                 if e["type"] == "collection_event"]
        assert 6003 in ceids, events
        rpts = [e["payload"]["reports"] for e in events
                if e["type"] == "collection_event" and e["payload"].get("ceid") == 6003]
        assert rpts[0]["7002"]["2001"] == "R-1"
        sv = await hosts.host_query_sv([1002, 2001])
        assert sv["1002"] == "RUNNING" and sv["2001"] == "R-1"

        # unknown command -> HCACK 1
        rc2 = await hosts.host_send_remote_command("NO_SUCH_CMD", {})
        assert rc2["hcack"] == 1

    event_loop.run_until_complete(run())


def test_s7_process_program(gem_pair, event_loop):
    eq, host = gem_pair
    eqs, hosts = eq.session, host.session

    async def run():
        up = await hosts.host_pp_upload("RECIPE-X", b"step1;step2")
        assert up["ackc7"] == 0
        body = await hosts.host_pp_download("RECIPE-X")
        assert body == b"step1;step2"
        body2 = await hosts.host_pp_download("NO-SUCH")
        assert body2 == b""
        # list
        rsp = await hosts.send(7, 19, None, wbit=True)
        body = Item.decode(rsp.body, 0)
        assert "RECIPE-X" in [c.first() for c in body.value]

    event_loop.run_until_complete(run())


def test_terminal_s10f3(gem_pair, event_loop):
    eq, host = gem_pair
    eqs, hosts = eq.session, host.session
    events = _capture_events(eq, [])

    async def run():
        ack = await hosts.host_terminal("hello operator")
        assert ack == 0
        await asyncio.sleep(0.5)
        terms = [e["payload"] for e in events if e["type"] == "terminal_display"]
        assert terms and terms[0]["text"] == "hello operator"

    event_loop.run_until_complete(run())


def test_unknown_function_s9f5(gem_pair, event_loop):
    eq, host = gem_pair

    async def run():
        rsp = await host.session.send(11, 1, Item.L([]), wbit=True)
        assert rsp is not None and rsp.function == 5  # S9F5 Unknown Function

    event_loop.run_until_complete(run())


def test_control_state_transitions(gem_pair, event_loop):
    eq, host = gem_pair
    eqs, hosts = eq.session, host.session

    async def run():
        onlack = await hosts.host_go_offline_request()
        assert onlack == 0
        assert eqs.control_state == "HOST_OFFLINE"
        onlack = await hosts.host_go_online_request()
        assert onlack == 0
        assert eqs.control_state == "ONLINE_REMOTE"

    event_loop.run_until_complete(run())


def test_clock_sync(gem_pair, event_loop):
    eq, host = gem_pair
    eqs, hosts = eq.session, host.session

    async def run():
        rsp = await hosts.send(2, 17, None, wbit=True)
        body = Item.decode(rsp.body, 0)
        assert len(body.first()) == 12  # yyMMddHHmmss
        rsp2 = await hosts.send(2, 31, Item.from_value("A", "260101120000"), wbit=True)
        body2 = Item.decode(rsp2.body, 0)
        assert body2.first() == 0
        assert eqs.clock.strftime("%y%m%d%H%M%S") == "260101120000"

    event_loop.run_until_complete(run())


def test_ec_read_write(gem_pair, event_loop):
    eq, host = gem_pair
    eqs, hosts = eq.session, host.session

    async def run():
        # read EC via S2F13
        rsp = await hosts.send(
            2, 13, Item.L([Item.from_value("U4", 3002)]), wbit=True)
        body = Item.decode(rsp.body, 0)
        assert body[0].first() == pytest.approx(1.2, rel=0.01)
        # write EC via S2F15
        rsp2 = await hosts.send(
            2, 15, Item.L([Item.L([Item.from_value("U4", 3002),
                                   Item.from_value("F4", 2.5)])]), wbit=True)
        body2 = Item.decode(rsp2.body, 0)
        assert body2[0].first() == 0
        assert eqs.ec_values[3002] == 2.5
        # out-of-range -> EAC 3
        rsp3 = await hosts.send(
            2, 15, Item.L([Item.L([Item.from_value("U4", 3002),
                                   Item.from_value("F4", 999)])]), wbit=True)
        body3 = Item.decode(rsp3.body, 0)
        assert body3[0].first() == 3

    event_loop.run_until_complete(run())


def test_trigger_event_requires_enabled(gem_pair, event_loop):
    eq, host = gem_pair
    eqs, hosts = eq.session, host.session
    events = _capture_events(host, [])

    async def run():
        # 6005 NOT enabled -> API trigger returns False, nothing received
        sent = await eqs.trigger_collection_event(6005)
        assert sent is False
        # enable via host (S2F33/35/37)
        await hosts.host_define_report(7002, [2001, 2002, 1003])
        await hosts.host_link_event(6005, 7002)
        await hosts.host_enable_events([6005], True)
        sent = await eqs.trigger_collection_event(6005)
        assert sent is True
        await asyncio.sleep(1.0)
        ceids = [e["payload"].get("ceid") for e in events
                 if e["type"] == "collection_event"]
        assert 6005 in ceids

    event_loop.run_until_complete(run())
