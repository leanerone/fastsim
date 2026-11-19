"""SML (SECS Message Language) parser & formatter.

Compatible with the WinSECS dialect (grammar extracted from the official
WSSML.BAS sample): message headers like ``name : SxFy W``, direction
annotations ``H->E`` / ``E->H``, ``.`` terminators, ``/* */`` and ``//``
comments, and standard item bodies ``<L [2] ...> <A "text"> <U4 1 2 3>``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from .secs2 import Item, SecsError

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>/\*.*?\*/|//[^\n]*)
  | (?P<dir>[HE]->[HE])
  | (?P<angle><|>)
  | (?P<brack>\[|\])
  | (?P<string>"(?:[^"\\]|\\.)*")
  | (?P<colon>:)
  | (?P<dot>\.(?=$|\s))
  | (?P<arrow>->)
  | (?P<word>[^\s<>\[\]":]+)
    """,
    re.VERBOSE | re.DOTALL,
)

_SF_RE = re.compile(r"^S(\d{1,3})F(\d{1,3})(W?)$", re.IGNORECASE)
_INT_RE = re.compile(r"^[+-]?\d+$")
_FLOAT_RE = re.compile(r"^[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?$")
SCALAR_TYPES = {"B", "BOOLEAN", "A", "J", "I1", "I2", "I4", "I8",
                "F4", "F8", "U1", "U2", "U4", "U8"}


class SmlError(SecsError):
    """SML parse error."""


@dataclass
class SmlMessage:
    """A parsed SML message: header (S/F/W/name) + body Item."""
    stream: int
    function: int
    w_bit: bool = False
    name: Optional[str] = None
    direction: Optional[str] = None
    body: Optional[Item] = None

    @property
    def sf(self) -> str:
        return f"S{self.stream}F{self.function}"

    def to_sml(self, indent: int = 0) -> str:
        head = f"{self.sf} W" if self.w_bit else self.sf
        if self.name:
            head = f"{self.name} : {head}"
        if self.direction:
            head += f"  {self.direction}"
        if self.body is not None:
            return f"{head}\n{self.body.to_sml(indent)}"
        return head + "\n" + "  " * indent + "<L []>"


@dataclass
class SmlTransaction:
    """WinSECS-style transaction: ``name H->E < S1F1 S1F2 >.``"""
    name: str
    direction: Optional[str] = None
    messages: List[str] = field(default_factory=list)


def _tokenize(text: str) -> List[Tuple[str, Any]]:
    tokens: List[Tuple[str, Any]] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise SmlError(f"unexpected character {text[pos]!r} at offset {pos}")
        pos = m.end()
        kind = m.lastgroup
        val = m.group()
        if kind in ("ws", "comment"):
            continue
        if kind == "string":
            tokens.append(("string", val[1:-1].replace('\\"', '"')))
        elif kind in ("angle", "brack", "colon", "dot", "arrow"):
            tokens.append((kind, val))
        else:  # word / dir / num
            tokens.append(("word", val))
    tokens.append(("eof", None))
    return tokens


def _make_scalar(ttype: str, values: List[Any]) -> Item:
    if not values:
        return Item.from_value(ttype, None)
    if ttype in ("A", "J"):
        if len(values) == 1:
            return Item.from_value(ttype, str(values[0]))
        raise SmlError(f"<{ttype}> takes a single quoted string")
    if ttype == "B":
        out = []
        for v in values:
            s = str(v)
            out.append(int(s, 16) if s.lower().startswith("0x") else int(s))
        return Item.from_value("B", out)
    if ttype == "BOOLEAN":
        out = []
        for v in values:
            s = str(v).strip().upper()
            out.append(s not in ("FALSE", "0", "NO"))
        return Item.from_value("BOOLEAN", out)
    out = []
    for v in values:
        s = str(v)
        if _INT_RE.match(s):
            out.append(int(s))
        elif _FLOAT_RE.match(s):
            out.append(float(s))
        else:
            raise SmlError(f"invalid numeric value {v!r} in <{ttype}>")
    if ttype in ("F4", "F8"):
        return Item.from_value(ttype, [float(x) for x in out])
    return Item.from_value(ttype, out)


