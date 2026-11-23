"""Readers for the Section 8.2.10 barcodes, for the conformance suite's `RO-107` case.

The suite has to read a rendered symbol back, so this module decodes a rasterized
barcode from its pixels instead of trusting the encoder that made it: it finds the
painted bounds, turns one scan line (one band per row, for the stacked symbol)
into element widths, scales those to modules by the narrowest element, and turns
the module pattern into characters again.

It inverts the standard's published pattern tables rather than restating them:
ISO/IEC 15417's Code 128 patterns, ISO/IEC 16388's Code 39 alphabet, ISO/IEC
15420's EAN/UPC digit sets, ISO/IEC 16390's interleaved 2 of 5 and ISO/IEC
16389's Codabar live in `renderer.barcode`, and PDF417's 2787 row patterns live
in `renderer.pdf417_tables`. What is not shared is the reading path or the
checks: the modulo-10 and modulo-103 check digits, the PDF417 row indicators, its
byte decompaction and its Reed-Solomon syndromes are computed here, so a wrong bar
or a misplaced codeword cannot pass.

A clean raster of a conforming artifact needs no error correction, so the readers
report what the pixels say rather than repairing them.
"""

from __future__ import annotations

from dataclasses import dataclass

from renderer import assets, barcode, pdf417_tables

# The published element-width patterns, inverted: observed widths name a value.
_CODE128 = {pattern: value for value, pattern in enumerate(barcode._PATTERNS)}
_CODE128_START_B = 104
_CODE128_STOP = barcode._STOP
_CODE39 = {pattern: character for character, pattern in barcode._CODE39.items()}
_CODE39_GUARD = barcode._CODE39_GUARD
_ITF = {pattern: digit for digit, pattern in barcode._ITF.items()}
_ITF_START = barcode._ITF_START
_ITF_STOP = barcode._ITF_STOP
_CODABAR = {pattern: character for character, pattern in barcode._CODABAR.items()}
_EAN_L = {pattern: digit for digit, pattern in barcode._EAN13_L.items()}
_EAN_G = {pattern: digit for digit, pattern in barcode._EAN13_G.items()}
_EAN_R = {pattern: digit for digit, pattern in barcode._EAN13_R.items()}
_EAN13_PARITY = {parity: digit for digit, parity in barcode._EAN13_PARITY.items()}
_UPC_E_PARITY = {parity: digit for digit, parity in barcode._UPC_E_PARITY.items()}

# PDF417: ISO/IEC 15438's start and stop patterns, its field and its frame, which
# is 17 modules of start, two indicators and 18 modules of stop around the data.
_PDF417_START = 0x1FEA8
_PDF417_STOP = 0x3FA29
_PDF417_MODULUS = 929
_PDF417_FRAME = 17 + 18
_PDF417_PATTERNS = tuple(
    {pattern: value for value, pattern in enumerate(cluster)}
    for cluster in pdf417_tables.PATTERNS
)


class ReaderError(ValueError):
    """A raster the reader cannot read, with the reason named."""


@dataclass(frozen=True)
class Reading:
    """One decoded symbol: its content as printed, its shape, and where it sits.

    `error_codewords` is the Reed-Solomon degree whose syndromes the reader
    evaluated, so a caller can tell that the stacked symbol's error block was
    checked and not skipped; it is zero for the linear symbols, which carry none.
    """

    symbology: str
    content: str
    modules: int
    rows: int
    columns: int
    error_codewords: int
    left: float
    top: float
    right: float
    bottom: float


def _dark(picture: assets.Picture) -> list[list[bool]]:
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


def _elements(dark: list[list[bool]], y: int, left: int, right: int) -> list[int]:
    """The widths of the alternating elements across one scan line, bar first."""

    widths: list[int] = []
    current = dark[y][left]
    if not current:
        raise ReaderError("the symbol's scan line starts on background")
    length = 0
    for x in range(left, right + 1):
        if dark[y][x] == current:
            length += 1
        else:
            widths.append(length)
            length = 1
            current = dark[y][x]
    widths.append(length)
    if not current:
        raise ReaderError("the symbol's scan line ends on background")
    return widths


