"""Code 128, Code 39, EAN-13, EAN-8, UPC-A, UPC-E, ITF and Codabar encoding for
the Section 8.2.10 `barcode` object.

`renderer.output` turns a `barcode` into the rectangles of one symbol, so this
module answers only what the symbol is: the modules a piece of content prints as,
in the order they appear from left to right. A module is one narrow element of the
symbol, and `renderer.output` scales the whole pattern to the declared
`width` mm, which is what `RT-116` measures.

Eight symbologies are encoded:

* `code128` uses subset B, the printable ASCII range 32-126, with the modulo-103
  check character the standard requires.
* `code39` frames its content with the `*` start and stop characters and one
  narrow space between characters. It prints the 43-character alphabet, has no
  check character by default, and is reported for the lowercase letters it cannot
  carry rather than converted.
* `ean13`, `ean8`, `upca` and `upce` accept a payload with or without its check
  digit: the shorter form gets the digit computed and the full one is verified.
  `upce` also accepts the number system digit, and encodes number system 0 only.
* `itf` interleaves pairs of digits, so its content needs an even digit count.
* `codabar` prints the start and stop characters its content names, `A`-`D`, and
  the digits and symbols between them.

`code39`, `itf` and `codabar` use a wide element of three modules, the ratio
`itf` and `codabar` are rationalized at and the ratio `code39` prints in this
renderer. `pdf417` is a stacked 2D symbol with its own codeword tables and
compaction modes, so it is reported rather than approximated, as is content a
symbology cannot carry and a symbology this module does not know.
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

# Code 39 element widths: five bars and four spaces, bar first, with three wide
# elements per character. `_CODE39_GUARD` is the `*` start and stop character.
_CODE39 = {
    "0": "111331311",
    "1": "311311113",
    "2": "113311113",
    "3": "313311111",
    "4": "111331113",
    "5": "311331111",
    "6": "113331111",
    "7": "111311313",
    "8": "311311311",
    "9": "113311311",
    "A": "311113113",
    "B": "113113113",
    "C": "313113111",
    "D": "111133113",
    "E": "311133111",
    "F": "113133111",
    "G": "111113313",
    "H": "311113311",
    "I": "113113311",
    "J": "111133311",
    "K": "311111133",
    "L": "113111133",
    "M": "313111131",
    "N": "111131133",
    "O": "311131131",
    "P": "113131131",
    "Q": "111111333",
    "R": "311111331",
    "S": "113111331",
    "T": "111131331",
    "U": "331111113",
    "V": "133111113",
    "W": "333111111",
    "X": "131131113",
    "Y": "331131111",
    "Z": "133131111",
    "-": "131111313",
    ".": "331111311",
    " ": "133111311",
    "$": "131313111",
    "/": "131311131",
    "+": "131113131",
    "%": "111313131",
}
_CODE39_GUARD = "131131311"

# ITF element widths: five elements per digit, bar first, with two wide ones. Two
# digits interleave, the first as bars and the second as spaces.
_ITF = {
    "0": "11331",
    "1": "31113",
    "2": "13113",
    "3": "33111",
    "4": "11313",
    "5": "31311",
    "6": "13311",
    "7": "11133",
    "8": "31131",
    "9": "13131",
}
_ITF_START = "1111"
_ITF_STOP = "311"

# Codabar element widths: four bars and three spaces, bar first. `A`-`D` are the
# start and stop characters, which carry three wide elements.
_CODABAR = {
    "0": "1111133",
    "1": "1111331",
    "2": "1113113",
    "3": "3311111",
    "4": "1131131",
    "5": "3111131",
    "6": "1311113",
    "7": "1311311",
    "8": "1331111",
    "9": "3113111",
    "-": "1113311",
    "$": "1133111",
    ":": "3111313",
    "/": "3131113",
    ".": "3131311",
    "+": "1131313",
    "A": "1133131",
    "B": "1313113",
    "C": "1113133",
    "D": "1113331",
}

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

# UPC-E parity per check digit for number system 0: `E` selects the even-parity
# set `_EAN13_G` and `O` the odd one `_EAN13_L`. Number system 1 is the inverse.
_UPC_E_PARITY = {
    "0": "EEEOOO", "1": "EEOEOO", "2": "EEOOEO", "3": "EEOOOE", "4": "EOEEOO",
    "5": "EOOEEO", "6": "EOOOEE", "7": "EOEOEO", "8": "EOEOOE", "9": "EOOEOE",
}

SUPPORTED = ("code128", "code39", "ean13", "ean8", "upca", "upce", "itf", "codabar")


class BarcodeError(ValueError):
    """Content or a symbology the renderer cannot encode, with the reason named."""


@dataclass(frozen=True)
class Symbol:
    """One encoded symbol: its content as printed, and a module per bar module.

    `modules` is `True` where the symbol prints a bar and `False` where it leaves
    the background, left to right. `content` is the normalized payload, so an
    EAN-13 given twelve digits carries the check digit it computed, a UPC-E given
    six carries its number system and check digit, and a Codabar given lowercase
    guards carries them uppercase.
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


