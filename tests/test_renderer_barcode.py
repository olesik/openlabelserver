"""Tests for `renderer/barcode.py` and the Section 8.2.10 bars it draws.

The encoders are checked against element widths and parity tables written out
here from the published symbology definitions, so a typo in `renderer/barcode.py`
cannot be masked by reading its own table back.
"""

from __future__ import annotations

from typing import Any

import pytest

from renderer import barcode, output
from renderer.plan import Fill

# Code 128 element widths for the values these tests use.
_W = {
    104: "211214",  # start B
    33: "111323",  # "A"
    34: "131123",  # "B"
    102: "411131",  # the check character for "AB"
    106: "2331112",  # stop
}


def _bits(pattern: str) -> str:
    bar, digits = True, []
    for width in pattern:
        digits.append(("1" if bar else "0") * int(width))
        bar = not bar
    return "".join(digits)


def _code128_bits(content: str) -> str:
    """The expected symbol for subset B content, element widths written out above."""

    values = [ord(character) - 0x20 for character in content]
    checksum = (104 + sum(value * position for position, value in enumerate(values, 1))) % 103
    patterns = [_W[104], *(_W[value] for value in values), _W[checksum], _W[106]]
    return "".join(_bits(pattern) for pattern in patterns)


def _modules(bits: str) -> tuple[bool, ...]:
    return tuple(bit == "1" for bit in bits)


def document(objects: list[dict[str, Any]], **props: Any) -> dict[str, Any]:
    return {
        "renderspec": "1.0",
        "id": "barcode_probe",
        "name": "Barcode Probe",
        "page": {"width": 60.0, "height": 30.0},
        "layers": [{"id": "base", "name": "Base", "objects": objects}],
        **props,
    }


def codes(content: str = "ABC-123", **props: Any) -> dict[str, Any]:
    return {
        "id": "code",
        "type": "barcode",
        "x": 5.0,
        "y": 5.0,
        "content": content,
        "symbology": "code128",
        "width": 42.0,
        "height": 12.0,
        "draw_text": False,
        **props,
    }


def extent(fill: Fill) -> tuple[float, float, float, float]:
    """The page-millimetre box one fill covers, as min x, min y, max x, max y."""

    points = [fill.matrix.apply(subpath.start) for subpath in fill.subpaths]
    points += [fill.matrix.apply(segment.end) for subpath in fill.subpaths for segment in subpath.segments]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def barcode_fills(spec: dict[str, Any]) -> list[Fill]:
    """Every fill of the first body: the backdrop, then one per bar run."""

    (page,) = output.display_pages(spec)
    return [op for op in page.bodies[0].ops if isinstance(op, Fill)]


def test_code128_encodes_a_known_symbol() -> None:
    assert barcode.symbol("code128", "A").modules == _modules(_code128_bits("A"))
    assert len(barcode.symbol("code128", "A").modules) == 46


def test_code128_uses_the_modulo_103_check_character() -> None:
    expected = _code128_bits("AB")
    assert barcode.symbol("code128", "AB").modules == _modules(expected)
    assert len(barcode.symbol("code128", "ABC-123").modules) == 11 * 9 + 13


@pytest.mark.parametrize("content", ["", "caf\u00e9", "line\nbreak"])
def test_code128_reports_content_outside_subset_b(content: str) -> None:
    with pytest.raises(barcode.BarcodeError, match="code128"):
        barcode.symbol("code128", content)


@pytest.mark.parametrize(
    ("content", "digits"),
    [
        ("4006381333931", "4006381333931"),
        ("400638133393", "4006381333931"),
        (" 5901234123457 ", "5901234123457"),
    ],
)
def test_ean13_accepts_twelve_digits_and_verifies_thirteen(content: str, digits: str) -> None:
    assert barcode.symbol("ean13", content).content == digits


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("4006381333930", "check digit"),
        ("40063813339", "twelve or thirteen"),
        ("40063813339311", "twelve or thirteen"),
        ("400638133393X", "not all digits"),
    ],
)
def test_ean13_reports_payloads_it_cannot_encode(content: str, message: str) -> None:
    with pytest.raises(barcode.BarcodeError, match=message):
        barcode.symbol("ean13", content)


def test_ean13_emits_the_95_module_symbol() -> None:
    symbol = barcode.symbol("ean13", "4006381333931")
    bits = "".join("1" if module else "0" for module in symbol.modules)
    assert len(bits) == 95
    assert bits[:3] == "101" and bits[45:50] == "01010" and bits[-3:] == "101"
    # The first digit 4 selects L, G, L, L, G, G for the six left digits 0,0,6,3,8,1.
    assert bits[3:10] == "0001101"  # L(0)
    assert bits[10:17] == "0100111"  # G(0)
    assert bits[17:24] == "0101111"  # L(6)
    assert bits[24:31] == "0111101"  # L(3)
    assert bits[31:38] == "0001001"  # G(8)
    assert bits[38:45] == "0110011"  # G(1)