class _Parser:
    def __init__(self, tokens: List[Tuple[str, Any]]):
        self.toks = tokens
        self.i = 0

    def peek(self, ahead: int = 0) -> Tuple[str, Any]:
        j = min(self.i + ahead, len(self.toks) - 1)
        return self.toks[j]

    def next(self) -> Tuple[str, Any]:
        tok = self.toks[self.i]
        if tok[0] != "eof":
            self.i += 1
        return tok

    def expect(self, kind: str, val: Any = None) -> Tuple[str, Any]:
        tok = self.next()
        if tok[0] != kind or (val is not None and tok[1] != val):
            raise SmlError(f"expected {val or kind}, got {tok[1]!r}")
        return tok

    def _try_direction(self) -> Optional[str]:
        """Consume ``H -> E`` / ``E -> H`` style direction if present."""
        k, v = self.peek()
        if k == "word" and str(v) in ("H", "E") and self.peek(1)[0] == "arrow":
            side1 = self.next()[1]
            self.next()  # arrow
            side2 = self.expect("word")[1]
            return f"{side1}->{side2}"
        if k == "word" and str(v) in ("H->E", "E->H"):
            return str(self.next()[1])
        return None

    def parse_message(self) -> SmlMessage:
        msg = SmlMessage(stream=0, function=0)
        # optional "name :"
        if self.peek()[0] == "word" and self.peek(1) == ("colon", ":"):
            msg.name = str(self.next()[1])
            self.next()  # colon
        # SxFy [W]
        kind, val = self.next()
        m = _SF_RE.match(str(val))
        if kind != "word" or not m:
            raise SmlError(f"expected SxFy header, got {val!r}")
        msg.stream = int(m.group(1))
        msg.function = int(m.group(2))
        if m.group(3):
            msg.w_bit = True
        elif self.peek() == ("word", "W"):
            self.next()
            msg.w_bit = True
        msg.direction = self._try_direction()
        msg.body = self.parse_body()
        if self.peek() == ("dot", "."):
            self.next()
        return msg

    def parse_body(self) -> Optional[Item]:
        if self.peek()[0] != "angle":
            return None
        return self.parse_item()

    def parse_item(self) -> Item:
        self.expect("angle", "<")
        kind, tval = self.next()
        if kind != "word":
            raise SmlError(f"expected type name, got {tval!r}")
        ttype = str(tval).upper()
        if ttype not in ("L",) and ttype not in SCALAR_TYPES:
            raise SmlError(f"unknown SML type {tval!r}")
        # optional [n] length hint
        if self.peek() == ("brack", "["):
            self.next()
            self.next()  # count
            self.expect("brack", "]")
        if ttype == "L":
            children: List[Item] = []
            while True:
                k, v = self.peek()
                if k == "eof":
                    raise SmlError("unterminated <L> list")
                if (k, v) == ("angle", ">"):
                    break
                children.append(self.parse_item())
            self.expect("angle", ">")
            return Item("L", children)
        values: List[Any] = []
        while True:
            k, v = self.peek()
            if k == "eof":
                raise SmlError(f"unterminated <{ttype}> item")
            if k == "angle" and v == ">":
                break
            if k == "angle" and v == "<":
                raise SmlError(f"unexpected nested < inside <{ttype}> item")
            self.next()
            values.append(v)
        self.expect("angle", ">")
        return _make_scalar(ttype, values)

    def parse_transaction(self) -> SmlTransaction:
        kind, name = self.next()
        if kind != "word":
            raise SmlError(f"expected transaction name, got {name!r}")
        tr = SmlTransaction(name=str(name))
        tr.direction = self._try_direction()
        self.expect("angle", "<")
        while self.peek() != ("angle", ">"):
            kind, val = self.next()
            if kind == "eof":
                raise SmlError("unterminated transaction")
            if kind != "word" or not _SF_RE.match(str(val)):
                raise SmlError(f"expected SxFy in transaction, got {val!r}")
            tr.messages.append(str(val))
        self.expect("angle", ">")
        if self.peek() == ("dot", "."):
            self.next()
        return tr


def parse(text: str) -> SmlMessage:
    """Parse a single SML message (with optional name/direction annotations)."""
    p = _Parser(_tokenize(text))
    msg = p.parse_message()
    if p.peek()[0] != "eof":
        raise SmlError(f"unexpected trailing token {p.peek()[1]!r}")
    return msg


def parse_all(text: str) -> List[SmlMessage]:
    """Parse a document containing one or more messages."""
    p = _Parser(_tokenize(text))
    msgs = []
    while p.peek()[0] != "eof":
        msgs.append(p.parse_message())
    return msgs


def parse_item(text: str) -> Item:
    """Parse a bare item body (without SxFy header), e.g. ``<L [2] <A \"X\">>``."""
    p = _Parser(_tokenize(text))
    it = p.parse_item()
    if p.peek()[0] != "eof":
        raise SmlError(f"unexpected trailing token {p.peek()[1]!r}")
    return it


def try_parse_transaction(text: str) -> Optional[SmlTransaction]:
    """If text is a WinSECS-style transaction (not a message), parse it.
    Non-transaction-looking text (e.g. classic IF syntax) returns None."""
    toks = _tokenize(text)
    first = toks[0]
    is_name_msg = first[0] == "word" and _SF_RE.match(str(first[1]))
    if first[0] == "word" and not is_name_msg and toks[1] != ("colon", ":"):
        try:
            p = _Parser(toks)
            return p.parse_transaction()
        except SmlError:
            return None
    return None


def format_message(msg: SmlMessage) -> str:
    return msg.to_sml()


def format_item(item: Item) -> str:
    return item.to_sml()
