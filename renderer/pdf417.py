"""PDF417 (ISO/IEC 15438) encoding for the Section 8.2.10 `barcode` object.

PDF417 is a stacked symbol, not one row of modules: `content` is compacted into
codewords, protected by Reed-Solomon codewords over GF(929), framed by a row
indicator at each end of every row, and split into rows of equal length.
`renderer.output` paints each row's dark runs as rectangles, so this module
answers only what the symbol is: its codewords and its module rows.

The encoding is deterministic and deliberately narrow:

* `content` is encoded as UTF-8 in byte compaction mode only — the 924 latch when
  the byte count is a multiple of six and the 901 latch otherwise, six bytes to
  five codewords by a base-256 to base-900 conversion, and any trailing bytes as
  one codeword each — so every string RenderSpec accepts is encodable without a
  compaction planner choosing between modes.
* Error correction is level 2, eight codewords, because Section 8.2.10 exposes no
  property for the level. Its generator polynomial is
  `product(x - 3**i for i in 1..8)` over GF(929), with 3 the primitive element the
  standard uses, computed here instead of tabulated.
* The column count is not a RenderSpec property either: it is the count in 1-30
  whose rows, printed at the standard's minimum height of three modules, shape the
  symbol closest to the declared `width` and `height`, with ties going to fewer
  columns.

Content that needs more than the 928 codewords a symbol holds, empty content and a
symbol that cannot be split into 3-90 rows are reported rather than truncated.
The caption `draw_text` asks for is outside this module: RenderSpec does not
define its face, size or position, so `renderer.output` reports it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from renderer.pdf417_tables import PATTERNS

# The start and stop patterns frame every row; the stop pattern is one module
# wider than the others.
_START = 0x1FEA8
_STOP = 0x3FA29

# Compaction modes and the codeword that fills a row's unused data region.
_BYTE_LATCH = 901
_BYTE_LATCH_MODE = 924
_PAD = 900

# Error correction level 2, and the symbol limits of ISO/IEC 15438 Table 2.
_LEVEL = 2
_EC_COUNT = 1 << (_LEVEL + 1)
_MAX_CODEWORDS = 928
_MAX_COLUMNS = 30
_MIN_ROWS = 3
_MAX_ROWS = 90

# The minimum height of a row, as a multiple of the module width, and the finite
# field the error correction works in.
_ROW_HEIGHT = 3
_MODULUS = 929


class Pdf417Error(ValueError):
    """Content PDF417 cannot carry, with the reason and the limit named."""


@dataclass(frozen=True)
class Symbol:
    """One encoded PDF417 symbol: its codewords and its module rows.

    `modules` holds one tuple per row, `True` where the row prints a bar. Every
    row is the same width, so `module_count` is the symbol's width in modules and
    `row_count` its height in rows. `codewords` is the data region followed by
    the error-correction codewords, `columns` words per row, as printed.
    """

    content: str
    columns: int
    rows: int
    level: int
    codewords: tuple[int, ...]
    modules: tuple[tuple[bool, ...], ...]

    @property
    def module_count(self) -> int:
        """How many modules wide one row prints."""

        return len(self.modules[0])

    @property
    def row_count(self) -> int:
        """How many rows the symbol stacks."""

        return len(self.modules)


def _base900(value: int) -> list[int]:
    """Five codewords, most significant first, for one 48-bit group of six bytes."""

    words: list[int] = []
    for power in range(4, -1, -1):
        words.append(value // 900**power % 900)
    return words


def _byte_words(data: bytes) -> tuple[int, ...]:
    """Compact `data` in byte mode: one latch, five codewords per six bytes."""

    latch = _BYTE_LATCH_MODE if len(data) % 6 == 0 else _BYTE_LATCH
    words: list[int] = [latch]
    whole = len(data) - len(data) % 6
    for start in range(0, whole, 6):
        words += _base900(int.from_bytes(data[start : start + 6], "big"))
    words += data[whole:]
    return tuple(words)


def _choose_columns(needed: int, width: float, height: float) -> int:
    """The column count whose three-module rows shape the symbol closest to the box."""

    ratio = width / height if width > 0.0 and height > 0.0 else float(_ROW_HEIGHT)
    best: tuple[float, int] | None = None
    for columns in range(1, _MAX_COLUMNS + 1):
        rows = max(_MIN_ROWS, math.ceil(needed / columns))
        if rows > _MAX_ROWS:
            continue
        aspect = (17 * (columns + 4) + 1) / (rows * _ROW_HEIGHT)
        score = abs(aspect - ratio)
        if best is None or score < best[0]:
            best = (score, columns)
    if best is None:
        raise Pdf417Error(
            f"pdf417 content needs {needed} codewords, which no {_MAX_COLUMNS}-column, "
            f"{_MAX_ROWS}-row symbol can hold"
        )
    return best[1]


def _generator(count: int) -> list[int]:
    """`product(x - 3**i for i in 1..count)` over GF(929), ascending, monic last."""

    polynomial = [1]
    for power in range(1, count + 1):
        root = pow(3, power, _MODULUS)
        shifted = [0] * (len(polynomial) + 1)
        for index, coefficient in enumerate(polynomial):
            shifted[index] = (shifted[index] - root * coefficient) % _MODULUS
            shifted[index + 1] = (shifted[index + 1] + coefficient) % _MODULUS
        polynomial = shifted
    return polynomial


def _error_correction(words: tuple[int, ...], count: int) -> tuple[int, ...]:
    """The `count` Reed-Solomon codewords the data region requires."""

    generator = _generator(count)
    register = [0] * count
    for word in words:
        factor = (word + register[-1]) % _MODULUS
        for index in range(count - 1, 0, -1):
            register[index] = (register[index - 1] - factor * generator[index]) % _MODULUS
        register[0] = (-factor * generator[0]) % _MODULUS
    return tuple((-value) % _MODULUS for value in reversed(register))


def _indicator(row: int, rows: int, columns: int, left: bool) -> int:
    """The row indicator codeword: row number, row count, column count and level."""

    cluster = row % 3
    if cluster == 0:
        extra = (rows - 1) // 3 if left else columns - 1
    elif cluster == 1:
        extra = _LEVEL * 3 + (rows - 1) % 3 if left else (rows - 1) // 3
    else:
        extra = columns - 1 if left else _LEVEL * 3 + (rows - 1) % 3
    return 30 * (row // 3) + extra


def _bits(value: int, width: int) -> tuple[bool, ...]:
    """One pattern as modules, most significant bit first."""

    return tuple(bool(value >> shift & 1) for shift in range(width - 1, -1, -1))


def _symbol_rows(
    codewords: tuple[int, ...], columns: int, rows: int
) -> tuple[tuple[bool, ...], ...]:
    """Frame every row with its indicators and the start and stop patterns."""

    modules: list[tuple[bool, ...]] = []
    for row in range(rows):
        cluster = row % 3
        values = [
            _indicator(row, rows, columns, left=True),
            *codewords[row * columns : (row + 1) * columns],
            _indicator(row, rows, columns, left=False),
        ]
        line = list(_bits(_START, 17))
        for value in values:
            line += _bits(PATTERNS[cluster][value], 17)
        line += _bits(_STOP, 18)
        modules.append(tuple(line))
    return tuple(modules)


def encode(content: str, width: float, height: float) -> Symbol:
    """Encode one Section 8.2.10 `pdf417` barcode within its declared millimetres."""

    data = content.encode("utf-8")
    if not data:
        raise Pdf417Error("pdf417 content is empty")
    payload = _byte_words(data)
    needed = len(payload) + 1 + _EC_COUNT
    if needed > _MAX_CODEWORDS:
        raise Pdf417Error(
            f"pdf417 content {len(data)} bytes needs {needed} data and error-correction "
            f"codewords; a symbol holds at most {_MAX_CODEWORDS}"
        )

    columns = _choose_columns(needed, width, height)
    rows = max(_MIN_ROWS, math.ceil(needed / columns))
    data_count = rows * columns - _EC_COUNT
    words = (data_count, *payload, *([_PAD] * (data_count - len(payload) - 1)))
    codewords = words + _error_correction(words, _EC_COUNT)
    return Symbol(
        content=content,
        columns=columns,
        rows=rows,
        level=_LEVEL,
        codewords=codewords,
        modules=_symbol_rows(codewords, columns, rows),
    )