def _module_counts(widths: list[int], limit: int = 4) -> list[int]:
    """Scale one line's pixel widths to modules, fitting the whole line at once.

    The narrowest element is not one module for every symbology — a Code 128
    character is eleven modules over six elements — so the fit tries every whole
    module count the line's span allows and keeps the grid that reproduces the
    measured widths most closely. `limit` is the widest element the symbology
    prints: four modules for the linear symbols, eight for PDF417's start pattern.
    """

    span = sum(widths)
    best: tuple[float, list[int]] | None = None
    for total in range(max(4, len(widths)), span + 1):
        module = span / total
        counts = [max(1, round(width / module)) for width in widths]
        if sum(counts) != total or max(counts) > limit:
            continue
        error = sum(
            (width - count * module) ** 2
            for width, count in zip(widths, counts, strict=True)
        ) / (module * module)
        if best is None or error < best[0]:
            best = (error, counts)
    if best is None or best[0] > len(widths) * 0.09:
        raise ReaderError(f"the element widths {widths} do not fit a whole module grid")
    return best[1]


def _bits(widths: list[int]) -> str:
    """The modules one line spans, as `1` for a bar and `0` for a space."""

    modules: list[str] = []
    dark = True
    for width in widths:
        modules.append(("1" if dark else "0") * width)
        dark = not dark
    return "".join(modules)


def _check_digit(data: str) -> str:
    """The modulo-10 check digit `data` requires, weighted from its last digit."""

    total = sum(
        int(digit) * (3 if (len(data) - 1 - index) % 2 == 0 else 1)
        for index, digit in enumerate(data)
    )
    return str((10 - total % 10) % 10)


def _upce_check(digits: str) -> str:
    """The check digit a six-digit number-system-0 UPC-E payload requires."""

    leading, last = digits[:5], digits[5]
    if last in "012":
        expanded = f"0{leading[:2]}{last}0000{leading[2:]}"
    elif last == "3":
        expanded = f"0{leading[:3]}00000{leading[3:]}"
    elif last == "4":
        expanded = f"0{leading[:4]}00000{leading[4:]}"
    else:
        expanded = f"0{leading}0000{last}"
    return _check_digit(expanded)


def _decode_code128(widths: list[int]) -> str:
    """Code 128 subset B: start, data characters, the modulo-103 check, the stop."""

    if len(widths) < 25 or (len(widths) - 7) % 6:
        raise ReaderError(
            f"a code128 symbol holds {len(widths)} elements, which no character sequence fills"
        )
    stop = "".join(str(width) for width in widths[-7:])
    if stop != _CODE128_STOP:
        raise ReaderError(f"the code128 stop pattern is {stop}, expected {_CODE128_STOP}")
    values: list[int] = []
    for start in range(0, len(widths) - 7, 6):
        pattern = "".join(str(width) for width in widths[start : start + 6])
        value = _CODE128.get(pattern)
        if value is None:
            raise ReaderError(f"the code128 element widths {pattern} are not a character")
        values.append(value)
    if values[0] != _CODE128_START_B:
        raise ReaderError(
            f"the code128 symbol starts with value {values[0]}, and subset B starts with "
            f"{_CODE128_START_B}"
        )
    data, check = values[1:-1], values[-1]
    if not data:
        raise ReaderError("the code128 symbol carries no data character")
    required = (
        _CODE128_START_B
        + sum(value * position for position, value in enumerate(data, 1))
    ) % 103
    if check != required:
        raise ReaderError(
            f"the code128 check character is {check}, and the data requires {required}"
        )
    for value in data:
        if value > 94:
            raise ReaderError(f"code128 subset B cannot print the value {value}")
    return "".join(chr(value + 0x20) for value in data)