@pytest.mark.parametrize("symbology", ["pdf417", "aztec"])
def test_an_unimplemented_symbology_is_reported(symbology: str) -> None:
    with pytest.raises(barcode.BarcodeError, match="not implemented"):
        barcode.symbol(symbology, "123")


def test_the_pattern_fills_the_declared_box_with_one_rectangle_per_bar_run() -> None:
    modules = barcode.symbol("code128", "ABC-123").modules
    runs = sum(
        1 for index, module in enumerate(modules) if module and (index == 0 or not modules[index - 1])
    )
    fills = barcode_fills(document([codes()]))

    backdrop, *ink = fills
    assert len(ink) == runs
    assert backdrop.colour.values == (1.0, 1.0, 1.0)
    assert extent(backdrop) == (5.0, 5.0, 47.0, 17.0)

    for fill in ink:
        left, top, right, bottom = extent(fill)
        assert (top, bottom) == (5.0, 17.0)
        assert 5.0 <= left < right <= 47.0
    assert min(extent(fill)[0] for fill in ink) == 5.0
    assert max(extent(fill)[2] for fill in ink) == 47.0


def test_a_none_background_leaves_the_backdrop_unpainted() -> None:
    fills = barcode_fills(document([codes(background_color="none")]))
    assert all(fill.colour.values == (0.0, 0.0, 0.0) for fill in fills)
    assert min(extent(fill)[0] for fill in fills) == 5.0


def test_draw_text_true_is_reported() -> None:
    spec = document([codes(draw_text=True)])
    with pytest.raises(output.OutputError, match="draw_text"):
        output.artifact(spec)


def test_an_unimplemented_symbology_and_bad_content_are_reported_by_output() -> None:
    with pytest.raises(output.OutputError, match="not implemented"):
        output.artifact(document([codes(symbology="pdf417")]))
    with pytest.raises(output.OutputError, match="check digit"):
        output.artifact(document([codes(content="4006381333930", symbology="ean13")]))


def test_both_formats_carry_the_barcode_and_stay_deterministic() -> None:
    spec = document([codes(), codes("4006381333931", id="ean", symbology="ean13", y=20.0)],
                    output={"format": "pdf", "compress": False})
    pdf = output.artifact(spec)
    postscript = output.artifact(spec, format="postscript")
    assert pdf == output.artifact(spec)
    assert postscript == output.artifact(spec, format="postscript")
    assert pdf.startswith(b"%PDF-1.4") and postscript.startswith(b"%!PS-Adobe-3.0")
    # Both symbols reach the page: the EAN-13's last bar ends at x = 5 + 33 mm.
    assert b"38" in pdf


_CODE39_GUARD = "100010111011101"


def printed(symbol: barcode.Symbol) -> str:
    """The module string a symbol prints, `1` for a bar and `0` for a space."""

    return "".join("1" if module else "0" for module in symbol.modules)


def test_code39_frames_one_character_with_its_star_guards() -> None:
    assert printed(barcode.symbol("code39", "A")) == (
        _CODE39_GUARD + "0" + "111010100010111" + "0" + _CODE39_GUARD
    )


def test_code39_prints_its_whole_alphabet() -> None:
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-. $/+%"
    assert len(alphabet) == 43
    for character in alphabet:
        symbol = barcode.symbol("code39", character)
        # A guard, one narrow space, the character, one narrow space and a guard.
        assert len(symbol.modules) == 47
        assert printed(symbol)[:15] == _CODE39_GUARD


@pytest.mark.parametrize("content", ["", "ab", "A*B", "caf\u00e9"])
def test_code39_reports_content_outside_its_alphabet(content: str) -> None:
    with pytest.raises(barcode.BarcodeError, match="code39"):
        barcode.symbol("code39", content)


def test_itf_interleaves_a_pair_of_digits() -> None:
    assert printed(barcode.symbol("itf", " 1234 ")) == (
        "1010"  # start: narrow bar, narrow space, narrow bar, narrow space
        "111010001010111000"  # 1 as bars and 2 as spaces
        "111011101000101000"  # 3 as bars and 4 as spaces
        "11101"  # stop: wide bar, narrow space, narrow bar
    )
    assert barcode.symbol("itf", " 1234 ").content == "1234"


@pytest.mark.parametrize(
    ("content", "message"),
    [("", "empty"), ("123", "even count"), ("12a4", "not all digits")],
)
def test_itf_reports_content_it_cannot_encode(content: str, message: str) -> None:
    with pytest.raises(barcode.BarcodeError, match=message):
        barcode.symbol("itf", content)


