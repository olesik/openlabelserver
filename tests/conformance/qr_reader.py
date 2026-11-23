"""An ISO/IEC 18004 reader for the conformance suite's `RO-108` case.

The suite has to read a rendered symbol back, so this module decodes a
rasterized QR code from its pixels instead of trusting the encoder that made it:
it finds the symbol's bounds, measures the module grid from the three finder
patterns and the timing patterns, reads both copies of the format information
(error-correction level and mask), unmasks the data area, walks the
two-module zigzag and parses the byte-mode segment.

It deliberately shares no table with `renderer/qrcode.py`. It reads versions 1
and 2, which are every version whose codewords form a single Reed-Solomon block
at all four levels (ISO/IEC 18004 Table 9), so it needs no block-interleaving
table; the data-codeword counts below are the standard's, not the encoder's.
A clean raster of a conforming artifact should need no error correction, so the
reader reports what the pixels say rather than repairing them.
"""

from __future__ import annotations

from dataclasses import dataclass

from renderer import assets

# ISO/IEC 18004 Table 9: versions 1 and 2 carry one block per level, so the
# interleaved codeword stream is the data codewords followed by the error ones.
_DATA_CODEWORDS = {
    1: {"L": 19, "M": 16, "Q": 13, "H": 9},
    2: {"L": 34, "M": 28, "Q": 22, "H": 16},
}

_MODULES = {1: 21, 2: 25}
# Alignment pattern centres, except the ones that coincide with a finder.
_ALIGNMENT = {1: (), 2: (18,)}

_FORMAT_MASK = 0b101010000010010
_FORMAT_GENERATOR = 0b10100110111
_LEVEL_BITS = {0b01: "L", 0b00: "M", 0b11: "Q", 0b10: "H"}
BYTE_MODE = 0b0100


class ReaderError(ValueError):
    """A raster the reader cannot read, with the reason named."""


@dataclass(frozen=True)
class Reading:
    """One decoded symbol: what it carries, how it is built, and where it sits."""

    content: str
    version: int
    level: str
    mask: int
    modules: int
    left: float
    top: float
    right: float
    bottom: float


def _dark_rows(picture: assets.Picture) -> list[list[bool]]:
    """The raster as one boolean per pixel, dark where the luma is below half."""

    if picture.kind != "png" or picture.colours != 3 or picture.bits != 8:
        raise ReaderError(
            f"the raster is {picture.kind} {picture.colours}-sample at {picture.bits} bits, "
            "and the reader needs an 8-bit RGB PNG"
        )
    rows = assets.samples(picture)
    stride = picture.width * 3
    dark: list[list[bool]] = []
    for y in range(picture.height):
        row = rows[y * stride : (y + 1) * stride]
        dark.append(
            [
                (299 * row[3 * x] + 587 * row[3 * x + 1] + 114 * row[3 * x + 2]) // 1000 < 128
                for x in range(picture.width)
            ]
        )
    return dark


def _bounds(dark: list[list[bool]]) -> tuple[int, int, int, int]:
    """The smallest rectangle of dark pixels: the symbol, drawn on white."""

    left = top = right = bottom = None
    for y, row in enumerate(dark):
        painted = [x for x, dark_pixel in enumerate(row) if dark_pixel]
        if not painted:
            continue
        top = y if top is None else top
        bottom = y
        left = painted[0] if left is None else min(left, painted[0])
        right = painted[-1] if right is None else max(right, painted[-1])
    if left is None or top is None or right is None or bottom is None:
        raise ReaderError("the raster paints no dark module")
    return left, top, right, bottom


def _grid(
    dark: list[list[bool]], left: int, top: int, module: float, count: int
) -> list[list[bool]]:
    """Sample one module centre per cell of a `count` x `count` grid."""

    height = len(dark)
    width = len(dark[0]) if dark else 0
    grid: list[list[bool]] = []
    for row in range(count):
        y = int(round(top + (row + 0.5) * module))
        line: list[bool] = []
        for column in range(count):
            x = int(round(left + (column + 0.5) * module))
            if not (0 <= y < height and 0 <= x < width):
                raise ReaderError(f"module ({row}, {column}) falls outside the raster")
            line.append(dark[y][x])
        grid.append(line)
    return grid


def _finder(grid: list[list[bool]], top: int, left: int) -> bool:
    """Whether the 7 x 7 finder pattern sits at `(top, left)`."""

    for row in range(7):
        for column in range(7):
            edge = row in (0, 6) or column in (0, 6)
            ring = row in (1, 5) or column in (1, 5)
            if grid[top + row][left + column] != (edge or not ring):
                return False
    return True


def _timing(grid: list[list[bool]]) -> bool:
    """Whether the two timing patterns alternate from row and column 8 inwards."""

    size = len(grid)
    for index in range(8, size - 8):
        if grid[6][index] != (index % 2 == 0):
            return False
        if grid[index][6] != (index % 2 == 0):
            return False
    return True


def _sized(
    dark: list[list[bool]], left: int, top: int, right: int, bottom: int
) -> tuple[int, float, list[list[bool]]]:
    """The module count, module size and grid the painted bounds describe."""

    width, height = right - left + 1, bottom - top + 1
    for version, count in sorted(_MODULES.items()):
        module = width / count
        if abs(height / count - module) > 1.5:
            continue
        try:
            grid = _grid(dark, left, top, module, count)
        except ReaderError:
            continue
        if (
            _finder(grid, 0, 0)
            and _finder(grid, 0, count - 7)
            and _finder(grid, count - 7, 0)
            and _timing(grid)
        ):
            return version, module, grid
    raise ReaderError(
        f"no version 1 or 2 grid fits the painted {width} x {height} px symbol: "
        "the finder or timing patterns do not match"
    )


