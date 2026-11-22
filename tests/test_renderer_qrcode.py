"""Tests for `renderer/qrcode.py` and the Section 8.2.11 grid it draws.

The pinned matrices come from python-qrcode 8, an independent encoder, at the
mask `renderer/qrcode.py` selects for the same content and level, so a mistake in
the block tables, the Reed-Solomon arithmetic, the placement or the format
information cannot be masked by reading the encoder's own output back. The
penalty rules and the two BCH codes are computed here from their published
definitions rather than from `renderer/qrcode.py`.
"""

from __future__ import annotations

from typing import Any

import pytest

from renderer import output, qrcode
from renderer.plan import Fill

# python-qrcode 8, byte mode, "a12" at H, version 1, mask 5.
_VERSION_1_H = (
    "#######.###.#.#######",
    "#.....#....##.#.....#",
    "#.###.#.#.###.#.###.#",
    "#.###.#..#.##.#.###.#",
    "#.###.#.#.#.#.#.###.#",
    "#.....#..#..#.#.....#",
    "#######.#.#.#.#######",
    "........#..#.........",
    ".....##...#.#.#.#.#.#",
    "..#.#...#####..##.##.",
    "...#######.##..#.##..",
    "##.......###.###..##.",
    "...####.#.#...###..##",
    "........#.##..#...#.#",
    "#######...#####.#..#.",
    "#.....#.#..###....##.",
    "#.###.#.....#...#.#..",
    "#.###.#..#.#...#.#...",
    "#.###.#..##.##.###.##",
    "#.....#..##.##.#.#...",
    "#######...##.###..##.",
)

# python-qrcode 8, byte mode, "https://example.org" at M, version 2, mask 1.
_VERSION_2_M = (
    "#######.#..#.#....#######",
    "#.....#..#..##..#.#.....#",
    "#.###.#.#..#.##...#.###.#",
    "#.###.#..##..###..#.###.#",
    "#.###.#..#...##...#.###.#",
    "#.....#.#######...#.....#",
    "#######.#.#.#.#.#.#######",
    "...........##.###........",
    "#.#...##..#..##.#..#..#.#",
    "#.###..##.####.#.###.#.##",
    "##....###.#....#.#..###.#",
    ".#####..####.#..#..#.#...",
    "...####.#.#.##.##.##....#",
    ".##.##.#.#..#..##.##...##",
    "##.#..##..#.#######..##.#",
    "..#.#...#####.#.##.###...",
    "####.###..#..##.#####..#.",
    "........#.#..##.#...#...#",
    "#######.#..#....#.#.#...#",
    "#.....#..##..#.##...#..##",
    "#.###.#....###.######..##",
    "#.###.#.....#....#..#.##.",
    "#.###.#.##..######.###.##",
    "#.....#....##.#######....",
    "#######.##...##.#.#..#..#",
)


def _matrix(rows: tuple[str, ...]) -> tuple[tuple[bool, ...], ...]:
    return tuple(tuple(module == "#" for module in row) for row in rows)


def document(objects: list[dict[str, Any]], **props: Any) -> dict[str, Any]:
    return {
        "renderspec": "1.0",
        "id": "qrcode_probe",
        "name": "QR Code Probe",
        "page": {"width": 60.0, "height": 30.0},
        "layers": [{"id": "base", "name": "Base", "objects": objects}],
        **props,
    }


def codes(content: str = "https://example.org", **props: Any) -> dict[str, Any]:
    return {
        "id": "code",
        "type": "qrcode",
        "x": 5.0,
        "y": 5.0,
        "content": content,
        "size": 18.0,
        **props,
    }


def extent(fill: Fill) -> tuple[float, float, float, float]:
    """The page-millimetre box one fill covers, as min x, min y, max x, max y."""

    points = [fill.matrix.apply(subpath.start) for subpath in fill.subpaths]
    points += [
        fill.matrix.apply(segment.end) for subpath in fill.subpaths for segment in subpath.segments
    ]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def qrcode_fills(spec: dict[str, Any]) -> list[Fill]:
    """Every fill of the first body: the backdrop, then one per dark run."""

    (page,) = output.display_pages(spec)
    return [op for op in page.bodies[0].ops if isinstance(op, Fill)]


