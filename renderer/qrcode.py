"""QR Code Model 2 encoding for the Section 8.2.11 `qrcode` object.

`renderer.output` turns a `qrcode` into the dark modules of one symbol, so this
module answers only what the symbol is: the square matrix a piece of content
prints as, and the declared `size` mm is the whole grid, which is what `RT-116`
measures.

The symbol is QR Code Model 2, byte mode, versions 1-40 at all four error
correction levels (`L`, `M`, `Q`, `H`). `content` is encoded as UTF-8, which is
the superset every decoder reads back for plain ASCII, and the smallest version
whose data capacity holds the payload is chosen. The encoder then appends the
Section 8.2.11 terminator and pad codewords, splits the data into the blocks
Table 9 of ISO/IEC 18004 prescribes for that version and level, computes each
block's Reed-Solomon codewords over GF(256), interleaves them, places the
function patterns and the codeword modules, and applies the mask pattern with
the lowest penalty score (`N1`-`N4`), with ties going to the lowest mask index so
the result depends only on the document.

Micro QR, structured-append and ECI symbols, and content longer than a version
40-L symbol can carry, are reported rather than approximated.
"""

from __future__ import annotations

from dataclasses import dataclass

LEVELS = ("L", "M", "Q", "H")

# ISO/IEC 18004 Tables 13-22, as (error-correction codewords per block,
# group 1 blocks, group 1 data codewords, group 2 blocks, group 2 data
# codewords), indexed by version and then by level.
_BLOCKS = (
    {"L": (7, 1, 19, 0, 0), "M": (10, 1, 16, 0, 0), "Q": (13, 1, 13, 0, 0), "H": (17, 1, 9, 0, 0)},
    {"L": (10, 1, 34, 0, 0), "M": (16, 1, 28, 0, 0), "Q": (22, 1, 22, 0, 0), "H": (28, 1, 16, 0, 0)},
    {"L": (15, 1, 55, 0, 0), "M": (26, 1, 44, 0, 0), "Q": (18, 2, 17, 0, 0), "H": (22, 2, 13, 0, 0)},
    {"L": (20, 1, 80, 0, 0), "M": (18, 2, 32, 0, 0), "Q": (26, 2, 24, 0, 0), "H": (16, 4, 9, 0, 0)},
    {"L": (26, 1, 108, 0, 0), "M": (24, 2, 43, 0, 0), "Q": (18, 2, 15, 2, 16), "H": (22, 2, 11, 2, 12)},
    {"L": (18, 2, 68, 0, 0), "M": (16, 4, 27, 0, 0), "Q": (24, 4, 19, 0, 0), "H": (28, 4, 15, 0, 0)},
    {"L": (20, 2, 78, 0, 0), "M": (18, 4, 31, 0, 0), "Q": (18, 2, 14, 4, 15), "H": (26, 4, 13, 1, 14)},
    {"L": (24, 2, 97, 0, 0), "M": (22, 2, 38, 2, 39), "Q": (22, 4, 18, 2, 19), "H": (26, 4, 14, 2, 15)},
    {"L": (30, 2, 116, 0, 0), "M": (22, 3, 36, 2, 37), "Q": (20, 4, 16, 4, 17), "H": (24, 4, 12, 4, 13)},
    {"L": (18, 2, 68, 2, 69), "M": (26, 4, 43, 1, 44), "Q": (24, 6, 19, 2, 20), "H": (28, 6, 15, 2, 16)},
    {"L": (20, 4, 81, 0, 0), "M": (30, 1, 50, 4, 51), "Q": (28, 4, 22, 4, 23), "H": (24, 3, 12, 8, 13)},
    {"L": (24, 2, 92, 2, 93), "M": (22, 6, 36, 2, 37), "Q": (26, 4, 20, 6, 21), "H": (28, 7, 14, 4, 15)},
    {"L": (26, 4, 107, 0, 0), "M": (22, 8, 37, 1, 38), "Q": (24, 8, 20, 4, 21), "H": (22, 12, 11, 4, 12)},
    {"L": (30, 3, 115, 1, 116), "M": (24, 4, 40, 5, 41), "Q": (20, 11, 16, 5, 17), "H": (24, 11, 12, 5, 13)},
    {"L": (22, 5, 87, 1, 88), "M": (24, 5, 41, 5, 42), "Q": (30, 5, 24, 7, 25), "H": (24, 11, 12, 7, 13)},
    {"L": (24, 5, 98, 1, 99), "M": (28, 7, 45, 3, 46), "Q": (24, 15, 19, 2, 20), "H": (30, 3, 15, 13, 16)},
    {"L": (28, 1, 107, 5, 108), "M": (28, 10, 46, 1, 47), "Q": (28, 1, 22, 15, 23), "H": (28, 2, 14, 17, 15)},
    {"L": (30, 5, 120, 1, 121), "M": (26, 9, 43, 4, 44), "Q": (28, 17, 22, 1, 23), "H": (28, 2, 14, 19, 15)},
    {"L": (28, 3, 113, 4, 114), "M": (26, 3, 44, 11, 45), "Q": (26, 17, 21, 4, 22), "H": (26, 9, 13, 16, 14)},
    {"L": (28, 3, 107, 5, 108), "M": (26, 3, 41, 13, 42), "Q": (30, 15, 24, 5, 25), "H": (28, 15, 15, 10, 16)},
    {"L": (28, 4, 116, 4, 117), "M": (26, 17, 42, 0, 0), "Q": (28, 17, 22, 6, 23), "H": (30, 19, 16, 6, 17)},
    {"L": (28, 2, 111, 7, 112), "M": (28, 17, 46, 0, 0), "Q": (30, 7, 24, 16, 25), "H": (24, 34, 13, 0, 0)},
    {"L": (30, 4, 121, 5, 122), "M": (28, 4, 47, 14, 48), "Q": (30, 11, 24, 14, 25), "H": (30, 16, 15, 14, 16)},
    {"L": (30, 6, 117, 4, 118), "M": (28, 6, 45, 14, 46), "Q": (30, 11, 24, 16, 25), "H": (30, 30, 16, 2, 17)},
    {"L": (26, 8, 106, 4, 107), "M": (28, 8, 47, 13, 48), "Q": (30, 7, 24, 22, 25), "H": (30, 22, 15, 13, 16)},
    {"L": (28, 10, 114, 2, 115), "M": (28, 19, 46, 4, 47), "Q": (28, 28, 22, 6, 23), "H": (30, 33, 16, 4, 17)},
    {"L": (30, 8, 122, 4, 123), "M": (28, 22, 45, 3, 46), "Q": (30, 8, 23, 26, 24), "H": (30, 12, 15, 28, 16)},
    {"L": (30, 3, 117, 10, 118), "M": (28, 3, 45, 23, 46), "Q": (30, 4, 24, 31, 25), "H": (30, 11, 15, 31, 16)},
    {"L": (30, 7, 116, 7, 117), "M": (28, 21, 45, 7, 46), "Q": (30, 1, 23, 37, 24), "H": (30, 19, 15, 26, 16)},
    {"L": (30, 5, 115, 10, 116), "M": (28, 19, 47, 10, 48), "Q": (30, 15, 24, 25, 25), "H": (30, 23, 15, 25, 16)},
    {"L": (30, 13, 115, 3, 116), "M": (28, 2, 46, 29, 47), "Q": (30, 42, 24, 1, 25), "H": (30, 23, 15, 28, 16)},
    {"L": (30, 17, 115, 0, 0), "M": (28, 10, 46, 23, 47), "Q": (30, 10, 24, 35, 25), "H": (30, 19, 15, 35, 16)},
    {"L": (30, 17, 115, 1, 116), "M": (28, 14, 46, 21, 47), "Q": (30, 29, 24, 19, 25), "H": (30, 11, 15, 46, 16)},
    {"L": (30, 13, 115, 6, 116), "M": (28, 14, 46, 23, 47), "Q": (30, 44, 24, 7, 25), "H": (30, 59, 16, 1, 17)},
    {"L": (30, 12, 121, 7, 122), "M": (28, 12, 47, 26, 48), "Q": (30, 39, 24, 14, 25), "H": (30, 22, 15, 41, 16)},
    {"L": (30, 6, 121, 14, 122), "M": (28, 6, 47, 34, 48), "Q": (30, 46, 24, 10, 25), "H": (30, 2, 15, 64, 16)},
    {"L": (30, 17, 122, 4, 123), "M": (28, 29, 46, 14, 47), "Q": (30, 49, 24, 10, 25), "H": (30, 24, 15, 46, 16)},
    {"L": (30, 4, 122, 18, 123), "M": (28, 13, 46, 32, 47), "Q": (30, 48, 24, 14, 25), "H": (30, 42, 15, 32, 16)},
    {"L": (30, 20, 117, 4, 118), "M": (28, 40, 47, 7, 48), "Q": (30, 43, 24, 22, 25), "H": (30, 10, 15, 67, 16)},
    {"L": (30, 19, 118, 6, 119), "M": (28, 18, 47, 31, 48), "Q": (30, 34, 24, 34, 25), "H": (30, 20, 15, 61, 16)},
)

