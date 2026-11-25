"""FastAPI REST routes (M1/M2/M3 surface per development doc chapter 7)."""
from __future__ import annotations

import asyncio
import pathlib
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from ..core.scenario import ScenarioRunner
from ..core.manager import SessionManager
from ..core.errors import public_error
from ..core.ports import find_free_port, port_is_free

router = APIRouter(prefix="/api/v1")
ws_router = APIRouter()

manager: Optional[SessionManager] = None  # injected by app factory


def get_manager() -> SessionManager:
    if manager is None:
        raise RuntimeError("manager not initialized")
    return manager


def _err(exc: Exception, code: int = 400) -> HTTPException:
    return HTTPException(status_code=code, detail=str(exc))


def _fail(exc: Exception, code: int = 422) -> HTTPException:
    """Actionable error body: {code, message, hint, raw} instead of a raw exception."""
    return HTTPException(status_code=code, detail=public_error(exc))


# ---------------------------------------------------------------- health
@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "0.1.0",
            "sessions": len(get_manager().sessions)}


# ---------------------------------------------------------------- port probes
@router.get("/ports/free")
async def free_port(host: str = "127.0.0.1",
                    start: int = Query(default=5000, ge=1, le=65535),
                    count: int = Query(default=50, ge=1, le=500)) -> dict:
    """First free port at or after `start`, used by the one-click demo wizard."""
    return {"host": host, "port": find_free_port(host, start, count)}


@router.get("/ports/check")
async def check_port(host: str = "127.0.0.1",
                     port: int = Query(ge=1, le=65535)) -> dict:
    """Whether a PASSIVE session can bind host:port right now."""
    return {"host": host, "port": port, "free": port_is_free(host, port)}


@router.get("/overview")
async def overview() -> dict:
    """Aggregated data for the dashboard (one request instead of N+1)."""
    m = get_manager()
    now = time.time()
    sessions: List[dict] = []
    recent: List[dict] = []
    totals = {"sessions": 0, "connected": 0, "communicating": 0, "verified": 0,
              "alarms_active": 0, "messages": 0, "messages_last_minute": 0,
              "data_messages": 0, "data_messages_last_minute": 0}
    for w in m.sessions.values():
        d = w.to_dict()
        logs = list(w.logs)
        active = [str(k) for k, v in getattr(w.session, "alarms_set", {}).items() if v]
        last_minute = sum(1 for item in logs if now - item.get("ts", 0) <= 60)
        data_logs = [item for item in logs if item.get("kind") != "control"]
        data_last_minute = sum(1 for item in data_logs if now - item.get("ts", 0) <= 60)
        # "verified" = communicating AND a user W-primary (not the auto S1F13
        # handshake) was sent, so the onboarding stepper reflects real exchanges
        verified = (d["states"].get("communication") == "COMMUNICATING"
                    and any(item.get("kind") == "data" and item.get("dir") == "out"
                            and item.get("w") and item.get("sf") != "S1F13"
                            for item in logs))
        d.update({"message_count": len(logs), "messages_last_minute": last_minute,
                  "data_messages": len(data_logs),
                  "data_messages_last_minute": data_last_minute,
                  "verified": verified, "alarms_active": active})
        sessions.append(d)
        totals["sessions"] += 1
        totals["messages"] += len(logs)
        totals["messages_last_minute"] += last_minute
        totals["data_messages"] += len(data_logs)
        totals["data_messages_last_minute"] += data_last_minute
        totals["alarms_active"] += len(active)
        if d["states"].get("hsms") == "SELECTED":
            totals["connected"] += 1
        if d["states"].get("communication") == "COMMUNICATING":
            totals["communicating"] += 1
        if verified:
            totals["verified"] += 1
        for item in data_logs[-8:]:
            recent.append({**item, "session_name": w.name})
    recent.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return {"version": "0.1.0", "time": now, "totals": totals,
            "sessions": sessions, "recent": recent[:12]}


# ---------------------------------------------------------------- profiles
@router.get("/profiles")
async def list_profiles() -> List[str]:
    return get_manager().list_profiles()


@router.get("/profiles/{name}")
async def get_profile(name: str) -> dict:
    try:
        return get_manager().load_profile(name)
    except FileNotFoundError as e:
        raise _err(e, 404)


@router.get("/profiles/{name}/text")
async def get_profile_text(name: str) -> dict:
    """Raw YAML source so the web editor round-trips what is on disk."""
    path = pathlib.Path(get_manager().loader.profiles_dir) / name
    if not path.exists():
        raise _err(f"profile not found: {name}", 404)
    return {"name": name, "text": path.read_text(encoding="utf-8")}


@router.post("/profiles/validate")
async def validate_profile(body: dict) -> dict:
    try:
        text = body.get("text", "")
        get_manager().validate_profile(text)
        return {"valid": True}
    except Exception as e:
        return {"valid": False, "error": str(e)}


@router.put("/profiles/{name}")
async def save_profile(name: str, body: dict) -> dict:
    try:
        get_manager().save_profile(name, body.get("text", ""))
        return {"saved": name}
    except Exception as e:
        raise _err(e)