def code39(content: str) -> tuple[bool, ...]:
    """Encode `content` between the `*` start and stop Code 39 characters."""

    if not content:
        raise BarcodeError("code39 content is empty")
    patterns = [_CODE39_GUARD]
    for character in content:
        pattern = _CODE39.get(character)
        if pattern is None:
            raise BarcodeError(
                f"code39 content {content!r} carries {character!r}, which the alphabet cannot "
                "encode; Code 39 prints A-Z, 0-9, space and - . $ / + %"
            )
        patterns.append(pattern)
    patterns.append(_CODE39_GUARD)

    modules: list[bool] = []
    for pattern in patterns:
        if modules:
            modules.append(False)
        modules += _bits(pattern)
    return tuple(modules)


def _numeric(symbology: str, content: str) -> str:
    """The digits `content` carries, with the surrounding whitespace removed."""

    digits = content.strip()
    if not (digits.isascii() and digits.isdigit()):
        raise BarcodeError(f"{symbology} content {content!r} is not all digits")
    return digits


def _check_digit(data: str) -> str:
    """The modulo-10 check digit `data` requires, weighted from its last digit."""

    total = sum(
        int(digit) * (3 if (len(data) - 1 - index) % 2 == 0 else 1)
        for index, digit in enumerate(data)
    )
    return str((10 - total % 10) % 10)


def check_digit(twelve: str) -> str:
    """The EAN-13 check digit the first twelve digits require."""

    return _check_digit(twelve)


def _with_check_digit(symbology: str, content: str, length: int, counts: str) -> str:
    """Validate a payload of `length` digits and its check digit, computing or verifying it."""

    digits = _numeric(symbology, content)
    if len(digits) == length:
        digits += _check_digit(digits)
    elif len(digits) != length + 1:
        raise BarcodeError(
            f"{symbology} content {content!r} has {len(digits)} digits; {counts} are needed"
        )
    expected = _check_digit(digits[:length])
    if digits[length] != expected:
        raise BarcodeError(
            f"{symbology} check digit is {digits[length]}, and {expected} is what the first "
            f"{length} digits require"
        )
    return digits


def ean13(content: str) -> str:
    """Validate one EAN-13 payload and return all thirteen digits."""

    return _with_check_digit("ean13", content, 12, "twelve or thirteen")


def ean8(content: str) -> str:
    """Validate one EAN-8 payload and return all eight digits."""

    return _with_check_digit("ean8", content, 7, "seven or eight")


def upca(content: str) -> str:
    """Validate one UPC-A payload and return all twelve digits."""

    return _with_check_digit("upca", content, 11, "eleven or twelve")


def upce(content: str) -> str:
    """Validate one UPC-E payload and return its number system, six digits and check digit.

    Number system 0 is the only one encoded: the symbol's parity selects between 0
    and 1, and RenderSpec names no `number_system` property to choose with.
    """

    digits = _numeric("upce", content)
    if len(digits) == 6:
        payload, given = digits, None
    elif len(digits) in (7, 8):
        if digits[0] != "0":
            raise BarcodeError(
                f"upce content {content!r} carries number system {digits[0]}; this renderer "
                "encodes number system 0"
            )
        payload = digits[1:7]
        given = digits[7] if len(digits) == 8 else None
    else:
        raise BarcodeError(
            f"upce content {content!r} has {len(digits)} digits; six, seven or eight are needed"
        )
    expected = _check_digit(_upce_expanded(payload))
    if given is not None and given != expected:
        raise BarcodeError(
            f"upce check digit is {given}, and {expected} is what the six digits require"
        )
    return f"0{payload}{expected}"


def _upce_expanded(payload: str) -> str:
    """The eleven UPC-A digits a six-digit number-system-0 UPC-E payload stands for."""

    leading, last = payload[:5], payload[5]
    if last in "012":
        return f"0{leading[:2]}{last}0000{leading[2:]}"
    if last == "3":
        return f"0{leading[:3]}00000{leading[3:]}"
    if last == "4":
        return f"0{leading[:4]}00000{leading[4:]}"
    return f"0{leading}0000{last}"