# The two-bit error-correction indicator of the format information (`L` is not
# the first value: level `M` is 00, `L` is 01, `H` is 10 and `Q` is 11).
_LEVEL_BITS = {"L": 0b01, "M": 0b00, "Q": 0b11, "H": 0b10}

_FORMAT_MASK = 0x5412
_VERSION_GENERATOR = 0x1F25
_PAD = (0xEC, 0x11)


class QrcodeError(ValueError):
    """Content or a level the renderer cannot encode, with the reason named."""


@dataclass(frozen=True)
class Symbol:
    """One encoded QR code: its version, level, mask and dark modules.

    `modules` is indexed `[row][column]`, top to bottom and left to right, and
    is `True` where the symbol prints a dark module. `module_count` is the grid
    size in modules, so the Section 8.2.11 `size` mm divides by it to give the
    width of one module.
    """

    version: int
    level: str
    mask: int
    modules: tuple[tuple[bool, ...], ...]

    @property
    def module_count(self) -> int:
        """How many modules wide the symbol's grid is."""

        return len(self.modules)


def _data_codewords(version: int, level: str) -> int:
    """How many data codewords one version and level carry."""

    _, group1, first, group2, second = _BLOCKS[version - 1][level]
    return group1 * first + group2 * second


def raw_modules(version: int) -> int:
    """The module count left for codewords once every function pattern is placed."""

    result = (16 * version + 128) * version + 64
    if version >= 2:
        count = version // 7 + 2
        result -= (25 * count - 10) * count - 55
        if version >= 7:
            result -= 36
    return result


