"""Registered font programs: loading, sfnt parsing and PDF subsetting (`RO-104`).

RenderSpec Section 7.1 registers custom typefaces with a `source` that is a
base64 data-URI, a local path or an HTTPS URL, and requires renderers to embed
them in vector output. This module is the one place that reads such a program:

* `load` resolves the `source`. A remote URL is reported rather than fetched:
  the artifact must depend only on the document, and an HTTP client would make
  the same document render differently on a different day (`DT-101`, `RS-119`).
* `Sfnt` reads a TrueType-outline program (`glyf`/`loca`) far enough to embed
  it: metrics for the PDF font descriptor, the Unicode `cmap` for character to
  glyph resolution, `hmtx` advances, and the composite-glyph closure.
* `Sfnt.subset` rebuilds the program around the glyphs one document uses,
  keeping `.notdef` and every composite component. The result carries no
  timestamp of its own — `head` is copied, not regenerated — so the same
  characters in the same face always produce the same bytes (`DT-101`).

A CFF/OTF program (`OTTO`) is reported instead of converted: subsetting CFF
charstrings is a different algorithm, and silently drawing through a fallback
face would emit text the document did not ask for (`RO-104`). OpenType
collections (`ttcf`) are reported for the same reason.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

# sfnt versions this module can read: 1.0 and the Apple `true` tag.
TRUE_TYPE_VERSIONS = (b"\x00\x01\x00\x00", b"true")
CFF_VERSION = b"OTTO"
COLLECTION_VERSION = b"ttcf"

# The segments and tables a TrueType subset must carry.
REQUIRED_TABLES = ("cmap", "glyf", "head", "hhea", "hmtx", "loca", "maxp")
OPTIONAL_TABLES = ("cvt ", "fpgm", "name", "OS/2", "prep")

# Composite glyph flags, from the TrueType `glyf` specification.
ARG_1_AND_2_ARE_WORDS = 0x0001
WE_HAVE_A_SCALE = 0x0008
MORE_COMPONENTS = 0x0020
WE_HAVE_AN_X_AND_Y_SCALE = 0x0040
WE_HAVE_A_TWO_BY_TWO = 0x0080
WE_HAVE_INSTRUCTIONS = 0x0100

# PDF font-descriptor flags (PDF 32000-1 Table 123).
FLAG_NONSYMBOLIC = 32
FLAG_ITALIC = 64
FLAG_FORCE_BOLD = 1 << 18

MAX_PDF_CID = 0xFFFF


class FontError(ValueError):
    """A font program that cannot be loaded or embedded, with the reason named."""


def load(source: str) -> bytes:
    """Resolve one Section 7.1 `source` to the bytes of its font program."""

    text = source.strip()
    if text.startswith("data:"):
        header, _, payload = text.partition(",")
        if ";base64" not in header or not payload:
            raise FontError(f"font source {source[:32]!r} is not a base64 data-URI")
        try:
            return base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise FontError(f"font source {source[:32]!r} is not valid base64") from None
    if text.startswith(("https://", "http://")):
        raise FontError(
            f"font source {text!r} is remote; fetching it would make the artifact "
            "depend on the network, so register a data-URI or a local path"
        )
    path = Path(text)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise FontError(f"font source {text!r} cannot be read: {exc.strerror}") from None


def _checksum(data: bytes) -> int:
    """The sfnt table checksum: the sum of big-endian uint32s, zero padded."""

    padded = data + b"\0" * (-len(data) % 4)
    return sum(struct.unpack(f">{len(padded) // 4}I", padded)) & 0xFFFFFFFF


def _fixed16_16(value: int) -> float:
    return value / 65536.0


@dataclass(frozen=True)
class Metrics:
    """The font-wide numbers a PDF descriptor or a PostScript must state."""

    units_per_em: int
    bbox: tuple[int, int, int, int]
    ascent: int
    descent: int
    cap_height: int
    italic_angle: float
    weight: int
    postscript_name: str

    def scaled(self, value: int) -> int:
        """One font unit in the 1000-unit glyph space PDF fonts use."""

        return round(value * 1000 / self.units_per_em)


@dataclass(frozen=True)
class Subset:
    """One deterministic glyph subset and how its characters map into it."""

    program: bytes
    tag: str
    cids: Mapping[str, int]
    widths: Mapping[int, int]


def _table_directory(data: bytes) -> dict[str, bytes]:
    """Read an sfnt table directory into tag -> bytes."""

    if len(data) < 12:
        raise FontError("font program is shorter than an sfnt header")
    if data[:4] == COLLECTION_VERSION:
        raise FontError("font collections (`ttcf`) are not supported; register one face")
    if data[:4] == CFF_VERSION:
        raise FontError(
            "CFF/OTF outlines are not supported yet; register a TrueType (`glyf`) program "
            "(RO-104 embedding of CFF is not implemented)"
        )
    if data[:4] not in TRUE_TYPE_VERSIONS:
        raise FontError(f"font program starts with {data[:4]!r}, not a TrueType sfnt")

    count = struct.unpack_from(">H", data, 4)[0]
    tables: dict[str, bytes] = {}
    for index in range(count):
        record = 12 + 16 * index
        if record + 16 > len(data):
            raise FontError("font table directory is truncated")
        tag, _sum, offset, length = struct.unpack_from(">4sIII", data, record)
        if offset + length > len(data):
            raise FontError(f"font table {tag!r} runs past the end of the program")
        tables[tag.decode("latin-1")] = data[offset : offset + length]
    missing = [tag for tag in REQUIRED_TABLES if tag not in tables]
    if missing:
        raise FontError(f"font program lacks the required table(s) {missing}")
    return tables


def _parse_name(tables: Mapping[str, bytes]) -> str:
    """The PostScript name (nameID 6), or the family name, or a placeholder."""

    name = tables.get("name")
    if not name or len(name) < 6:
        return "EmbeddedFont"
    count, string_offset = struct.unpack_from(">HH", name, 2)
    best: dict[int, str] = {}
    for index in range(count):
        record = 6 + 12 * index
        if record + 12 > len(name):
            break
        platform, encoding, language, name_id, length, offset = struct.unpack_from(
            ">HHHHHH", name, record
        )
        start = string_offset + offset
        raw = name[start : start + length]
        if platform == 3 and encoding in (0, 1):
            try:
                text = raw.decode("utf-16-be")
            except UnicodeDecodeError:
                continue
        elif platform == 1 and encoding == 0:
            text = raw.decode("latin-1")
        else:
            continue
        if name_id in (6, 1, 4) and name_id not in best:
            best[name_id] = text
        if language:
            continue
    return best.get(6) or best.get(4) or best.get(1) or "EmbeddedFont"


def _parse_cmap(tables: Mapping[str, bytes]) -> dict[int, int]:
    """A Unicode code point -> glyph id map from the best available subtable."""

    cmap = tables.get("cmap")
    if not cmap or len(cmap) < 4:
        raise FontError("font `cmap` table is missing or truncated")
    count = struct.unpack_from(">H", cmap, 2)[0]
    candidates: list[tuple[int, int, int]] = []
    for index in range(count):
        record = 4 + 8 * index
        if record + 8 > len(cmap):
            break
        platform, encoding, offset = struct.unpack_from(">HHI", cmap, record)
        if offset >= len(cmap):
            continue
        # Prefer a full-repertoire Unicode subtable, then a BMP one.
        rank = {(3, 10): 0, (0, 4): 1, (0, 6): 1, (3, 1): 2, (0, 3): 3}.get((platform, encoding), 9)
        candidates.append((rank, offset, platform))
    for _rank, offset, _platform in sorted(candidates):
        mapping = _cmap_subtable(cmap, offset)
        if mapping:
            return mapping
    raise FontError("font has no readable Unicode `cmap` subtable")


def _cmap_subtable(cmap: bytes, offset: int) -> dict[int, int]:
    """Read one format 4 or format 12 subtable into code point -> glyph id."""

    if offset + 2 > len(cmap):
        return {}
    format_ = struct.unpack_from(">H", cmap, offset)[0]
    mapping: dict[int, int] = {}
    if format_ == 12 and offset + 16 <= len(cmap):
        groups = struct.unpack_from(">I", cmap, offset + 12)[0]
        for index in range(groups):
            record = offset + 16 + 12 * index
            if record + 12 > len(cmap):
                break
            start, end, glyph = struct.unpack_from(">III", cmap, record)
            for code in range(start, min(end, MAX_PDF_CID) + 1):
                mapping[code] = glyph + (code - start)
        return mapping
    if format_ == 4 and offset + 14 <= len(cmap):
        seg_count = struct.unpack_from(">H", cmap, offset + 6)[0] // 2
        ends = offset + 14
        starts = ends + 2 * seg_count + 2
        deltas = starts + 2 * seg_count
        ranges = deltas + 2 * seg_count
        for segment in range(seg_count):
            record = 2 * segment
            if ranges + record + 2 > len(cmap):
                break
            end = struct.unpack_from(">H", cmap, ends + record)[0]
            start = struct.unpack_from(">H", cmap, starts + record)[0]
            delta = struct.unpack_from(">h", cmap, deltas + record)[0]
            range_offset = struct.unpack_from(">H", cmap, ranges + record)[0]
            if start == 0xFFFF:
                continue
            for code in range(start, end + 1):
                if code == 0xFFFF:
                    continue
                if range_offset == 0:
                    glyph = (code + delta) & 0xFFFF
                else:
                    glyph_at = ranges + record + range_offset + 2 * (code - start)
                    if glyph_at + 2 > len(cmap):
                        continue
                    glyph = struct.unpack_from(">H", cmap, glyph_at)[0]
                    if glyph:
                        glyph = (glyph + delta) & 0xFFFF
                if glyph:
                    mapping[code] = glyph
        return mapping
    return mapping


class Sfnt:
    """One TrueType-outline font program, read without external dependencies."""

    def __init__(self, data: bytes) -> None:
        self.data = bytes(data)
        self.tables = _table_directory(self.data)
        head = self.tables["head"]
        hhea = self.tables["hhea"]
        maxp = self.tables["maxp"]
        if len(head) < 54 or len(hhea) < 36 or len(maxp) < 6:
            raise FontError("font `head`, `hhea` or `maxp` table is truncated")
        self.units_per_em = struct.unpack_from(">H", head, 18)[0]
        if self.units_per_em == 0:
            raise FontError("font declares zero units per em")
        self.bbox = struct.unpack_from(">4h", head, 36)
        self.index_to_loc = struct.unpack_from(">h", head, 50)[0]
        self.ascent, self.descent = struct.unpack_from(">2h", hhea, 4)
        self.number_of_h_metrics = struct.unpack_from(">H", hhea, 34)[0]
        if self.number_of_h_metrics == 0:
            raise FontError("font declares no horizontal metrics")
        self.glyph_count = struct.unpack_from(">H", maxp, 4)[0]
        if self.glyph_count == 0:
            raise FontError("font declares no glyphs")
        self.cmap = _parse_cmap(self.tables)

        post = self.tables.get("post")
        self.italic_angle = (
            _fixed16_16(struct.unpack_from(">i", post, 4)[0]) if post and len(post) >= 8 else 0.0
        )

        os2 = self.tables.get("OS/2")
        weight, cap_height, selection = 400, 0, 0
        if os2 and len(os2) >= 64:
            version = struct.unpack_from(">H", os2, 0)[0]
            weight = struct.unpack_from(">H", os2, 4)[0] or 400
            selection = struct.unpack_from(">H", os2, 62)[0]
            if version >= 2 and len(os2) >= 90:
                cap_height = struct.unpack_from(">h", os2, 88)[0]
        self.weight = weight
        self.cap_height = cap_height or round(self.units_per_em * 0.7)
        self.flags = FLAG_NONSYMBOLIC
        if selection & 0x01 or self.italic_angle:
            self.flags |= FLAG_ITALIC
        if weight >= 600:
            self.flags |= FLAG_FORCE_BOLD
        self.metrics = Metrics(
            units_per_em=self.units_per_em,
            bbox=self.bbox,
            ascent=self.ascent,
            descent=self.descent,
            cap_height=self.cap_height,
            italic_angle=self.italic_angle,
            weight=weight,
            postscript_name=_parse_name(self.tables),
        )
        self._loca = self._read_loca()
        self._advances = self._read_advances()

    # -- reading ---------------------------------------------------------

    def _read_loca(self) -> list[int]:
        loca = self.tables["loca"]
        count = self.glyph_count + 1
        if self.index_to_loc == 0:
            if len(loca) < 2 * count:
                raise FontError("font `loca` table is truncated")
            return [2 * value for value in struct.unpack_from(f">{count}H", loca, 0)]
        if len(loca) < 4 * count:
            raise FontError("font `loca` table is truncated")
        return list(struct.unpack_from(f">{count}I", loca, 0))

    def _read_advances(self) -> list[int]:
        hmtx = self.tables["hmtx"]
        count = self.glyph_count
        if len(hmtx) < 4 * self.number_of_h_metrics:
            raise FontError("font `hmtx` table is truncated")
        advances = [
            struct.unpack_from(">H", hmtx, 4 * index)[0]
            for index in range(self.number_of_h_metrics)
        ]
        if len(advances) < count:
            advances += [advances[-1]] * (count - len(advances))
        return advances

    def glyph(self, gid: int) -> bytes:
        """The raw `glyf` bytes of one glyph."""

        if not 0 <= gid < self.glyph_count:
            raise FontError(f"glyph {gid} is outside the font's {self.glyph_count} glyphs")
        return self.tables["glyf"][self._loca[gid] : self._loca[gid + 1]]

    def glyph_id(self, character: str) -> int | None:
        """The glyph one character selects, or `None` when the font lacks it."""

        return self.cmap.get(ord(character))

    def advance(self, gid: int) -> int:
        """One glyph's advance width in font units."""

        return self._advances[gid]

    # -- subsetting ------------------------------------------------------

    def _components(self, gid: int) -> list[int]:
        """The component glyph ids of a composite glyph, empty for a simple one."""

        data = self.glyph(gid)
        if len(data) < 10:
            return []
        contours = struct.unpack_from(">h", data, 0)[0]
        if contours >= 0:
            return []
        components: list[int] = []
        offset = 10
        while True:
            if offset + 4 > len(data):
                break
            flags, component = struct.unpack_from(">HH", data, offset)
            components.append(component)
            offset += 4
            offset += 4 if flags & ARG_1_AND_2_ARE_WORDS else 2
            if flags & WE_HAVE_A_SCALE:
                offset += 2
            elif flags & WE_HAVE_AN_X_AND_Y_SCALE:
                offset += 4
            elif flags & WE_HAVE_A_TWO_BY_TWO:
                offset += 8
            if not flags & MORE_COMPONENTS:
                break
        return [component for component in components if component < self.glyph_count]

    def _composite_closure(self, gids: Iterable[int]) -> set[int]:
        seen = set(gids)
        pending = list(seen)
        while pending:
            gid = pending.pop()
            for component in self._components(gid):
                if component not in seen:
                    seen.add(component)
                    pending.append(component)
        return seen

    def _remap_composites(self, data: bytes, mapping: Mapping[int, int]) -> bytes:
        """Rewrite the component glyph ids of a composite glyph."""

        if len(data) < 10 or struct.unpack_from(">h", data, 0)[0] >= 0:
            return data
        patched = bytearray(data)
        offset = 10
        while offset + 4 <= len(patched):
            flags, component = struct.unpack_from(">HH", patched, offset)
            replacement = mapping.get(component)
            if replacement is not None:
                struct.pack_into(">H", patched, offset + 2, replacement)
            offset += 4
            offset += 4 if flags & ARG_1_AND_2_ARE_WORDS else 2
            if flags & WE_HAVE_A_SCALE:
                offset += 2
            elif flags & WE_HAVE_AN_X_AND_Y_SCALE:
                offset += 4
            elif flags & WE_HAVE_A_TWO_BY_TWO:
                offset += 8
            if not flags & MORE_COMPONENTS:
                break
        return bytes(patched)

    def subset(self, characters: Iterable[str]) -> Subset:
        """Rebuild the program around `characters`, keeping `.notdef` and composites."""

        used: dict[str, int] = {}
        for character in sorted(set(characters)):
            gid = self.glyph_id(character)
            if gid is not None and gid < self.glyph_count:
                used[character] = gid
        keep = self._composite_closure({0, *used.values()})
        order = [0] + sorted(gid for gid in keep if gid)
        if len(order) > MAX_PDF_CID + 1:
            raise FontError(f"subset needs {len(order)} glyphs, more than a PDF CID allows")
        mapping = {gid: index for index, gid in enumerate(order)}

        glyf = bytearray()
        loca = [0]
        for gid in order:
            data = self._remap_composites(self.glyph(gid), mapping)
            glyf += data
            glyf += b"\0" * (-len(glyf) % 4)
            loca.append(len(glyf))
        hmtx = bytearray()
        for gid in order:
            hmtx += struct.pack(">Hh", self.advance(gid), 0)

        tables: dict[str, bytes] = {
            "glyf": bytes(glyf),
            "loca": struct.pack(f">{len(loca)}I", *loca),
            "hmtx": bytes(hmtx),
            "cmap": _format4_cmap({character: mapping[gid] for character, gid in used.items()}),
        }
        tables["head"] = self._subset_head()
        tables["hhea"] = self._subset_hhea(len(order))
        tables["maxp"] = self._subset_maxp(len(order))
        post = self.tables.get("post")
        if post and len(post) >= 32:
            tables["post"] = struct.pack(">I", 0x00030000) + post[4:32]
        for tag in OPTIONAL_TABLES:
            if tag in self.tables:
                tables[tag] = self.tables[tag]

        program = _assemble(tables)
        tag = _subset_tag(program)
        widths = {
            mapping[gid]: round(self.advance(gid) * 1000 / self.units_per_em)
            for gid in used.values()
        }
        widths[0] = round(self.advance(0) * 1000 / self.units_per_em)
        return Subset(
            program=program,
            tag=tag,
            cids={character: mapping[gid] for character, gid in used.items()},
            widths=widths,
        )

    def _subset_head(self) -> bytes:
        head = bytearray(self.tables["head"])
        struct.pack_into(">I", head, 8, 0)  # checkSumAdjustment, set when assembled
        struct.pack_into(">h", head, 50, 1)  # long `loca` offsets
        return bytes(head)

    def _subset_hhea(self, glyphs: int) -> bytes:
        hhea = bytearray(self.tables["hhea"])
        struct.pack_into(">H", hhea, 34, glyphs)
        return bytes(hhea)

    def _subset_maxp(self, glyphs: int) -> bytes:
        maxp = bytearray(self.tables["maxp"])
        struct.pack_into(">H", maxp, 4, glyphs)
        return bytes(maxp)


