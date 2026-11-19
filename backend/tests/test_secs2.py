"""SECS-II codec full coverage tests."""
import sys

import pytest

from fastsim.engine.builtin.secs2 import Item, SecsError, kind_of


class TestScalarRoundtrip:
    def test_u_kinds(self):
        for kind, vals in [("U1", [0, 255]), ("U2", [0, 65535]), ("U4", [0, 4294967295]),
                           ("U8", [0, 18446744073709551615])]:
            it = Item.from_value(kind, vals)
            back = Item.decode_full(it.encode())
            assert back.kind == kind and back.value == vals

    def test_i_kinds(self):
        for kind, vals in [("I1", [-128, 127]), ("I2", [-32768, 32767]),
                           ("I4", [-2147483648, 2147483647]),
                           ("I8", [-9223372036854775808, 9223372036854775807])]:
            it = Item.from_value(kind, vals)
            back = Item.decode_full(it.encode())
            assert back.value == vals

    def test_floats(self):
        it = Item.from_value("F4", [1.5, -2.25, 0.0])
        back = Item.decode_full(it.encode())
        assert back.value == pytest.approx([1.5, -2.25, 0.0])
        it8 = Item.from_value("F8", [3.141592653589793])
        back8 = Item.decode_full(it8.encode())
        assert back8.value[0] == pytest.approx(3.141592653589793)

    def test_ascii(self):
        it = Item.from_value("A", "HELLO WORLD")
        back = Item.decode_full(it.encode())
        assert back.first() == "HELLO WORLD"

    def test_ascii_chinese_replaced(self):
        it = Item.from_value("A", "晶圆")
        assert it.encode()  # replacement chars, no crash

    def test_binary(self):
        it = Item.from_value("B", [0x00, 0xFF, 0x80])
        back = Item.decode_full(it.encode())
        assert back.value == bytes([0x00, 0xFF, 0x80])

    def test_boolean(self):
        it = Item.from_value("BOOLEAN", [True, False, True])
        back = Item.decode_full(it.encode())
        assert back.value == [True, False, True]

    def test_empty_items(self):
        for kind in ("A", "B", "U4", "BOOLEAN"):
            it = Item.from_value(kind, [])
            back = Item.decode_full(it.encode())
            assert len(back.value) == 0


class TestLists:
    def test_nested(self):
        it = Item.L([
            Item.from_value("U4", 1),
            Item.L([Item.from_value("A", "X"), Item.L([])]),
            Item.from_value("B", [1, 2, 3]),
        ])
        back = Item.decode_full(it.encode())
        assert back.kind == "L" and len(back) == 3
        assert back[1][0].first() == "X"
        assert len(back[1][1]) == 0

    def test_big_list_needs_2_length_bytes(self):
        it = Item.L([Item.L([]) for _ in range(300)])
        raw = it.encode()
        assert raw[0] == 0x02  # format L + 2 length bytes
        back = Item.decode_full(raw)
        assert len(back) == 300

    def test_empty_list(self):
        it = Item.L([])
        raw = it.encode()
        assert raw == bytes([0x01, 0x00])
        back = Item.decode_full(raw)
        assert back.kind == "L" and len(back) == 0


class TestErrors:
    def test_truncated(self):
        with pytest.raises(SecsError):
            Item.decode_full(b"\x41\x05AB")  # claims 5 bytes, gives 2

    def test_bad_length_count(self):
        with pytest.raises(SecsError):
            Item.decode_full(b"\x40")  # A with n=0 length-byte count

    def test_unknown_kind(self):
        with pytest.raises(SecsError):
            Item("X9")

    def test_trailing_bytes(self):
        with pytest.raises(SecsError):
            Item.decode_full(Item.from_value("U4", 1).encode() + b"\x00")


class TestDictConversion:
    def test_roundtrip(self):
        it = Item.L([Item.from_value("U4", 42), Item.from_value("A", "S"),
                     Item.L([Item.from_value("BOOLEAN", [True])])])
        d = it.to_dict()
        back = Item.from_dict(d)
        assert back.encode() == it.encode()

    def test_kind_of(self):
        assert kind_of(True) == "BOOLEAN"
        assert kind_of(5) == "U4"
        assert kind_of(1.5) == "F8"
        assert kind_of("s") == "A"
        assert kind_of([]) == "L"


class TestSmlRender:
    def test_render_parse_roundtrip(self):
        it = Item.L([Item.from_value("A", "T"), Item.from_value("U4", [1, 2]),
                     Item.from_value("B", [0xFF])])
        text = it.to_sml()
        from fastsim.engine.builtin import sml
        back = sml.parse_item(text)
        assert back.encode() == it.encode()
