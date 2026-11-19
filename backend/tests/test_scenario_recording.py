"""Scenario runner + recording/replay/golden-compare tests (via manager, no HTTP)."""
import asyncio

import pytest

from fastsim.core.scenario import ScenarioRunner


def test_scenario_remote_command_flow(manager, gem_pair, event_loop):
    runner = ScenarioRunner(manager)
    report = event_loop.run_until_complete(
        runner.run_file("remote-command-flow.yaml", "HOST", str(manager.scenarios_dir)))
    assert report["ok"] is True, report
    assert all(s["ok"] for s in report["steps"])


def test_scenario_alarm_flow(manager, gem_pair, event_loop):
    runner = ScenarioRunner(manager)
    report = event_loop.run_until_complete(
        runner.run_file("alarm-flow.yaml", "EQ", str(manager.scenarios_dir)))
    assert report["ok"] is True, report


def test_scenario_failure_stops_and_reports(manager, gem_pair, event_loop):
    steps = [
        {"action": "query_sv", "svids": [1002], "expect": {"1002": "WRONG"}},
    ]
    runner = ScenarioRunner(manager)
    report = event_loop.run_until_complete(runner.run_steps(steps, "HOST", "negative"))
    assert report["ok"] is False
    assert "expect" in report["steps"][0]["detail"]["error"]


def test_scenario_unknown_action(manager, gem_pair, event_loop):
    steps = [{"action": "no_such_action"}]
    runner = ScenarioRunner(manager)
    report = event_loop.run_until_complete(runner.run_steps(steps, "EQ", "x"))
    assert report["ok"] is False
    assert "unknown action" in report["steps"][0]["detail"]["error"]


def test_scenario_cross_session_steps(manager, gem_pair, event_loop):
    # steps running against different sessions via `session:` override
    steps = [
        {"action": "subscribe", "ceid": 6001, "rptid": 7001,
         "svids": [1001, 1002, 1003], "session": "HOST"},
        {"action": "set_alarm", "alid": 5001, "on": True, "session": "EQ"},
        {"action": "wait_event", "event": "alarm", "timeout": 5,
         "where": {"alid": 5001}, "session": "HOST"},
    ]
    runner = ScenarioRunner(manager)
    report = event_loop.run_until_complete(runner.run_steps(steps, "EQ", "cross"))
    assert report["ok"] is True, report


def test_recording_golden_compare(manager, gem_pair, event_loop):
    from fastsim.core.recording import Recorder, compare

    async def record():
        eq = manager.get("EQ").session
        rec = Recorder("recordings/test-golden-a.jsonl")
        rec.start()
        eq.recorder = rec
        await eq.set_alarm(5002, True)
        await asyncio.sleep(1.0)
        rec.stop()
        eq.recorder = None
        return rec

    rec = event_loop.run_until_complete(record())
    assert rec.count > 0
    r = compare(rec.path, rec.path)
    assert r["ok"] is True and r["diff_count"] == 0
