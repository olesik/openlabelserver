"""Code 128 and EAN-13 encoding for the Section 8.2.10 `barcode` object.

`renderer.output` turns a `barcode` into the rectangles of one symbol, so this
module answers only what the symbol is: the modules a piece of content prints as,
in the order they appear from left to right. A module is one narrow element of the
symbol, and `renderer.output` scales the whole pattern to the declared
`width` mm, which is what `RT-116` measures.

Two symbologies are encoded. Code 128 uses subset B, the printable ASCII range
32-126, with the modulo-103 check character the standard requires. EAN-13 accepts
twelve digits and computes the check digit, or thirteen and verifies it, then emits
the 95-module symbol: start guard, six left digits in the parity the first digit
selects, centre guard, six right digits and the end guard.

The other symbologies Section 8.2.10 names (`code39`, `ean8`, `upca`, `upce`,
`itf`, `codabar`, `pdf417`) are reported rather than approximated, as is content a
symbology cannot carry.
"""

from __future__ import annotations

from dataclasses import dataclass

# Code 128 element widths by value: six digits, bar first, alternating. Values
# 103-105 are the start characters and 106 is the stop pattern (seven elements).
_PATTERNS = (
    "212222", "222122", "222221", "121223", "121322", "131222", "122213",
    "122312", "132212", "221213", "221312", "231212", "112232", "122132",
    "122231", "113222", "123122", "123221", "223211", "221132", "221231",
    "213212", "223112", "312131", "311222", "321122", "321221", "312212",
    "322112", "322211", "212123", "212321", "232121", "111323", "131123",
    "131321", "112313", "132113", "132311", "211313", "231113", "231311",
    "112133", "112331", "132131", "113123", "113321", "133121", "313121",
    "211331", "231131", "213113", "213311", "213131", "311123", "311321",
    "331121", "312113", "312311", "332111", "314111", "221411", "431111",
    "111224", "111422", "121124", "121421", "141122", "141221", "112214",
    "112412", "122114", "122411", "142112", "142211", "241211", "221114",
    "413111", "241112", "134111", "111242", "121142", "121241", "114212",
    "124112", "124211", "411212", "421112", "421211", "212141", "214121",
    "412121", "111143", "111341", "131141", "114113", "114311", "411113",
    "411311", "113141", "114131", "311141", "411131", "211412", "211214",
    "211232",
)

_START_B = 104
_STOP = "2331112"

# EAN-13 digit patterns: left odd, left even and right of the centre guard.
_EAN13_L = {
    "0": "0001101", "1": "0011001", "2": "0010011", "3": "0111101", "4": "0100011",
    "5": "0110001", "6": "0101111", "7": "0111011", "8": "0110111", "9": "0001011",
}
_EAN13_G = {
    "0": "0100111", "1": "0110011", "2": "0011011", "3": "0100001", "4": "0011101",
    "5": "0111001", "6": "0000101", "7": "0010001", "8": "0001001", "9": "0010111",
}
_EAN13_R = {
    "0": "1110010", "1": "1100110", "2": "1101100", "3": "1000010", "4": "1011100",
    "5": "1001110", "6": "1010000", "7": "1000100", "8": "1001000", "9": "1110100",
}

# The six left digits' parity, selected by the first digit.
_EAN13_PARITY = {
    "0": "LLLLLL", "1": "LLGLGG", "2": "LLGGLG", "3": "LLGGGL", "4": "LGLLGG",
    "5": "LGGLLG", "6": "LGGGLL", "7": "LGLGLG", "8": "LGLGGL", "9": "LGGLGL",
}

SUPPORTED = ("code128", "ean13")


class BarcodeError(ValueError):
    """Content or a symbology the renderer cannot encode, with the reason named."""


@dataclass(frozen=True)
class Symbol:
    """One encoded symbol: its content as printed, and a module per bar module.

    `modules` is `True` where the symbol prints a bar and `False` where it leaves
    the background, left to right. `content` is the normalized payload, so an
    EAN-13 given twelve digits carries the check digit it computed.
    """

    symbology: str
    content: str
    modules: tuple[bool, ...]

    @property
    def module_count(self) -> int:
        """How many narrow elements the pattern spans."""

        return len(self.modules)


def _bits(pattern: str) -> tuple[bool, ...]:
    """Expand one element-width string, where the first element is a bar."""

    modules: list[bool] = []
    bar = True
    for width in pattern:
        modules += [bar] * int(width)
        bar = not bar
    return tuple(modules)


def code128(content: str) -> tuple[bool, ...]:
    """Encode `content` in Code 128 subset B."""

    if not content:
        raise BarcodeError("code128 content is empty")
    values: list[int] = []
    for character in content:
        code = ord(character)
        if not 0x20 <= code <= 0x7E:
            raise BarcodeError(
                f"code128 content {content!r} carries {character!r}, which is outside "
                "subset B (printable ASCII 32-126)"
            )
        values.append(code - 0x20)
    checksum = (_START_B + sum(value * position for position, value in enumerate(values, 1))) % 103
    patterns = [_PATTERNS[_START_B], *(_PATTERNS[value] for value in values)]
    patterns += [_PATTERNS[checksum], _STOP]
    return tuple(module for pattern in patterns for module in _bits(pattern))


def check_digit(twelve: str) -> str:
    """The EAN-13 check digit the first twelve digits require."""

    total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(twelve))
    return str((10 - total % 10) % 10)


def ean13(content: str) -> str:
    """Validate one EAN-13 payload and return all thirteen digits."""

    digits = content.strip()
    if not digits.isdigit():
        raise BarcodeError(f"ean13 content {content!r} is not all digits")
    if len(digits) == 12:
        digits += check_digit(digits)
    elif len(digits) != 13:
        raise BarcodeError(
            f"ean13 content {content!r} has {len(digits)} digits; twelve or thirteen are needed"
        )
    expected = check_digit(digits[:12])
    if digits[12] != expected:
        raise BarcodeError(
            f"ean13 check digit is {digits[12]}, and {expected} is what the first twelve digits require"
        )
    return digits


def _ean13_bits(digits: str) -> tuple[bool, ...]:
    bits = "101"
    for digit, parity in zip(digits[1:7], _EAN13_PARITY[digits[0]], strict=True):
        bits += (_EAN13_L if parity == "L" else _EAN13_G)[digit]
    bits += "01010"
    for digit in digits[7:13]:
        bits += _EAN13_R[digit]
    bits += "101"
    return tuple(module == "1" for module in bits)


def symbol(symbology: str, content: str) -> Symbol:
    """Encode one Section 8.2.10 `barcode` into its modules."""

    if symbology == "code128":
        return Symbol("code128", content, code128(content))
    if symbology == "ean13":
        digits = ean13(content)
        return Symbol("ean13", digits, _ean13_bits(digits))
    raise BarcodeError(
        f"symbology {symbology!r} is not implemented; this renderer encodes {', '.join(SUPPORTED)}"
    )