def dark_runs(modules: tuple[tuple[bool, ...], ...]) -> int:
    """How many horizontal runs of dark modules the grid holds."""

    runs = 0
    for row in modules:
        for index, dark in enumerate(row):
            if dark and (index == 0 or not row[index - 1]):
                runs += 1
    return runs


def test_version_1_matches_an_independent_encoder() -> None:
    symbol = qrcode.encode("a12", "H")
    assert (symbol.version, symbol.mask) == (1, 5)
    assert symbol.module_count == 21
    assert symbol.modules == _matrix(_VERSION_1_H)


def test_version_2_matches_an_independent_encoder() -> None:
    symbol = qrcode.encode("https://example.org", "M")
    assert (symbol.version, symbol.mask) == (2, 1)
    assert symbol.module_count == 25
    assert symbol.modules == _matrix(_VERSION_2_M)


def test_every_version_and_level_shares_one_encoding_region() -> None:
    """The data and error codewords of a version fill the same region at every level."""

    for version in range(1, 41):
        totals = set()
        for level in qrcode.LEVELS:
            error, first, first_data, second, second_data = qrcode._BLOCKS[version - 1][level]
            totals.add(
                error * (first + second) + first * first_data + second * second_data
            )
        assert len(totals) == 1, f"version {version} carries {sorted(totals)} codewords per level"
        assert qrcode.raw_modules(version) // 8 == totals.pop()


@pytest.mark.parametrize(
    ("version", "level", "bytes"),
    [
        (1, "L", 17),
        (1, "M", 14),
        (1, "Q", 11),
        (1, "H", 7),
        (10, "L", 271),
        (10, "M", 213),
        (10, "Q", 151),
        (10, "H", 119),
        (40, "L", 2953),
        (40, "M", 2331),
        (40, "Q", 1663),
        (40, "H", 1273),
    ],
)
def test_byte_capacities_match_the_published_table(version: int, level: str, bytes: int) -> None:
    assert qrcode._capacity(version, level) == bytes


def test_the_smallest_version_that_fits_is_chosen() -> None:
    assert qrcode.encode("x" * 14, "M").version == 1
    assert qrcode.encode("x" * 15, "M").version == 2
    assert qrcode.encode("x" * 271, "L").version == 10
    assert qrcode.encode("x" * 272, "L").version == 11


def test_utf8_content_is_measured_in_bytes() -> None:
    assert qrcode.encode("é" * 7, "M").version == 1  # 14 UTF-8 bytes
    assert qrcode.encode("é" * 8, "M").version == 2  # 16 UTF-8 bytes


def test_content_beyond_a_version_40_symbol_is_reported() -> None:
    with pytest.raises(qrcode.QrcodeError, match="version 40-L.*capacity is 2953"):
        qrcode.encode("x" * 2954, "L")


@pytest.mark.parametrize("level", ["X", "m", ""])
def test_an_unknown_error_correction_level_is_reported(level: str) -> None:
    with pytest.raises(qrcode.QrcodeError, match="error_correction"):
        qrcode.encode("x", level)


def _bch(value: int, degree: int, generator: int) -> int:
    """The remainder of `value` shifted by `degree` bits, divided by `generator`."""

    remainder = value << degree
    for shift in range(remainder.bit_length() - 1, degree - 1, -1):
        if remainder & (1 << shift):
            remainder ^= generator << (shift - degree)
    return remainder


def _format_bits(level: str, mask: int) -> int:
    """The 15-bit format information, from the BCH(15, 5) definition."""

    indicator = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}[level]
    value = indicator << 3 | mask
    return ((value << 10) | _bch(value, 10, 0x537)) ^ 0x5412


def _bits(bits: list[bool]) -> int:
    return sum(1 << index for index, bit in enumerate(bits) if bit)


def _format_copies(matrix: tuple[tuple[bool, ...], ...]) -> tuple[int, int]:
    """Both 15-bit format copies, read from the positions the standard fixes."""

    size = len(matrix)
    first = [matrix[index][8] for index in range(6)]
    first += [matrix[7][8], matrix[8][8], matrix[8][7]]
    first += [matrix[8][14 - index] for index in range(9, 15)]
    second = [matrix[8][size - 1 - index] for index in range(8)]
    second += [matrix[size - 15 + index][8] for index in range(8, 15)]
    return _bits(first), _bits(second)


