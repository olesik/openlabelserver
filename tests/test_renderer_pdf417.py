"""Tests for `renderer/pdf417.py` and the rows it draws.

The encoder is checked against the byte-compaction, error-correction and row
indicator rules written out here from the published PDF417 definition, against a
three-row symbol pinned from an independent implementation, and against the
structural invariants of its 3 x 929 pattern table, so a typo in
`renderer/pdf417.py` cannot be masked by reading its own table back.
"""

from __future__ import annotations

from typing import Any

import pytest

from renderer import barcode, output, pdf417
from renderer.pdf417_tables import PATTERNS
from renderer.plan import Fill

# The published start and stop patterns, which frame every row.
_START = "11111111010101000"
_STOP = "111111101000101001"

# A three-row symbol: "a" (two byte-mode codewords) in a box wide enough to fit
# the symbol in three of its four columns.
_PINNED_THREE_ROWS = (
    "111111110101010001110101011100000011110101001111000100000100001000101101000111001111"
    "01000011000110010011101010011100000111111101000101001",
    "111111110101010001111010100001000010100011111101110100011111010111001111101101001000"
    "01111010011100111011111010101100000111111101000101001",
    "111111110101010001101010011111000010011111001100100100001110010110001000011101000110"
    "01011110010000100010101000011110000111111101000101001",
)


def bits(value: int, width: int = 17) -> str:
    """One pattern as a module string, most significant bit first."""

    return "".join(str(value >> shift & 1) for shift in range(width - 1, -1, -1))


def printed(symbol: pdf417.Symbol) -> list[str]:
    """The module string of every row."""

    return ["".join("1" if module else "0" for module in row) for row in symbol.modules]


def elements(line: str) -> list[int]:
    """The width of each bar and space in one module string."""

    widths: list[int] = []
    current = ""
    for module in line:
        if module == current:
            widths[-1] += 1
        else:
            widths.append(1)
            current = module
    return widths


def document(objects: list[dict[str, Any]], **props: Any) -> dict[str, Any]:
    return {
        "renderspec": "1.0",
        "id": "pdf417_probe",
        "name": "PDF417 Probe",
        "page": {"width": 60.0, "height": 30.0},
        "layers": [{"id": "base", "name": "Base", "objects": objects}],
        **props,
    }


