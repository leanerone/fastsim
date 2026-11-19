"""SML parser/formatter tests incl. WinSECS dialect (from official WSSML.BAS grammar)."""
import pytest

from fastsim.engine.builtin import sml
from fastsim.engine.builtin.secs2 import Item


class TestBasicParse:
    def test_simple_message(self):
        m = sml.parse("S1F1 W")
        assert m.sf == "S1F1" and m.w_bit and m.body is None

    def test_message_no_w(self):
        m = sml.parse("S1F2")
        assert m.w_bit is False

    def test_named_message(self):
        m = sml.parse("AreYouThere : S1F1 W")
        assert m.name == "AreYouThere" and m.sf == "S1F1"

    def test_nested_list(self):
        m = sml.parse('S7F3 W <L [2] <A "RECIPE1"> <B 0x41 0x42>>')
        assert m.body[0].first() == "RECIPE1"
        assert m.body[1].value == bytes([0x41, 0x42])

    def test_scalar_values(self):
        m = sml.parse("S6F11 W <L [3] <U4 1> <U4 2> <L [0]>>")
        assert m.body[0].first() == 1 and m.body[1].first() == 2

    def test_multiple_numeric_values(self):
        m = sml.parse("S9F5 <L [2] <B 0x01 0x02 0x03> <A \"\">>")
        assert m.body[0].value == bytes([1, 2, 3])

    def test_floats_and_negatives(self):
        m = sml.parse("S2F14 <L [2] <F4 1.5 -2.25> <I4 -100>>")
        assert m.body[0].value == pytest.approx([1.5, -2.25])
        assert m.body[1].value == [-100]

    def test_boolean_keywords(self):
        m = sml.parse("S2F37 W <L [3] <U4 0> <BOOLEAN TRUE> <L [1] <U4 6001>>>")
        assert m.body[1].value == [True]

    def test_comments(self):
        m = sml.parse("S1F1 W /* hello */ <L [0]>  // trailing")
        assert m.body.kind == "L"

    def test_multiline(self):
        text = """S1F13 W
<L [2]
  <A "MDLN">
  <A "1.0">
>."""
        m = sml.parse(text)
        assert m.body[1].first() == "1.0"

    def test_direction(self):
        m = sml.parse("S1F1 W H->E")
        assert m.direction == "H->E"

    def test_length_hint(self):
        m = sml.parse('S1F2 W <L [2] <A [10] "ABC"> <A [10] "DEF">>')
        assert m.body[0].first() == "ABC"


class TestWinSecsDialect:
    def test_transaction_syntax(self):
        tr = sml.try_parse_transaction("hello H->E < S1F1 S1F2 >.")
        assert tr.name == "hello" and tr.direction == "H->E"
        assert tr.messages == ["S1F1", "S1F2"]

    def test_if_transaction(self):
        tr = sml.try_parse_transaction("IF ( S1F1 W ) S1F2.")
        assert tr is None  # classic IF syntax not required for MVP parser

    def test_transaction_not_confused_with_message(self):
        assert sml.try_parse_transaction("S1F1 W") is None


class TestFormat:
    def test_format_parse_roundtrip(self):
        m = sml.parse('S2F41 W <L [2] <A "START"> <L [1] <L [2] <A "RECIPE"> <A "R1">>>>')
        text = m.body.to_sml()
        m2 = sml.parse_item(text)
        assert m2.encode() == m.body.encode()

    def test_unicode_escape(self):
        m = sml.parse('S5F1 W <L [3] <B 0x80> <U4 1> <A "quote \\" inside">>')
        assert m.body[2].first() == 'quote " inside'

    def test_parse_errors(self):
        with pytest.raises(sml.SmlError):
            sml.parse("SxFy")  # bad header
        with pytest.raises(sml.SmlError):
            sml.parse("S1F1 <L [1]")  # unterminated
        with pytest.raises(sml.SmlError):
            sml.parse("S1F1 <X9 1>")  # unknown type
        with pytest.raises(sml.SmlError):
            sml.parse("S1F1 trailing junk")  # trailing token

    def test_parse_item(self):
        it = sml.parse_item('<L [2] <U4 5> <A "Z">>')
        assert it[1].first() == "Z"