def _ean_bits(left: str, right: str) -> tuple[bool, ...]:
    """Frame one EAN/UPC symbol: start guard, left digits, centre guard, right digits, end guard."""

    return tuple(module == "1" for module in f"101{left}01010{right}101")


def _ean13_bits(digits: str) -> tuple[bool, ...]:
    left = "".join(
        (_EAN13_L if parity == "L" else _EAN13_G)[digit]
        for digit, parity in zip(digits[1:7], _EAN13_PARITY[digits[0]], strict=True)
    )
    right = "".join(_EAN13_R[digit] for digit in digits[7:13])
    return _ean_bits(left, right)


def _ean8_bits(digits: str) -> tuple[bool, ...]:
    left = "".join(_EAN13_L[digit] for digit in digits[:4])
    right = "".join(_EAN13_R[digit] for digit in digits[4:])
    return _ean_bits(left, right)


def _upca_bits(digits: str) -> tuple[bool, ...]:
    left = "".join(_EAN13_L[digit] for digit in digits[:6])
    right = "".join(_EAN13_R[digit] for digit in digits[6:])
    return _ean_bits(left, right)


def _upce_bits(digits: str) -> tuple[bool, ...]:
    """The 51-module symbol: start guard, six parity digits, and the `010101` end guard."""

    modules = "101"
    for digit, parity in zip(digits[1:7], _UPC_E_PARITY[digits[7]], strict=True):
        modules += (_EAN13_G if parity == "E" else _EAN13_L)[digit]
    return tuple(module == "1" for module in f"{modules}010101")


def itf(content: str) -> tuple[bool, ...]:
    """Encode an even number of digits as interleaved bars and spaces."""

    if not content.strip():
        raise BarcodeError("itf content is empty")
    digits = _numeric("itf", content)
    if len(digits) % 2:
        raise BarcodeError(
            f"itf content {content!r} has {len(digits)} digits; an even count is needed"
        )
    modules = list(_bits(_ITF_START))
    for index in range(0, len(digits), 2):
        bars, spaces = _ITF[digits[index]], _ITF[digits[index + 1]]
        for bar, space in zip(bars, spaces, strict=True):
            modules += [True] * int(bar)
            modules += [False] * int(space)
    modules += _bits(_ITF_STOP)
    return tuple(modules)


def codabar(content: str) -> tuple[bool, ...]:
    """Encode `content`, which names its own `A`-`D` start and stop characters."""

    payload = content.strip().upper()
    if len(payload) < 3:
        raise BarcodeError(
            f"codabar content {content!r} needs a start and a stop character (A-D) around at "
            "least one data character"
        )
    if payload[0] not in "ABCD" or payload[-1] not in "ABCD":
        raise BarcodeError(
            f"codabar content {content!r} must start and end with a start or stop character "
            "(A, B, C or D)"
        )
    for character in payload[1:-1]:
        if character not in _CODABAR or character in "ABCD":
            raise BarcodeError(
                f"codabar content {content!r} carries {character!r}, which the alphabet cannot "
                "encode; Codabar prints 0-9 and - $ : / . + between its start and stop characters"
            )
    modules: list[bool] = []
    for character in payload:
        if modules:
            modules.append(False)
        modules += _bits(_CODABAR[character])
    return tuple(modules)


def symbol(symbology: str, content: str) -> Symbol:
    """Encode one Section 8.2.10 `barcode` into its modules."""

    if symbology == "code128":
        return Symbol("code128", content, code128(content))
    if symbology == "code39":
        return Symbol("code39", content, code39(content))
    if symbology == "ean13":
        digits = ean13(content)
        return Symbol("ean13", digits, _ean13_bits(digits))
    if symbology == "ean8":
        digits = ean8(content)
        return Symbol("ean8", digits, _ean8_bits(digits))
    if symbology == "upca":
        digits = upca(content)
        return Symbol("upca", digits, _upca_bits(digits))
    if symbology == "upce":
        digits = upce(content)
        return Symbol("upce", digits, _upce_bits(digits))
    if symbology == "itf":
        return Symbol("itf", content.strip(), itf(content))
    if symbology == "codabar":
        return Symbol("codabar", content.strip().upper(), codabar(content))
    raise BarcodeError(
        f"symbology {symbology!r} is not implemented; this renderer encodes {', '.join(SUPPORTED)}"
    )