@pytest.mark.parametrize("level", qrcode.LEVELS)
def test_format_information_is_bch_protected_in_both_copies(level: str) -> None:
    symbol = qrcode.encode("https://example.org", level)
    assert _format_copies(symbol.modules) == (
        _format_bits(level, symbol.mask),
        _format_bits(level, symbol.mask),
    )


def test_version_information_repeats_the_version_for_seven_and_up() -> None:
    symbol = qrcode.encode("x" * 110, "M")
    assert symbol.version == 7
    expected = 7 << 12 | _bch(7, 12, 0x1F25)
    size = symbol.module_count
    first = _bits([symbol.modules[index // 3][size - 11 + index % 3] for index in range(18)])
    second = _bits([symbol.modules[size - 11 + index % 3][index // 3] for index in range(18)])
    assert (first, second) == (expected, expected)


def test_the_penalty_counts_its_four_rules() -> None:
    # Six rows of six dark modules: N1 is 12 lines of (3 + 1), N2 is 25 blocks of
    # 3, N4 is the full ten steps from an even balance, and N3 cannot occur.
    assert qrcode._penalty([[True] * 6 for _ in range(6)]) == 48 + 75 + 100

    # One 1:1:3:1:1 row in a light 7 x 7 grid: N1 counts the zero rows and the
    # two all-light columns, N2 the all-light 2 x 2 blocks, N3 the finder ratio
    # in the quiet zone, and N4 the 5-of-49 dark proportion.
    grid = [[False] * 7 for _ in range(7)]
    grid[3] = [True, False, True, True, True, False, True]
    assert qrcode._penalty(grid) == 40 + 72 + 40 + 70


def test_the_pattern_fills_the_declared_box_with_one_rectangle_per_dark_run() -> None:
    encoded = qrcode.encode("https://example.org", "M")
    fills = qrcode_fills(document([codes()]))

    backdrop, *ink = fills
    assert len(ink) == dark_runs(encoded.modules)
    assert backdrop.colour.values == (1.0, 1.0, 1.0)
    assert extent(backdrop) == (5.0, 5.0, 23.0, 23.0)

    module = 18.0 / encoded.module_count
    for fill in ink:
        left, top, right, bottom = extent(fill)
        assert 5.0 - 1e-9 <= left < right <= 23.0 + 1e-9
        assert 5.0 - 1e-9 <= top < bottom <= 23.0 + 1e-9
        # Every rectangle covers whole modules, so its width is a multiple of one.
        assert abs(round((right - left) / module) * module - (right - left)) < 1e-9
        assert abs(round((bottom - top) / module) * module - (bottom - top)) < 1e-9

    covered = [extent(fill) for fill in ink]
    assert min(box[0] for box in covered) == 5.0
    assert min(box[1] for box in covered) == 5.0
    assert max(box[2] for box in covered) == 23.0
    assert max(box[3] for box in covered) == 23.0


def test_a_none_background_leaves_the_backdrop_unpainted() -> None:
    fills = qrcode_fills(document([codes(background_color="none")]))
    assert all(fill.colour.values == (0.0, 0.0, 0.0) for fill in fills)
    assert min(extent(fill)[0] for fill in fills) == 5.0


def test_content_the_symbol_cannot_carry_is_reported_by_output() -> None:
    with pytest.raises(output.OutputError, match="version 40"):
        output.artifact(document([codes(content="x" * 3000, error_correction="H")]))


def test_both_formats_carry_the_qrcode_and_stay_deterministic() -> None:
    spec = document(
        [codes(), codes("a12", id="small", error_correction="H", x=30.0)],
        output={"format": "pdf", "compress": False},
    )
    pdf = output.artifact(spec)
    postscript = output.artifact(spec, format="postscript")
    assert pdf == output.artifact(spec)
    assert postscript == output.artifact(spec, format="postscript")
    assert pdf.startswith(b"%PDF-1.4") and postscript.startswith(b"%!PS-Adobe-3.0")