def _decode_code39(widths: list[int]) -> str:
    """Code 39: the `*` guard, characters separated by one narrow space."""

    if len(widths) < 19 or (len(widths) - 9) % 10:
        raise ReaderError(
            f"a code39 symbol holds {len(widths)} elements, which no character sequence fills"
        )
    guard = "".join(str(width) for width in widths[:9])
    if guard != _CODE39_GUARD:
        raise ReaderError("the code39 symbol does not start with its guard character")
    rest = widths[9:]
    characters: list[str] = []
    for start in range(0, len(rest), 10):
        if rest[start] != 1:
            raise ReaderError("code39 characters are separated by one narrow space")
        pattern = "".join(str(width) for width in rest[start + 1 : start + 10])
        if pattern == _CODE39_GUARD:
            if start + 10 != len(rest):
                raise ReaderError("the code39 guard character appears before the end")
            continue
        character = _CODE39.get(pattern)
        if character is None:
            raise ReaderError(f"the code39 element widths {pattern} are not a character")
        characters.append(character)
    return "".join(characters)


def _decode_itf(widths: list[int]) -> str:
    """Interleaved 2 of 5: two digits per ten elements, bars then spaces."""

    if len(widths) < 17 or (len(widths) - 7) % 10:
        raise ReaderError(
            f"an itf symbol holds {len(widths)} elements, which no digit pair fills"
        )
    start = "".join(str(width) for width in widths[:4])
    if start != _ITF_START:
        raise ReaderError(f"the itf start pattern is {start}, expected {_ITF_START}")
    stop = "".join(str(width) for width in widths[-3:])
    if stop != _ITF_STOP:
        raise ReaderError(f"the itf stop pattern is {stop}, expected {_ITF_STOP}")
    middle = widths[4:-3]
    digits: list[str] = []
    for start in range(0, len(middle), 10):
        group = middle[start : start + 10]
        for pattern in (
            "".join(str(width) for width in group[0::2]),
            "".join(str(width) for width in group[1::2]),
        ):
            digit = _ITF.get(pattern)
            if digit is None:
                raise ReaderError(f"the itf element widths {pattern} are not a digit")
            digits.append(digit)
    return "".join(digits)


def _decode_codabar(widths: list[int]) -> str:
    """Codabar: the start and stop characters, then the data characters."""

    if len(widths) < 15 or (len(widths) + 1) % 8:
        raise ReaderError(
            f"a codabar symbol holds {len(widths)} elements, which no character sequence fills"
        )
    characters: list[str] = []
    for start in range(0, len(widths), 8):
        pattern = "".join(str(width) for width in widths[start : start + 7])
        character = _CODABAR.get(pattern)
        if character is None:
            raise ReaderError(f"the codabar element widths {pattern} are not a character")
        characters.append(character)
        if start + 7 < len(widths) and widths[start + 7] != 1:
            raise ReaderError("codabar characters are separated by one narrow space")
    if characters[0] not in "ABCD" or characters[-1] not in "ABCD":
        raise ReaderError("the codabar symbol does not start and stop on a start character")
    return "".join(characters)


def _guards(bits: str, centre: int) -> None:
    """Require the two outer guards and the centre guard of an EAN/UPC symbol."""

    if bits[:3] != "101" or bits[-3:] != "101":
        raise ReaderError("the EAN/UPC outer guards are not where the standard puts them")
    if bits[centre : centre + 5] != "01010":
        raise ReaderError("the EAN/UPC centre guard is not where the standard puts it")


def _left_digit(bits: str, index: int) -> tuple[str, str]:
    """One left-half digit and the parity set it printed in."""

    pattern = bits[3 + 7 * index : 10 + 7 * index]
    if pattern in _EAN_L:
        return _EAN_L[pattern], "L"
    if pattern in _EAN_G:
        return _EAN_G[pattern], "G"
    raise ReaderError(f"left digit {index} is {pattern}, which is no EAN/UPC pattern")


def _right_digit(bits: str, offset: int, index: int) -> str:
    """One right-half digit."""

    pattern = bits[offset + 7 * index : offset + 7 * index + 7]
    digit = _EAN_R.get(pattern)
    if digit is None:
        raise ReaderError(f"right digit {index} is {pattern}, which is no EAN/UPC pattern")
    return digit