def _format_value(grid: list[list[bool]]) -> int:
    """The first copy of the 15-bit format information, bit 0 first."""

    positions = [(index, 8) for index in range(6)]
    positions += [(7, 8), (8, 8), (8, 7)]
    positions += [(8, 14 - index) for index in range(9, 15)]
    value = 0
    for bit, (row, column) in enumerate(positions):
        if grid[row][column]:
            value |= 1 << bit
    return value


def _format_copy(grid: list[list[bool]]) -> int:
    """The second copy of the format information, bit 0 first."""

    size = len(grid)
    positions = [(8, size - 1 - index) for index in range(8)]
    positions += [(size - 15 + index, 8) for index in range(8, 15)]
    value = 0
    for bit, (row, column) in enumerate(positions):
        if grid[row][column]:
            value |= 1 << bit
    return value


def _decode_format(value: int, which: str) -> tuple[str, int]:
    """One format-information copy as `(level, mask)`, BCH(15, 5) checked."""

    value ^= _FORMAT_MASK
    data = value >> 10
    remainder = data
    for _ in range(10):
        remainder <<= 1
        if remainder & 0b10000000000:
            remainder ^= _FORMAT_GENERATOR
    if ((data << 10) | remainder) != value:
        raise ReaderError(f"the {which} format information fails its BCH check")
    level = _LEVEL_BITS.get(data >> 3)
    if level is None:
        raise ReaderError(f"the {which} format information names an undefined level")
    return level, data & 0b111


def _reserved(version: int, size: int) -> list[list[bool]]:
    """Every module a codeword does not use: finder, timing, format, alignment."""

    reserved = [[False] * size for _ in range(size)]

    def fill(top: int, left: int, height: int, width: int) -> None:
        for row in range(top, top + height):
            for column in range(left, left + width):
                reserved[row][column] = True

    fill(0, 0, 9, 9)
    fill(0, size - 8, 9, 8)
    fill(size - 8, 0, 8, 9)
    for index in range(size):
        reserved[6][index] = True
        reserved[index][6] = True
    for centre in _ALIGNMENT[version]:
        fill(centre - 2, centre - 2, 5, 5)
    return reserved


def _masked(mask: int, row: int, column: int) -> bool:
    """Whether the mask inverts the module at `(row, column)`."""

    if mask == 0:
        return (row + column) % 2 == 0
    if mask == 1:
        return row % 2 == 0
    if mask == 2:
        return column % 3 == 0
    if mask == 3:
        return (row + column) % 3 == 0
    if mask == 4:
        return (row // 2 + column // 3) % 2 == 0
    if mask == 5:
        return (row * column) % 2 + (row * column) % 3 == 0
    if mask == 6:
        return ((row * column) % 2 + (row * column) % 3) % 2 == 0
    return ((row + column) % 2 + (row * column) % 3) % 2 == 0


def _codeword_bits(grid: list[list[bool]], version: int, mask: int) -> list[bool]:
    """The unmasked data bits, read in the standard's two-module zigzag."""

    size = len(grid)
    reserved = _reserved(version, size)
    bits: list[bool] = []
    column = size - 1
    upward = True
    while column > 0:
        if column == 6:
            column -= 1
        for step in range(size):
            row = size - 1 - step if upward else step
            for offset in (0, 1):
                x = column - offset
                if reserved[row][x]:
                    continue
                bits.append(grid[row][x] != _masked(mask, row, x))
        upward = not upward
        column -= 2
    return bits


def _payload(bits: list[bool], version: int, level: str) -> str:
    """The byte-mode segment of one symbol's data codewords."""

    available = _DATA_CODEWORDS[version][level] * 8
    if len(bits) < available:
        raise ReaderError(f"the symbol holds {len(bits)} data bits of {available}")
    stream = "".join("1" if bit else "0" for bit in bits[:available])
    mode = int(stream[0:4], 2)
    if mode != BYTE_MODE:
        raise ReaderError(f"the symbol starts with mode {mode:04b}, and not byte mode")
    count_width = 8 if version <= 9 else 16
    count = int(stream[4 : 4 + count_width], 2)
    start = 4 + count_width
    if start + count * 8 > available:
        raise ReaderError(
            f"the symbol declares {count} bytes in {available - start} bits of data"
        )
    payload = bytes(
        int(stream[start + 8 * index : start + 8 * index + 8], 2) for index in range(count)
    )
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        raise ReaderError("the symbol's bytes are not UTF-8") from None


def read(picture: assets.Picture) -> Reading:
    """Decode one rasterized QR symbol drawn dark on white."""

    dark = _dark_rows(picture)
    left, top, right, bottom = _bounds(dark)
    version, module, grid = _sized(dark, left, top, right, bottom)
    first = _decode_format(_format_value(grid), "first")
    second = _decode_format(_format_copy(grid), "second")
    if first != second:
        raise ReaderError(
            f"the format copies disagree: {first[0]}-{first[1]} and {second[0]}-{second[1]}"
        )
    level, mask = first
    bits = _codeword_bits(grid, version, mask)
    return Reading(
        content=_payload(bits, version, level),
        version=version,
        level=level,
        mask=mask,
        modules=len(grid),
        left=float(left),
        top=float(top),
        right=float(right + 1),
        bottom=float(bottom + 1),
    )