def _format4_cmap(mapping: Mapping[str, int]) -> bytes:
    """A `cmap` table with one format 4 subtable for the subset's characters."""

    codes = sorted(
        (ord(character), gid) for character, gid in mapping.items() if ord(character) <= 0xFFFE
    )
    segments: list[tuple[int, int, int]] = [
        (code, code, (gid - code + 0x8000) % 0x10000 - 0x8000) for code, gid in codes
    ]
    segments.append((0xFFFF, 0xFFFF, 1))
    count = len(segments)
    entry_selector = max(count.bit_length() - 1, 0)
    search_range = 2 * (1 << entry_selector)
    subtable = (
        struct.pack(
            ">7H", 4, 0, 0, 2 * count, search_range, entry_selector, 2 * count - search_range
        )
        + b"".join(struct.pack(">H", end) for _start, end, _delta in segments)
        + b"\0\0"
        + b"".join(struct.pack(">H", start) for start, _end, _delta in segments)
        + b"".join(struct.pack(">h", delta) for _start, _end, delta in segments)
        + b"\0\0" * count
    )
    subtable = subtable[:2] + struct.pack(">H", len(subtable)) + subtable[4:]
    header = struct.pack(">HHHH", 0, 1, 3, 1) + struct.pack(">I", 12)
    return header + subtable