def _exp_log() -> tuple[tuple[int, ...], tuple[int, ...]]:
    """GF(256) exponent and logarithm tables for the QR field polynomial."""

    exponent = [0] * 512
    logarithm = [0] * 256
    value = 1
    for power in range(255):
        exponent[power] = value
        logarithm[value] = power
        value <<= 1
        if value & 0x100:
            value ^= 0x11D
    for power in range(255, 512):
        exponent[power] = exponent[power - 255]
    return tuple(exponent), tuple(logarithm)


_EXP, _LOG = _exp_log()


def _multiply(left: int, right: int) -> int:
    """Product of two field elements."""

    if left == 0 or right == 0:
        return 0
    return _EXP[_LOG[left] + _LOG[right]]


def _generator(degree: int) -> tuple[int, ...]:
    """The Reed-Solomon generator polynomial for `degree` error codewords."""

    polynomial = [1]
    for power in range(degree):
        factor = _EXP[power]
        shifted = polynomial + [0]
        for index, coefficient in enumerate(polynomial):
            shifted[index + 1] ^= _multiply(coefficient, factor)
        polynomial = shifted
    return tuple(polynomial)


def _remainder(data: list[int], degree: int) -> list[int]:
    """The Reed-Solomon error codewords of one block."""

    generator = _generator(degree)
    remainder = [0] * degree
    for byte in data:
        factor = byte ^ remainder[0]
        remainder = remainder[1:] + [0]
        for index in range(degree):
            remainder[index] ^= _multiply(generator[index + 1], factor)
    return remainder


def _count_bits(version: int) -> int:
    """The byte-mode character count indicator width for one version."""

    return 8 if version <= 9 else 16


def _capacity(version: int, level: str) -> int:
    """How many UTF-8 bytes one version and level can carry."""

    return (_data_codewords(version, level) * 8 - 4 - _count_bits(version)) // 8


def _choose(data: bytes, level: str) -> int:
    """The smallest version whose capacity holds `data`."""

    for version in range(1, 41):
        if len(data) <= _capacity(version, level):
            return version
    largest = _capacity(40, level)
    raise QrcodeError(
        f"content of {len(data)} bytes does not fit a version 40-{level} symbol, "
        f"whose byte capacity is {largest}"
    )