# ---------------------------------------------------------------- sessions
@router.post("/sessions")
async def create_session(body: dict) -> dict:
    try:
        return await get_manager().create_session(
            profile_name=body["profile"],
            role=body.get("role"),
            name=body.get("name"),
            host=body.get("host"),
            port=body.get("port"),
            session_id=body.get("session_id"),
            mode=body.get("mode"),
        )
    except (ValueError, FileNotFoundError) as e:
        raise _err(e)
    except KeyError as e:
        raise _err(f"missing field {e}")


@router.get("/sessions")
async def list_sessions() -> List[dict]:
    return get_manager().list_sessions()


@router.get("/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    try:
        return get_manager().get(session_id).to_dict()
    except KeyError as e:
        raise _err(e, 404)


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    ok = await get_manager().destroy_session(session_id)
    if not ok:
        raise _err("session not found", 404)
    return {"deleted": session_id}


@router.post("/sessions/{session_id}/connect")
async def connect_session(session_id: str) -> dict:
    try:
        return await get_manager().connect(session_id)
    except KeyError as e:
        raise _err(e, 404)


@router.post("/sessions/{session_id}/disconnect")
async def disconnect_session(session_id: str) -> dict:
    try:
        return await get_manager().disconnect(session_id)
    except KeyError as e:
        raise _err(e, 404)


@router.get("/sessions/{session_id}/state")
async def session_state(session_id: str) -> dict:
    try:
        return get_manager().get(session_id).states()
    except KeyError as e:
        raise _err(e, 404)


# ---------------------------------------------------------------- messaging
@router.post("/sessions/{session_id}/send")
async def send_sml(session_id: str, body: dict) -> dict:
    try:
        return await get_manager().send_sml(session_id, body["sml"],
                                            body.get("wait_reply"))
    except KeyError as e:
        raise _err(e, 404)
    except Exception as e:
        raise _fail(e)


@router.get("/sessions/{session_id}/logs")
async def get_logs(session_id: str, direction: Optional[str] = None,
                   sf: Optional[str] = None, text: Optional[str] = None,
                   kind: Optional[str] = None,
                   tail: int = Query(default=200, le=5000)) -> List[dict]:
    try:
        return get_manager().get_logs(session_id, direction, sf, text, kind, tail)
    except KeyError as e:
        raise _err(e, 404)


# ---------------------------------------------------------------- GEM ops
@router.post("/sessions/{session_id}/alarms/{alid}/set")
async def set_alarm(session_id: str, alid: str) -> dict:
    try:
        return await get_manager().set_alarm(session_id, _num(alid), True)
    except KeyError as e:
        raise _err(e, 404)


@router.post("/sessions/{session_id}/alarms/{alid}/clear")
async def clear_alarm(session_id: str, alid: str) -> dict:
    try:
        return await get_manager().set_alarm(session_id, _num(alid), False)
    except KeyError as e:
        raise _err(e, 404)


@router.post("/sessions/{session_id}/events/{ceid}/trigger")
async def trigger_event(session_id: str, ceid: str, body: Optional[dict] = None) -> dict:
    try:
        return await get_manager().trigger_event(
            session_id, _num(ceid), (body or {}).get("values"))
    except KeyError as e:
        raise _err(e, 404)


@router.get("/sessions/{session_id}/variables")
async def get_variables(session_id: str) -> dict:
    try:
        return get_manager().get_variables(session_id)
    except KeyError as e:
        raise _err(e, 404)


@router.put("/sessions/{session_id}/variables")
async def set_variable(session_id: str, body: dict) -> dict:
    try:
        return await get_manager().set_variable(session_id, _num(body["vid"]), body["value"])
    except KeyError as e:
        raise _err(e, 404)


@router.post("/sessions/{session_id}/control-state")
async def control_state(session_id: str, body: dict) -> dict:
    try:
        return await get_manager().switch_control_state(session_id, body["target"])
    except (KeyError, ValueError) as e:
        raise _err(e, 400)


@router.post("/sessions/{session_id}/remote-command")
async def remote_command(session_id: str, body: dict) -> dict:
    try:
        return await get_manager().remote_command(session_id, body["rcmd"],
                                                  body.get("params", {}))
    except KeyError as e:
        raise _err(e, 404)
    except Exception as e:
        raise _fail(e)


@router.post("/sessions/{session_id}/subscribe")
async def subscribe(session_id: str, body: dict) -> dict:
    try:
        return await get_manager().subscribe_events(
            session_id, _num(body["ceid"]), _num(body["rptid"]),
            [_num(s) for s in body.get("svids", [])])
    except Exception as e:
        raise _fail(e)


@router.post("/sessions/{session_id}/query-sv")
async def query_sv(session_id: str, body: dict) -> dict:
    try:
        return await get_manager().query_sv(session_id, [_num(s) for s in body["svids"]])
    except Exception as e:
        raise _fail(e)


@router.post("/sessions/{session_id}/pp/upload")
async def pp_upload(session_id: str, body: dict) -> dict:
    try:
        return await get_manager().pp_upload(session_id, body["ppid"], body["body_b64"])
    except Exception as e:
        raise _fail(e)


@router.post("/sessions/{session_id}/pp/download")
async def pp_download(session_id: str, body: dict) -> dict:
    try:
        return await get_manager().pp_download(session_id, body["ppid"])
    except Exception as e:
        raise _fail(e)


@router.post("/sessions/{session_id}/terminal")
async def terminal(session_id: str, body: dict) -> dict:
    try:
        return await get_manager().terminal(session_id, body["text"], body.get("tid", 0))
    except Exception as e:
        raise _fail(e)


# ---------------------------------------------------------------- scenarios
@router.get("/scenarios")
async def list_scenarios() -> List[str]:
    d = pathlib.Path(get_manager().scenarios_dir)
    return sorted(p.name for p in d.glob("*.yaml")) if d.exists() else []


@router.get("/scenarios/manifest")
async def scenarios_manifest() -> List[dict]:
    """Structured scenario index (role, description, Chinese step summaries)."""
    m = get_manager()
    return ScenarioRunner(m).manifest(m.scenarios_dir)


@router.get("/scenarios/{name}/text")
async def get_scenario_text(name: str) -> dict:
    d = pathlib.Path(get_manager().scenarios_dir)
    path = d / name
    if not path.exists() and not name.endswith(".yaml"):
        path = d / f"{name}.yaml"
    if not path.exists():
        raise _err(f"scenario not found: {name}", 404)
    return {"name": path.name, "text": path.read_text(encoding="utf-8")}


@router.post("/sessions/{session_id}/scenario/{name}/run")
async def run_scenario(session_id: str, name: str, body: Optional[dict] = None) -> dict:
    m = get_manager()
    runner = ScenarioRunner(m)
    try:
        report = await runner.run_file(name, session_id, m.scenarios_dir)
        return report
    except FileNotFoundError as e:
        raise _err(e, 404)
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------- record/replay
@router.post("/sessions/{session_id}/record/start")
async def record_start(session_id: str) -> dict:
    from ..core.recording import Recorder
    import time as _t
    try:
        w = get_manager().get(session_id)
    except KeyError as e:
        raise _err(e, 404)
    rec = Recorder(f"recordings/{session_id}-{int(_t.time())}.jsonl")
    w.session.recorder = rec
    rec.start()
    return {"recording": rec.path}


@router.post("/sessions/{session_id}/record/stop")
async def record_stop(session_id: str) -> dict:
    try:
        w = get_manager().get(session_id)
    except KeyError as e:
        raise _err(e, 404)
    rec = w.session.recorder
    if rec is None:
        raise _err("not recording", 400)
    rec.stop()
    w.session.recorder = None
    return {"recording": rec.path, "frames": rec.count}


@router.post("/sessions/{session_id}/replay")
async def replay(session_id: str, body: dict) -> dict:
    from ..core.recording import replay_recording
    try:
        return await replay_recording(get_manager(), session_id, body["recording"],
                                      speed=float(body.get("speed", 1.0)))
    except Exception as e:
        raise _fail(e)


@router.post("/recordings/compare")
async def compare_recordings(body: dict) -> dict:
    from ..core.recording import compare
    try:
        return compare(body["a"], body["b"])
    except Exception as e:
        raise _fail(e)


# ---------------------------------------------------------------- websocket
@ws_router.websocket("/ws/{session_id}")
async def ws_session(websocket: WebSocket, session_id: str):
    m = get_manager()
    await websocket.accept()
    q = m.bus.subscribe(session_id)
    try:
        # send initial state
        try:
            w = m.get(session_id)
            await websocket.send_json({"type": "state", "payload": {"states": w.states()}})
        except KeyError:
            pass
        import asyncio as _a
        while True:
            recv = _a.create_task(websocket.receive_text())
            pub = _a.create_task(q.get())
            done, pending = await _a.wait({recv, pub},
                                          return_when=_a.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            if recv in done:
                # client ping/close
                try:
                    text = recv.result()
                    if text in ("ping", '{"ping":1}'):
                        await websocket.send_json({"type": "pong"})
                    else:
                        await websocket.send_json({"type": "error",
                                                   "payload": {"message": "unknown command"}})
                except WebSocketDisconnect:
                    break
            if pub in done:
                try:
                    item = pub.result()
                    await websocket.send_json(item)
                except WebSocketDisconnect:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        m.bus.unsubscribe(q, session_id)
        try:
            await websocket.close()
        except Exception:
            pass


@ws_router.websocket("/ws")
async def ws_global(websocket: WebSocket):
    m = get_manager()
    await websocket.accept()
    q = m.bus.subscribe(None)
    try:
        while True:
            item = await q.get()
            await websocket.send_json(item)
    except WebSocketDisconnect:
        pass
    finally:
        m.bus.unsubscribe(q)


def _num(x: Any) -> Any:
    """Path params come as strings; normalize numeric ids to int."""
    if isinstance(x, str):
        try:
            return int(x)
        except ValueError:
            return x
    return x