def test_codabar_prints_the_start_and_stop_characters_its_content_names() -> None:
    assert printed(barcode.symbol("codabar", "a12b")) == (
        "1011100010001"  # A
        "0"  # the narrow space between characters
        "10101110001"  # 1
        "0"
        "10100010111"  # 2
        "0"
        "1000100010111"  # B
    )
    assert barcode.symbol("codabar", " a12b ").content == "A12B"


@pytest.mark.parametrize(
    ("content", "message"),
    [("AA", "start and a stop"), ("1234", "start or stop"), ("A*B", "cannot encode")],
)
def test_codabar_reports_content_it_cannot_encode(content: str, message: str) -> None:
    with pytest.raises(barcode.BarcodeError, match=message):
        barcode.symbol("codabar", content)


def test_ean8_emits_the_67_module_symbol() -> None:
    symbol = barcode.symbol("ean8", "9638507")
    assert symbol.content == "96385074"
    assert printed(symbol) == (
        "101"  # start guard
        "0001011" "0101111" "0111101" "0110111"  # 9, 6, 3 and 8, left odd
        "01010"  # centre guard
        "1001110" "1110010" "1000100" "1011100"  # 5, 0, 7 and 4, right
        "101"  # end guard
    )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("96385070", "check digit"),
        ("963850", "seven or eight"),
        ("963850744", "seven or eight"),
        ("9638507X", "not all digits"),
    ],
)
def test_ean8_reports_payloads_it_cannot_encode(content: str, message: str) -> None:
    with pytest.raises(barcode.BarcodeError, match=message):
        barcode.symbol("ean8", content)


def test_upca_emits_the_95_module_symbol() -> None:
    symbol = barcode.symbol("upca", "036000291452")
    assert symbol.content == "036000291452"
    assert printed(symbol) == (
        "101"  # start guard
        "0001101" "0111101" "0101111" "0001101" "0001101" "0001101"  # 0 3 6 0 0 0
        "01010"  # centre guard
        "1101100" "1110100" "1100110" "1011100" "1001110" "1101100"  # 2 9 1 4 5 2
        "101"  # end guard
    )
    # UPC-A is EAN-13 with a leading zero, so both symbols are the same 95 modules.
    assert symbol.modules == barcode.symbol("ean13", "0036000291452").modules


def test_upce_derives_the_number_system_and_check_digit() -> None:
    symbol = barcode.symbol("upce", "123456")
    assert symbol.content == "01234565"
    assert printed(symbol) == (
        "101"  # start guard
        "0110011"  # 1, even parity
        "0010011"  # 2, odd
        "0111101"  # 3, odd
        "0011101"  # 4, even
        "0111001"  # 5, even
        "0101111"  # 6, odd
        "010101"  # end guard
    )


def test_upce_accepts_its_number_system_and_check_digit() -> None:
    assert barcode.symbol("upce", "0123456").content == "01234565"
    assert barcode.symbol("upce", "01234565").modules == barcode.symbol("upce", "123456").modules
    # 654321 expands to UPC-A 065100004327, whose check digit 7 selects E O E O E O.
    assert barcode.symbol("upce", "654321").content == "06543217"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("12345", "six, seven or eight"),
        ("1123456", "number system 0"),
        ("01234564", "check digit"),
        ("12345X", "not all digits"),
    ],
)
def test_upce_reports_payloads_it_cannot_encode(content: str, message: str) -> None:
    with pytest.raises(barcode.BarcodeError, match=message):
        barcode.symbol("upce", content)


@pytest.mark.parametrize(
    ("symbology", "content", "modules"),
    [
        ("code39", "ABC-123", 143),
        ("ean8", "9638507", 67),
        ("upca", "036000291452", 95),
        ("upce", "123456", 51),
        ("itf", "12345678", 81),
        ("codabar", "A1234B", 75),
    ],
)
def test_every_supported_symbology_draws_inside_the_declared_box(
    symbology: str, content: str, modules: int
) -> None:
    encoded = barcode.symbol(symbology, content)
    assert encoded.module_count == modules
    runs = sum(
        1
        for index, module in enumerate(encoded.modules)
        if module and (index == 0 or not encoded.modules[index - 1])
    )
    backdrop, *ink = barcode_fills(document([codes(content, symbology=symbology)]))
    assert len(ink) == runs
    assert extent(backdrop) == (5.0, 5.0, 47.0, 17.0)
    left = min(extent(fill)[0] for fill in ink)
    right = max(extent(fill)[2] for fill in ink)
    assert (left, right) == (5.0, 47.0)