def _assemble(tables: Mapping[str, bytes]) -> bytes:
    """Write a deterministic sfnt: tags sorted, 4-byte aligned, checksums set."""

    ordered = sorted(tables.items())
    count = len(ordered)
    entry_selector = max(count.bit_length() - 1, 0)
    search_range = 16 * (1 << entry_selector)
    header = struct.pack(
        ">4sHHHH",
        b"\x00\x01\x00\x00",
        count,
        search_range,
        entry_selector,
        16 * count - search_range,
    )
    offset = 12 + 16 * count
    records = bytearray()
    body = bytearray()
    for tag, data in ordered:
        padded = data + b"\0" * (-len(data) % 4)
        records += struct.pack(">4sIII", tag.encode("latin-1"), _checksum(data), offset, len(data))
        body += padded
        offset += len(padded)
    program = bytearray(header + records + body)

    head_offset = (
        12 + 16 * count + sum(len(data) + (-len(data) % 4) for tag, data in ordered if tag < "head")
    )
    struct.pack_into(">I", program, 8, 0)
    adjustment = (0xB1B0AFBA - _checksum(bytes(program))) & 0xFFFFFFFF
    struct.pack_into(">I", program, head_offset + 8, adjustment)
    return bytes(program)


def _subset_tag(program: bytes) -> str:
    """A deterministic six-letter PDF/PostScript subset tag for one program."""

    digest = hashlib.sha256(program).digest()
    return "".join(chr(ord("A") + byte % 26) for byte in digest[:6])