def codes(content: str = "PDF417", **props: Any) -> dict[str, Any]:
    return {
        "id": "stacked",
        "type": "barcode",
        "x": 5.0,
        "y": 5.0,
        "content": content,
        "symbology": "pdf417",
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


def symbol_fills(spec: dict[str, Any]) -> list[Fill]:
    """Every fill of the first body: the backdrop, then one per run of bars."""

    (page,) = output.display_pages(spec)
    return [op for op in page.bodies[0].ops if isinstance(op, Fill)]


def runs(modules: tuple[bool, ...]) -> int:
    """How many runs of dark modules one row prints."""

    return sum(
        1
        for index, module in enumerate(modules)
        if module and (index == 0 or not modules[index - 1])
    )


def test_byte_compaction_keeps_whole_six_byte_groups_together() -> None:
    # "PDF417" is six bytes: the 924 latch, then five codewords of base 900.
    assert pdf417.encode("PDF417", 42.0, 12.0).codewords[:8] == (
        8,
        924,
        134,
        461,
        860,
        248,
        599,
        900,
    )
    # "abcdefg" is seven: the 901 latch, one codeword group and the trailing byte.
    assert pdf417.encode("abcdefg", 42.0, 12.0).codewords[:8] == (
        8,
        901,
        163,
        179,
        507,
        603,
        522,
        103,
    )


def test_content_is_encoded_as_utf8_bytes() -> None:
    symbol = pdf417.encode("ééé", 42.0, 12.0)
    value = int.from_bytes("ééé".encode("utf-8"), "big")
    assert len("ééé".encode("utf-8")) == 6
    assert symbol.codewords[1] == 924
    assert symbol.codewords[2:7] == tuple(value // 900**power % 900 for power in (4, 3, 2, 1, 0))


def test_error_correction_is_level_2_over_the_published_generator() -> None:
    # Eight codewords of Reed-Solomon over GF(929) for the data region above.
    assert pdf417.encode("abcdefg", 42.0, 12.0).codewords[8:] == (
        798,
        363,
        596,
        556,
        682,
        774,
        300,
        147,
    )
    assert pdf417.encode("abc", 42.0, 12.0).level == 2


def test_a_three_row_symbol_matches_its_pinned_rows() -> None:
    symbol = pdf417.encode("a", 15.0, 1.0)
    assert (symbol.columns, symbol.rows, symbol.level) == (4, 3, 2)
    assert symbol.codewords == (4, 901, 97, 900, 161, 919, 268, 95, 837, 789, 774, 566)
    assert tuple(printed(symbol)) == _PINNED_THREE_ROWS


def test_row_indicators_carry_the_row_the_counts_and_the_level() -> None:
    symbol = pdf417.encode("a", 15.0, 1.0)
    # Row, then the row count in one indicator and the column count in the other,
    # alternating by cluster; the level rides in the cluster 1 and 2 positions.
    expected = {
        (0, "left"): 0,
        (0, "right"): 3,
        (1, "left"): 8,
        (1, "right"): 0,
        (2, "left"): 3,
        (2, "right"): 8,
    }
    for row, line in enumerate(printed(symbol)):
        cluster = row % 3
        assert line[:17] == _START
        assert line[-18:] == _STOP
        assert line[17:34] == bits(PATTERNS[cluster][expected[(row, "left")]])
        assert line[102:119] == bits(PATTERNS[cluster][expected[(row, "right")]])


def test_the_symbol_is_as_wide_as_its_codewords_and_indicators() -> None:
    symbol = pdf417.encode("PDF417", 42.0, 12.0)
    assert symbol.module_count == 17 * (symbol.columns + 4) + 1
    assert len(symbol.codewords) == symbol.columns * symbol.rows
    # The first data codeword counts the data region, itself included, without EC.
    assert symbol.codewords[0] == symbol.columns * symbol.rows - 8


@pytest.mark.parametrize(
    ("box", "columns", "rows"),
    [((42.0, 12.0), 2, 8), ((12.0, 42.0), 1, 15), ((30.0, 15.0), 1, 15)],
)
def test_columns_follow_the_declared_box(box: tuple[float, float], columns: int, rows: int) -> None:
    symbol = pdf417.encode("PDF417", box[0], box[1])
    assert (symbol.columns, symbol.rows) == (columns, rows)


def test_the_pattern_table_is_three_clusters_of_unique_seventeen_module_patterns() -> None:
    assert len(PATTERNS) == 3
    assert [len(cluster) for cluster in PATTERNS] == [929, 929, 929]
    assert len({value for cluster in PATTERNS for value in cluster}) == 2787
    for cluster in PATTERNS:
        for value in cluster:
            line = bits(value)
            widths = elements(line)
            assert len(line) == 17
            assert line[0] == "1" and line[-1] == "0"
            # Four bars and four spaces: eight elements, none wider than six modules.
            assert len(widths) == 8
            assert sum(widths) == 17
            assert max(widths) <= 6


@pytest.mark.parametrize(("content", "message"), [("", "empty"), ("x" * 1200, "at most 928")])
def test_content_the_symbol_cannot_hold_is_reported(content: str, message: str) -> None:
    with pytest.raises(pdf417.Pdf417Error, match=message):
        pdf417.encode(content, 100.0, 50.0)


def test_the_symbol_fills_the_declared_box_with_one_rectangle_per_run() -> None:
    encoded = pdf417.encode("PDF417", 42.0, 12.0)
    bars = sum(runs(row) for row in encoded.modules)
    fills = symbol_fills(document([codes()]))

    backdrop, *ink = fills
    assert len(ink) == bars
    assert extent(backdrop) == (5.0, 5.0, 47.0, 17.0)
    for fill in ink:
        left, top, right, bottom = extent(fill)
        assert 5.0 <= left < right <= 47.0
        assert 5.0 <= top < bottom <= 17.0
    assert min(extent(fill)[0] for fill in ink) == 5.0
    assert max(extent(fill)[2] for fill in ink) == 47.0
    assert min(extent(fill)[1] for fill in ink) == 5.0
    assert max(extent(fill)[3] for fill in ink) == 17.0


def test_a_none_background_leaves_the_backdrop_unpainted() -> None:
    fills = symbol_fills(document([codes(background_color="none")]))
    assert all(fill.colour.values == (0.0, 0.0, 0.0) for fill in fills)
    assert min(extent(fill)[0] for fill in fills) == 5.0


def test_draw_text_true_is_still_reported_for_pdf417() -> None:
    with pytest.raises(output.OutputError, match="pdf417 caption"):
        output.artifact(document([codes(draw_text=True)]))


def test_both_formats_carry_the_symbol_and_stay_deterministic() -> None:
    spec = document([codes()], output={"format": "pdf", "compress": False})
    pdf = output.artifact(spec)
    postscript = output.artifact(spec, format="postscript")
    assert pdf == output.artifact(spec)
    assert postscript == output.artifact(spec, format="postscript")
    assert pdf.startswith(b"%PDF-1.4") and postscript.startswith(b"%!PS-Adobe-3.0")


def test_the_linear_encoder_reports_pdf417_as_stacked() -> None:
    with pytest.raises(barcode.BarcodeError, match="renderer.pdf417"):
        barcode.symbol("pdf417", "123")