def _decode_ean13(widths: list[int]) -> str:
    """EAN-13: six left digits whose parity names the first, then six right digits."""

    bits = _bits(widths)
    if len(bits) != 95:
        raise ReaderError(f"an EAN-13 symbol spans 95 modules, and this spans {len(bits)}")
    _guards(bits, 45)
    parities: list[str] = []
    digits: list[str] = []
    for index in range(6):
        digit, parity = _left_digit(bits, index)
        digits.append(digit)
        parities.append(parity)
    first = _EAN13_PARITY.get("".join(parities))
    if first is None:
        raise ReaderError(f"the EAN-13 parity {''.join(parities)} names no first digit")
    content = first + "".join(digits) + "".join(_right_digit(bits, 50, index) for index in range(6))
    if _check_digit(content[:12]) != content[12]:
        raise ReaderError(
            f"the EAN-13 check digit is {content[12]}, and the first twelve digits require "
            f"{_check_digit(content[:12])}"
        )
    return content


def _decode_ean8(widths: list[int]) -> str:
    """EAN-8: four left digits, four right digits, and the guard between them."""

    bits = _bits(widths)
    if len(bits) != 67:
        raise ReaderError(f"an EAN-8 symbol spans 67 modules, and this spans {len(bits)}")
    _guards(bits, 31)
    content = "".join(_left_digit(bits, index)[0] for index in range(4))
    content += "".join(_right_digit(bits, 36, index) for index in range(4))
    if _check_digit(content[:7]) != content[7]:
        raise ReaderError(
            f"the EAN-8 check digit is {content[7]}, and the first seven digits require "
            f"{_check_digit(content[:7])}"
        )
    return content


def _decode_upca(widths: list[int]) -> str:
    """UPC-A: twelve digits, all six left digits in the odd-parity set."""

    bits = _bits(widths)
    if len(bits) != 95:
        raise ReaderError(f"a UPC-A symbol spans 95 modules, and this spans {len(bits)}")
    _guards(bits, 45)
    content = ""
    for index in range(6):
        digit, parity = _left_digit(bits, index)
        if parity != "L":
            raise ReaderError(f"UPC-A left digit {index} prints in the even-parity set")
        content += digit
    content += "".join(_right_digit(bits, 50, index) for index in range(6))
    if _check_digit(content[:11]) != content[11]:
        raise ReaderError(
            f"the UPC-A check digit is {content[11]}, and the first eleven digits require "
            f"{_check_digit(content[:11])}"
        )
    return content


def _decode_upce(widths: list[int]) -> str:
    """UPC-E: six digits whose parity names the check digit of number system 0."""

    bits = _bits(widths)
    if len(bits) != 51:
        raise ReaderError(f"a UPC-E symbol spans 51 modules, and this spans {len(bits)}")
    if bits[:3] != "101" or bits[45:] != "010101":
        raise ReaderError("the UPC-E guards are not where the standard puts them")
    parities: list[str] = []
    digits: list[str] = []
    for index in range(6):
        digit, parity = _left_digit(bits, index)
        digits.append(digit)
        parities.append("E" if parity == "G" else "O")
    check = _UPC_E_PARITY.get("".join(parities))
    if check is None:
        raise ReaderError(f"the UPC-E parity {''.join(parities)} names no check digit")
    payload = "".join(digits)
    if _upce_check(payload) != check:
        raise ReaderError(
            f"the UPC-E parity names check digit {check}, and {payload} requires "
            f"{_upce_check(payload)}"
        )
    return f"0{payload}{check}"


_LINEAR = {
    "code128": _decode_code128,
    "code39": _decode_code39,
    "ean13": _decode_ean13,
    "ean8": _decode_ean8,
    "upca": _decode_upca,
    "upce": _decode_upce,
    "itf": _decode_itf,
    "codabar": _decode_codabar,
}


def _bands(
    dark: list[list[bool]], left: int, right: int, top: int, bottom: int, module: float
) -> list[tuple[int, int]]:
    """The scan-line bands of one pattern each: one band per PDF417 row."""

    bands: list[tuple[int, int]] = []
    previous: list[bool] | None = None
    start = top
    for y in range(top, bottom + 1):
        line = dark[y][left : right + 1]
        if previous is None:
            previous = line
        elif line != previous:
            bands.append((start, y - 1))
            start = y
            previous = line
    bands.append((start, bottom))
    # A row boundary can leave a one-pixel blended line that the threshold splits
    # either way; anything thinner than half a module is such a line, not a row.
    minimum = max(2, int(module * 0.5))
    return [band for band in bands if band[1] - band[0] + 1 >= minimum]