def _codewords(data: bytes, version: int, level: str) -> list[int]:
    """The interleaved data and error codewords of one symbol."""

    bits: list[int] = [0, 1, 0, 0]
    count = len(data)
    width = _count_bits(version)
    bits += [(count >> shift) & 1 for shift in range(width - 1, -1, -1)]
    for byte in data:
        bits += [(byte >> shift) & 1 for shift in range(7, -1, -1)]

    capacity = _data_codewords(version, level) * 8
    bits += [0] * min(4, capacity - len(bits))
    bits += [0] * (-len(bits) % 8)
    codewords = [
        sum(bit << (7 - offset) for offset, bit in enumerate(bits[start : start + 8]))
        for start in range(0, len(bits), 8)
    ]
    index = 0
    while len(codewords) < capacity // 8:
        codewords.append(_PAD[index % 2])
        index += 1

    ec_length, group1, first, group2, second = _BLOCKS[version - 1][level]
    blocks: list[list[int]] = []
    cursor = 0
    for groups, size in ((group1, first), (group2, second)):
        for _ in range(groups):
            blocks.append(codewords[cursor : cursor + size])
            cursor += size
    errors = [_remainder(block, ec_length) for block in blocks]

    interleaved: list[int] = []
    for index in range(max(first, second)):
        interleaved += [block[index] for block in blocks if index < len(block)]
    for index in range(ec_length):
        interleaved += [block[index] for block in errors]
    return interleaved


def _alignment(version: int) -> tuple[int, ...]:
    """The centre coordinates of the alignment patterns of one version."""

    if version == 1:
        return ()
    count = version // 7 + 2
    if version == 32:
        step = 26
    else:
        step = (version * 4 + count * 2 + 1) // (count * 2 - 2) * 2
    size = version * 4 + 17
    return tuple([6] + [size - 7 - index * step for index in range(count - 2, -1, -1)])


