"""SECS-II item codec (SEMI E5).

Implements all 14 SECS-II data types with encode/decode, JSON-safe dict
conversion and SML rendering. Pure data layer, no I/O.
"""
from __future__ import annotations

import struct
from typing import Any, List, Optional, Union

# format code -> kind name (top 4 bits of format byte)
FORMAT_NAMES = {
    0x0: "L",
    0x1: "B",
    0x2: "BOOLEAN",
    0x4: "A",
    0x5: "J",
    0x6: "I8",
    0x7: "I1",
    0x8: "I2",
    0x9: "I4",
    0xA: "F8",
    0xB: "F4",
    0xC: "U1",
    0xD: "U2",
    0xE: "U4",
    0xF: "U8",
}
KIND_TO_FORMAT = {v: k for k, v in FORMAT_NAMES.items()}
KIND_SIZE = {
    "I8": 8, "I1": 1, "I2": 2, "I4": 4,
    "F8": 8, "F4": 4,
    "U8": 8, "U1": 1, "U2": 2, "U4": 4,
    "B": 1, "BOOLEAN": 1,
}
INT_KINDS = {"I1", "I2", "I4", "I8", "U1", "U2", "U4", "U8"}
INT_PACK = {"I1": "b", "U1": "B", "I2": "h", "U2": "H",
            "I4": "i", "U4": "I", "I8": "q", "U8": "Q"}
FLOAT_KINDS = {"F4", "F8"}


class SecsError(Exception):
    """Base error for SECS-II encode/decode problems."""