def _six_byte_groups(words: list[int]) -> bytes:
    """The bytes of one byte-compaction run: five base-900 codewords per six bytes."""

    data = bytearray()
    for start in range(0, len(words), 5):
        value = 0
        for word in words[start : start + 5]:
            value = value * 900 + word
        if value >= 1 << 48:
            raise ReaderError("a six-byte group carries a value wider than 48 bits")
        data += value.to_bytes(6, "big")
    return bytes(data)


def _utf8(data: bytes, description: str) -> str:
    """The text one byte-compaction run carries."""

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReaderError(f"{description} does not decode as UTF-8: {exc}") from None


def _check_syndromes(words: list[int], degree: int) -> None:
    """Evaluate the block at every generator root `3^1 ... 3^degree`; all must be zero."""

    for power in range(1, degree + 1):
        root = pow(3, power, _PDF417_MODULUS)
        value = 0
        for word in words:
            value = (value * root + word) % _PDF417_MODULUS
        if value:
            raise ReaderError(
                f"the PDF417 Reed-Solomon syndromes are not zero: S{power} = {value}, so a "
                "codeword is missing, misplaced or damaged"
            )


def _decompact(payload: list[int]) -> str:
    """The text one PDF417 data region carries: one byte-mode latch and its bytes."""

    while payload and payload[-1] == 900:
        payload.pop()
    if not payload:
        raise ReaderError("the PDF417 data region carries no latch")
    latch, rest = payload[0], payload[1:]
    if latch == 924:
        if len(rest) % 5:
            raise ReaderError(
                f"the PDF417 byte latch 924 holds {len(rest)} codewords, which is not a whole "
                "number of six-byte groups"
            )
        return _utf8(_six_byte_groups(rest), "the PDF417 data region")
    if latch != 901:
        raise ReaderError(
            f"the PDF417 data region starts with codeword {latch}, not a byte-mode latch"
        )
    if not rest:
        raise ReaderError("the PDF417 byte latch 901 carries no data")
    # 901 ends with one to five single-byte codewords. A run whose length is a
    # multiple of five could equally be five bytes or one six-byte group, so when
    # both readings yield text the reader refuses to guess.
    remainders = {len(rest) % 5}
    if len(rest) % 5 == 0:
        remainders.add(5)
    texts: set[str] = set()
    for remainder in sorted(remainders):
        literals = rest[len(rest) - remainder :]
        if any(word > 0xFF for word in literals):
            continue
        data = _six_byte_groups(rest[: len(rest) - remainder]) + bytes(literals)
        try:
            texts.add(data.decode("utf-8"))
        except UnicodeDecodeError:
            continue
    if not texts:
        raise ReaderError("the PDF417 byte latch 901 does not decode as UTF-8")
    if len(texts) > 1:
        raise ReaderError(
            f"the PDF417 byte latch 901 is ambiguous: it reads as {sorted(texts)}"
        )
    return texts.pop()


def _same(name: str, seen: int | None, value: int) -> int:
    """One row indicator's value, required to agree with the rows before it."""

    if seen is not None and seen != value:
        raise ReaderError(
            f"the PDF417 row indicators disagree about the {name}: {seen} and {value}"
        )
    return value


