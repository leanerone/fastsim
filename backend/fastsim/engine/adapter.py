"""Engine abstraction. The builtin asyncio engine is the default implementation;
secsgem/.NET engines can implement the same interface later (license escape hatch)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Optional

from .builtin.secs2 import Item


class EngineAdapter(ABC):
    """Minimal surface the FastSim core drives; engines emit events back."""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send(self, stream: int, function: int, body: Optional[Item] = None,
                   wbit: bool = False, system_bytes: Optional[int] = None) -> Any:
        """Send primary/secondary message; waits T3 when wbit."""

    @abstractmethod
    async def reply(self, primary: Any, stream: int, function: int,
                    body: Optional[Item] = None) -> None: ...

    @abstractmethod
    def states(self) -> dict:
        """{'hsms': ..., 'communication': ..., 'control': ...}"""