class Item:
    """A SECS-II data item (list or scalar array)."""

    def __init__(self, kind: str, value: Any = None):
        kind = kind.upper()
        if kind not in KIND_TO_FORMAT:
            raise SecsError(f"unknown SECS-II kind: {kind!r}")
        self.kind = kind
        self.value = value if value is not None else ([] if kind == "L" else [])

    # ---------- constructors ----------
    @classmethod
    def L(cls, items: Optional[List["Item"]] = None) -> "Item":
        return cls("L", list(items or []))

    @classmethod
    def from_value(cls, kind: str, value: Any) -> "Item":
        """Build an Item from a python value, coercing element types."""
        kind = kind.upper()
        it = cls(kind)
        if kind == "L":
            if not isinstance(value, (list, tuple)):
                raise SecsError("L value must be a list")
            it.value = [v if isinstance(v, Item) else cls.from_value(kind_of(v), v)
                        for v in value]
            return it
        if value is None:
            it.value = b"" if kind in ("A", "J", "B") else []
            return it
        if isinstance(value, Item):
            raise SecsError("scalar item value must not be an Item")
        if kind == "A":
            if isinstance(value, (list, tuple)):
                value = "".join(str(v) for v in value)
            it.value = str(value).encode("ascii", "replace") if not isinstance(value, bytes) else bytes(value)
        elif kind == "J":
            if isinstance(value, (list, tuple)):
                value = "".join(str(v) for v in value)
            it.value = str(value).encode("latin-1", "replace") if not isinstance(value, bytes) else bytes(value)
        elif kind == "B":
            vals = value if isinstance(value, (list, tuple)) else [value]
            it.value = bytes(int(v) & 0xFF for v in vals)
        elif kind == "BOOLEAN":
            vals = value if isinstance(value, (list, tuple)) else [value]
            it.value = [bool(v) for v in vals]
        elif kind in INT_KINDS:
            vals = value if isinstance(value, (list, tuple)) else [value]
            it.value = [int(v) for v in vals]
        elif kind in FLOAT_KINDS:
            vals = value if isinstance(value, (list, tuple)) else [value]
            it.value = [float(v) for v in vals]
        else:  # pragma: no cover
            raise SecsError(f"unhandled kind {kind}")
        return it

    # ---------- introspection ----------
    @property
    def is_list(self) -> bool:
        return self.kind == "L"

    def __len__(self) -> int:
        return len(self.value)

    def __getitem__(self, idx: Union[int, str]) -> Any:
        if isinstance(idx, str):
            return self.get_by_name(idx)
        if self.kind != "L":
            raise TypeError(f"{self.kind} item is not a list; use .first()/.value for scalars")
        child = self.value[idx]
        return child

    def get_by_name(self, name: str) -> "Item":
        for child in self.value:
            if isinstance(child, Item) and getattr(child, "name", None) == name:
                return child
        raise KeyError(name)

    def first(self) -> Any:
        """Convenience: first logical value (str for A/J, int for numerics...)."""
        if self.kind in ("A", "J"):
            codec = "ascii" if self.kind == "A" else "latin-1"
            return bytes(self.value).decode(codec, "replace") if len(self.value) else ""
        if self.kind == "B":
            raw = bytes(self.value)
            if len(raw) == 1:
                return raw[0]
            return raw
        if isinstance(self.value, list):
            return self.value[0] if self.value else None
        return None

    def as_list(self) -> List[Any]:
        if isinstance(self.value, bytes):
            if self.kind in ("A", "J"):
                codec = "ascii" if self.kind == "A" else "latin-1"
                return [bytes(self.value).decode(codec, "replace")]
            # B: list of ints (byte-faithful)
            return list(bytes(self.value))
        out = []
        for v in self.value:
            if isinstance(v, bytes):
                out.append(bytes(v))
            elif isinstance(v, bytearray):
                out.append(bytes(v))
            else:
                out.append(v)
        return out

    # ---------- encoding ----------
    def encode(self) -> bytes:
        fmt = KIND_TO_FORMAT[self.kind]
        if self.kind == "L":
            body = b"".join(child.encode() for child in self.value)
            return _header(fmt, len(self.value)) + body
        if self.kind in ("A", "J", "B"):
            body = bytes(self.value)
        elif self.kind == "BOOLEAN":
            body = bytes(1 if v else 0 for v in self.value)
        elif self.kind in INT_KINDS:
            n = len(self.value)
            body = b"" if n == 0 else struct.pack(f">{n}{INT_PACK[self.kind]}", *self.value)
        elif self.kind == "F4":
            n = len(self.value)
            body = b"" if n == 0 else struct.pack(f">{n}f", *self.value)
        elif self.kind == "F8":
            n = len(self.value)
            body = b"" if n == 0 else struct.pack(f">{n}d", *self.value)
        else:  # pragma: no cover
            raise SecsError(f"unhandled kind {self.kind}")
        return _header(fmt, len(body)) + body

    # ---------- decoding ----------
    @classmethod
    def decode(cls, data: bytes, pos: int = 0) -> "Item":
        try:
            fmt, length, newpos = _decode_header(data, pos)
        except IndexError:
            raise SecsError("truncated SECS-II item header") from None
        kind = FORMAT_NAMES[fmt]
        if kind == "L":
            items: List[Item] = []
            p = newpos
            for _ in range(length):
                child = cls.decode(data, p)
                p = child._end
                items.append(child)
            it = cls("L", items)
            it._end = p
            return it
        body = data[newpos:newpos + length]
        if len(body) < length:
            raise SecsError("truncated SECS-II item body")
        it = cls._from_raw(kind, body)
        it._end = newpos + length
        return it

    @classmethod
    def decode_full(cls, data: bytes) -> "Item":
        """Decode exactly one item that spans the whole buffer."""
        it = cls.decode(data, 0)
        if it._end != len(data):
            raise SecsError("trailing bytes after SECS-II item")
        return it

    @classmethod
    def _from_raw(cls, kind: str, body: bytes) -> "Item":
        it = cls(kind)
        if kind in ("A", "J", "B"):
            it.value = bytes(body)
        elif kind == "BOOLEAN":
            it.value = [v != 0 for v in body]
        elif kind in INT_KINDS:
            size = KIND_SIZE[kind]
            if len(body) % size != 0:
                raise SecsError(f"bad {kind} body length {len(body)}")
            n = len(body) // size
            it.value = [] if n == 0 else list(struct.unpack(f">{n}{INT_PACK[kind]}", body))
        elif kind == "F4":
            n = len(body) // 4
            it.value = [] if n == 0 else list(struct.unpack(f">{n}f", body))
        elif kind == "F8":
            n = len(body) // 8
            it.value = [] if n == 0 else list(struct.unpack(f">{n}d", body))
        return it

    # ---------- JSON-safe ----------
    def to_dict(self) -> Any:
        if self.kind == "L":
            return {"type": "L", "value": [c.to_dict() for c in self.value]}
        return {"type": self.kind, "value": self.as_list()}

    @classmethod
    def from_dict(cls, d: Any) -> "Item":
        if isinstance(d, Item):
            return d
        if isinstance(d, dict):
            kind = str(d.get("type", "L")).upper()
            value = d.get("value")
            if kind == "L":
                return cls("L", [cls.from_dict(c) for c in (value or [])])
            return cls.from_value(kind, value if value is not None else [])
        return cls.from_value(kind_of(d), d)

    # ---------- SML ----------
    def to_sml(self, indent: int = 0) -> str:
        pad = "  " * indent
        if self.kind == "L":
            if not self.value:
                return f"{pad}<L []>"
            inner = "\n".join(c.to_sml(indent + 1) for c in self.value)
            return f"{pad}<L [{len(self.value)}]\n{inner}\n{pad}>"
        if self.kind in ("A", "J"):
            codec = "ascii" if self.kind == "A" else "latin-1"
            text = bytes(self.value).decode(codec, "replace").replace('"', '\\"')
            return f'{pad}<{self.kind} "{text}">'
        if self.kind == "B":
            return f"{pad}<B " + " ".join(f"0x{v:02X}" for v in bytes(self.value)) + ">"
        if self.kind == "BOOLEAN":
            return f"{pad}<BOOLEAN " + " ".join("TRUE" if v else "FALSE" for v in self.value) + ">"
        vals = " ".join(_num_repr(v) for v in self.value)
        return f"{pad}<{self.kind} {vals}>"

    def __repr__(self) -> str:  # pragma: no cover
        return f"Item({self.kind}, {self.value!r})"


def _num_repr(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def kind_of(value: Any) -> str:
    """Infer SECS-II kind for a python value."""
    if isinstance(value, bool):
        return "BOOLEAN"
    if isinstance(value, int):
        return "U4"
    if isinstance(value, float):
        return "F8"
    if isinstance(value, str):
        return "A"
    if isinstance(value, (bytes, bytearray)):
        return "B"
    if isinstance(value, (list, tuple)):
        return "L"
    raise SecsError(f"cannot infer kind for {type(value)}")


def _header(fmt: int, length: int) -> bytes:
    n = 1 if length < 256 else (2 if length < 65536 else 3)
    return bytes([(fmt << 4) | n]) + length.to_bytes(n, "big")


def _decode_header(data: bytes, pos: int) -> "tuple[int, int, int]":
    b = data[pos]
    fmt = (b >> 4) & 0x0F
    n = b & 0x07
    if n == 0 or n > 3:
        raise SecsError(f"invalid length-byte count {n}")
    length = int.from_bytes(data[pos + 1:pos + 1 + n], "big")
    return fmt, length, pos + 1 + n