def _decode_pdf417(picture: assets.Picture) -> Reading:
    """PDF417: every row's start, codewords and stop, the indicators, then the text."""

    dark = _dark(picture)
    left, top, right, bottom = _bounds(dark)
    total = -1
    columns = 0
    for offset in (2, 1, 3, 4):
        if top + offset > bottom:
            continue
        widths = _module_counts(_elements(dark, top + offset, left, right), limit=8)
        if (sum(widths) - _PDF417_FRAME) % 17 == 0 and sum(widths) > _PDF417_FRAME:
            total = sum(widths)
            columns = (total - _PDF417_FRAME) // 17 - 2
            break
    if total < 0:
        raise ReaderError("the top row does not span a whole number of PDF417 codewords")
    module = (right - left + 1) / total
    bands = _bands(dark, left, right, top, bottom, module)
    if len(bands) < 3:
        raise ReaderError(f"the symbol stacks {len(bands)} rows, and PDF417 needs at least 3")

    words: list[int] = []
    indicators: list[tuple[int, int]] = []
    for index, (band_top, band_bottom) in enumerate(bands):
        y = (band_top + band_bottom) // 2
        bits = "".join(
            "1" if dark[y][int(left + (column + 0.5) * module)] else "0"
            for column in range(total)
        )
        if int(bits[:17], 2) != _PDF417_START:
            raise ReaderError(f"row {index} does not start with the PDF417 start pattern")
        if int(bits[-18:], 2) != _PDF417_STOP:
            raise ReaderError(f"row {index} does not end with the PDF417 stop pattern")
        cluster = _PDF417_PATTERNS[index % 3]
        row: list[int] = []
        middle = bits[17:-18]
        for start in range(0, len(middle), 17):
            value = int(middle[start : start + 17], 2)
            word = cluster.get(value)
            if word is None:
                raise ReaderError(
                    f"row {index} holds a 17-module pattern that is not a PDF417 codeword"
                )
            row.append(word)
        if len(row) != columns + 2:
            raise ReaderError(
                f"row {index} holds {len(row)} codewords, and its width allows {columns + 2}"
            )
        indicators.append((row[0], row[-1]))
        words.extend(row[1:-1])

    high = low = level = column_count = None
    for index, (left_word, right_word) in enumerate(indicators):
        if left_word // 30 != index // 3 or right_word // 30 != index // 3:
            raise ReaderError(
                f"row {index}'s indicators name row group {left_word // 30}/"
                f"{right_word // 30}"
            )
        if index % 3 == 0:
            high = _same("row count", high, left_word % 30)
            column_count = _same("column count", column_count, right_word % 30 + 1)
        elif index % 3 == 1:
            extra = left_word % 30
            level = _same("error-correction level", level, extra // 3)
            low = _same("row count", low, extra % 3)
            high = _same("row count", high, right_word % 30)
        else:
            column_count = _same("column count", column_count, left_word % 30 + 1)
            extra = right_word % 30
            level = _same("error-correction level", level, extra // 3)
            low = _same("row count", low, extra % 3)
    if high is None or low is None or level is None or column_count is None:
        raise ReaderError("the PDF417 row indicators name no complete geometry")
    if column_count != columns:
        raise ReaderError(
            f"the row indicators name {column_count} columns, and the row spans {columns}"
        )
    if 3 * high + low + 1 != len(bands):
        raise ReaderError(
            f"the row indicators name {3 * high + low + 1} rows, and the symbol stacks "
            f"{len(bands)}"
        )

    degree = 1 << (level + 1)
    if len(words) != len(bands) * columns:
        raise ReaderError(
            f"the symbol holds {len(words)} codewords, and its grid holds "
            f"{len(bands) * columns}"
        )
    if words[0] + degree != len(words):
        raise ReaderError(
            f"the PDF417 length codeword is {words[0]}, and {len(words) - degree} data "
            "codewords precede the error-correction block"
        )
    _check_syndromes(words, degree)
    content = _decompact(words[1 : words[0]])
    return Reading(
        symbology="pdf417",
        content=content,
        modules=total,
        rows=len(bands),
        columns=columns,
        error_codewords=degree,
        left=float(left),
        top=float(top),
        right=float(right + 1),
        bottom=float(bottom + 1),
    )


def read(picture: assets.Picture, symbology: str) -> Reading:
    """Read one rasterized Section 8.2.10 symbol of the named symbology."""

    if symbology == "pdf417":
        return _decode_pdf417(picture)
    decode = _LINEAR.get(symbology)
    if decode is None:
        raise ReaderError(
            f"the reader decodes {', '.join([*barcode.SUPPORTED, 'pdf417'])}, not {symbology!r}"
        )
    dark = _dark(picture)
    left, top, right, bottom = _bounds(dark)
    y = (top + bottom) // 2
    widths = _module_counts(_elements(dark, y, left, right))
    return Reading(
        symbology=symbology,
        content=decode(widths),
        modules=sum(widths),
        rows=1,
        columns=0,
        error_codewords=0,
        left=float(left),
        top=float(top),
        right=float(right + 1),
        bottom=float(bottom + 1),
    )
