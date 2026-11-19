"""Recording & replay: capture session frames to JSONL, replay, compare (golden)."""
from __future__ import annotations

import asyncio
import json
import pathlib
import time
from typing import List, Optional

from .manager import SessionManager


class Recorder:
    """Thread-safe-ish JSONL recorder (called from the engine's loop)."""

    def __init__(self, path: str):
        self.path = str(path)
        self._fh = None
        self.count = 0

    def start(self) -> None:
        p = pathlib.Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self._fh = p.open("w", encoding="utf-8")

    def record(self, entry: dict) -> None:
        if self._fh is None:
            return
        keep = {k: entry.get(k) for k in
                ("ts", "dir", "role", "sf", "w", "system_bytes", "sml",
                 "hex", "kind", "desc") if entry.get(k) is not None}
        self._fh.write(json.dumps(keep, ensure_ascii=False) + "\n")
        self.count += 1

    def stop(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def load(self, path: str) -> List[dict]:
        return [json.loads(line) for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines()
                if line.strip()]


def load_recording(path: str) -> List[dict]:
    p = pathlib.Path(path)
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def compare(path_a: str, path_b: str) -> dict:
    """Golden-file regression: compare two recordings ignoring timestamps and
    hex (hex may differ on system bytes), keyed on dir+sf+sml."""
    a = load_recording(path_a)
    b = load_recording(path_b)
    ka = [(e.get("dir"), e.get("sf"), e.get("sml")) for e in a]
    kb = [(e.get("dir"), e.get("sf"), e.get("sml")) for e in b]
    diffs: List[dict] = []
    n = max(len(ka), len(kb))
    for i in range(n):
        ea = ka[i] if i < len(ka) else None
        eb = kb[i] if i < len(kb) else None
        if ea != eb:
            diffs.append({"index": i, "a": ea, "b": eb})
    return {"ok": len(diffs) == 0, "frames_a": len(a), "frames_b": len(b),
            "diffs": diffs[:50], "diff_count": len(diffs)}


async def replay_recording(mgr: SessionManager, session_id: str, path: str,
                           speed: float = 1.0, wait_reply: bool = False) -> dict:
    """Re-send recorded OUT data messages against the session, preserving gaps."""
    recs = load_recording(path)
    outs = [e for e in recs if e.get("dir") == "out" and e.get("kind") == "data"]
    sent = 0
    prev_ts: Optional[float] = None
    for e in outs:
        if prev_ts is not None:
            gap = max((e["ts"] - prev_ts) / max(speed, 0.01), 0)
            if gap > 0:
                await asyncio.sleep(gap)
        prev_ts = e["ts"]
        text = str(e.get("sf") or "")
        if not text:
            continue
        if e.get("w"):
            text += " W"
        if e.get("sml"):
            text += "\n" + e["sml"]
        try:
            await mgr.send_sml(session_id, text, wait_reply=wait_reply)
            sent += 1
        except Exception:
            pass  # keep replaying
    return {"replayed": sent, "total": len(outs), "recording": path}