def _function_patterns(version: int) -> tuple[list[list[bool]], list[list[bool]]]:
    """The function-pattern modules and the map of which modules are reserved."""

    size = version * 4 + 17
    modules = [[False] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def place(row: int, column: int, dark: bool) -> None:
        modules[row][column] = dark
        reserved[row][column] = True

    # Finder patterns, each with its separator.
    for top, left in ((0, 0), (0, size - 7), (size - 7, 0)):
        for offset in range(-1, 8):
            for across in range(-1, 8):
                row, column = top + offset, left + across
                if not (0 <= row < size and 0 <= column < size):
                    continue
                distance = max(abs(offset - 3), abs(across - 3))
                place(row, column, distance != 2 and distance != 4)

    # Timing patterns.
    for index in range(8, size - 8):
        place(6, index, index % 2 == 0)
        place(index, 6, index % 2 == 0)

    # Alignment patterns, skipping the three finder corners.
    positions = _alignment(version)
    for row in positions:
        for column in positions:
            if (row < 8 and column < 8) or (row < 8 and column > size - 9):
                continue
            if row > size - 9 and column < 8:
                continue
            for offset in range(-2, 3):
                for across in range(-2, 3):
                    distance = max(abs(offset), abs(across))
                    place(row + offset, column + across, distance != 1)

    # The dark module and the reserved format-information strips.
    place(size - 8, 8, True)
    for index in range(9):
        if not reserved[8][index]:
            place(8, index, False)
        if not reserved[index][8]:
            place(index, 8, False)
    for index in range(8):
        place(8, size - 1 - index, False)
        place(size - 1 - index, 8, False)

    # Version information, for versions 7 and up.
    if version >= 7:
        for index in range(18):
            row, column = divmod(index, 3)
            place(row, size - 11 + column, False)
            place(size - 11 + column, row, False)
    return modules, reserved


def _format_bits(level: str, mask: int) -> int:
    """The 15-bit format information of one level and mask, BCH(15, 5) protected."""

    value = _LEVEL_BITS[level] << 3 | mask
    remainder = value
    for _ in range(10):
        remainder = remainder << 1
        if remainder & 0x400:
            remainder ^= 0x537
    return ((value << 10) | remainder) ^ _FORMAT_MASK


def _version_bits(version: int) -> int:
    """The 18-bit version information of version 7 and up, BCH(18, 6) protected."""

    remainder = version
    for _ in range(12):
        remainder = remainder << 1
        if remainder & 0x1000:
            remainder ^= _VERSION_GENERATOR
    return version << 12 | remainder


def _write_format(modules: list[list[bool]], level: str, mask: int) -> None:
    """Place both copies of the format information."""

    size = len(modules)
    bits = _format_bits(level, mask)
    for index in range(6):
        modules[index][8] = bool(bits >> index & 1)
    modules[7][8] = bool(bits >> 6 & 1)
    modules[8][8] = bool(bits >> 7 & 1)
    modules[8][7] = bool(bits >> 8 & 1)
    for index in range(9, 15):
        modules[8][14 - index] = bool(bits >> index & 1)
    for index in range(8):
        modules[8][size - 1 - index] = bool(bits >> index & 1)
    for index in range(8, 15):
        modules[size - 15 + index][8] = bool(bits >> index & 1)
    modules[size - 8][8] = True


def _write_version(modules: list[list[bool]], version: int) -> None:
    """Place both copies of the version information, for versions 7 and up."""

    if version < 7:
        return
    size = len(modules)
    bits = _version_bits(version)
    for index in range(18):
        row, column = divmod(index, 3)
        dark = bool(bits >> index & 1)
        modules[row][size - 11 + column] = dark
        modules[size - 11 + column][row] = dark


def _place(bits: list[int], version: int) -> tuple[list[list[bool]], list[list[bool]]]:
    """Place the codeword bits in the two-module-wide zigzag, unmasked."""

    modules, reserved = _function_patterns(version)
    size = len(modules)
    index = 0
    right = size - 1
    while right > 0:
        if right == 6:
            right = 5
        upward = (right + 1) & 2 == 0
        for step in range(size):
            row = size - 1 - step if upward else step
            for offset in (0, 1):
                column = right - offset
                if reserved[row][column]:
                    continue
                if index < len(bits):
                    modules[row][column] = bool(bits[index])
                index += 1
        right -= 2
    return modules, reserved


def _mask(row: int, column: int, mask: int) -> bool:
    """Whether one mask pattern inverts the module at `row`, `column`."""

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
        return row * column % 2 + row * column % 3 == 0
    if mask == 6:
        return (row * column % 2 + row * column % 3) % 2 == 0
    return ((row + column) % 2 + row * column % 3) % 2 == 0


def _applied(
    modules: list[list[bool]], reserved: list[list[bool]], mask: int
) -> list[list[bool]]:
    """One candidate matrix with `mask` applied to its data modules."""

    return [
        [
            module != (not reserved[row][column] and _mask(row, column, mask))
            for column, module in enumerate(line)
        ]
        for row, line in enumerate(modules)
    ]


def _penalty(modules: list[list[bool]]) -> int:
    """The `N1`-`N4` penalty score of one masked matrix."""

    size = len(modules)
    score = 0
    lines = [list(line) for line in modules]
    lines += [[modules[row][column] for row in range(size)] for column in range(size)]
    # N3: the 1:1:3:1:1 finder ratio needs a light area four modules wide on
    # either side, and the quiet zone outside the symbol counts as light.
    finder = (True, False, True, True, True, False, True)

    for line in lines:
        run = 1
        for index in range(1, size + 1):
            if index < size and line[index] == line[index - 1]:
                run += 1
                continue
            if run >= 5:
                score += 3 + (run - 5)
            run = 1
        padded = [False] * 4 + line + [False] * 4
        for start in range(size):
            if tuple(padded[start + 4 : start + 11]) != finder:
                continue
            if not any(padded[start : start + 4]) or not any(padded[start + 11 : start + 15]):
                score += 40

    for row in range(size - 1):
        for column in range(size - 1):
            first = modules[row][column]
            if (
                modules[row][column + 1] == first
                and modules[row + 1][column] == first
                and modules[row + 1][column + 1] == first
            ):
                score += 3

    dark = sum(module for line in modules for module in line)
    total = size * size
    # N4: the proportion of dark modules, in 5% steps from an even balance.
    score += 10 * (abs(dark * 20 - total * 10) // total)
    return score


def encode(content: str, error_correction: str = "M") -> Symbol:
    """Encode one Section 8.2.11 `qrcode` into its masked module matrix."""

    if error_correction not in LEVELS:
        raise QrcodeError(
            f"error_correction {error_correction!r} is not one of {', '.join(LEVELS)}"
        )
    data = content.encode("utf-8")
    version = _choose(data, error_correction)
    bits = [
        bit
        for byte in _codewords(data, version, error_correction)
        for bit in [(byte >> shift) & 1 for shift in range(7, -1, -1)]
    ]
    bits += [0] * (raw_modules(version) % 8)
    base, reserved = _place(bits, version)

    candidates = []
    for mask in range(8):
        candidate = _applied(base, reserved, mask)
        _write_format(candidate, error_correction, mask)
        _write_version(candidate, version)
        candidates.append(candidate)
    best = min(range(8), key=lambda mask: (_penalty(candidates[mask]), mask))

    return Symbol(
        version=version,
        level=error_correction,
        mask=best,
        modules=tuple(tuple(line) for line in candidates[best]),
    )
