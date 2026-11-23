"""RenderSpec Section 7.2 asset registry: raster pictures carried unchanged.

A Section 8.2.9 `image` names an entry of the document's `assets` list, and the
renderer places that picture without rasterizing or re-encoding it: a PNG's zlib
stream becomes a PDF predictor image, and a JPEG's entropy-coded stream becomes a
DCT image in PDF and in PostScript. This module therefore resolves a Section 7.2
`source` to bytes and reads the header each format needs — the dimensions, the
sample depth and the colour layout — so the compressed data reaches the backend
unchanged; `samples` unpacks a PNG only for PostScript, whose Level 2 filters
have no deflate.

Reported rather than guessed: a remote URL (fetching it would make the artifact
depend on the network), SVG artwork (not a raster stream), a picture carrying a
transparency channel, an interlaced PNG (its scanlines are stored in passes, so a
PNG predictor cannot describe them), and a JPEG whose colour component count has
no device colour space.
"""

from __future__ import annotations

import base64
import binascii
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_START = b"\xff\xd8"

# PNG colour type -> samples per pixel. Types 4 and 6 carry an alpha channel.
_PNG_COLOURS = {0: 1, 2: 3, 3: 1}
_PNG_ALPHA = (4, 6)
_PNG_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8)}

# JPEG frame markers that carry the dimensions: baseline, extended, progressive.
_JPEG_FRAMES = (0xC0, 0xC1, 0xC2)


class AssetError(ValueError):
    """An asset the renderer cannot carry, with the reason named."""


@dataclass(frozen=True)
class Picture:
    """One raster picture: its header, and its pixel data still compressed.

    `colours` is the number of samples per pixel in `data`, so a palette PNG
    reports 1 while `palette` carries the RGB table the image indexes into.
    """

    kind: str
    width: int
    height: int
    bits: int
    colours: int
    data: bytes
    palette: bytes | None = None

    @property
    def aspect_ratio(self) -> float:
        """The source width over its height, as declared by the header."""

        return self.width / self.height


def load(source: str) -> bytes:
    """Resolve one Section 7.2 `source` to the bytes of its picture."""

    text = source.strip()
    if text.startswith("data:"):
        header, _, payload = text.partition(",")
        if ";base64" not in header or not payload:
            raise AssetError(f"asset source {source[:32]!r} is not a base64 data-URI")
        try:
            return base64.b64decode(payload, validate=True)
        except (binascii.Error, ValueError):
            raise AssetError(f"asset source {source[:32]!r} is not valid base64") from None
    if text.startswith(("https://", "http://")):
        raise AssetError(
            f"asset source {text!r} is remote; fetching it would make the artifact "
            "depend on the network, so register a data-URI or a local path"
        )
    path = Path(text)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AssetError(f"asset source {text!r} cannot be read: {exc.strerror}") from None


def _png(data: bytes) -> Picture:
    """Read the chunks a PNG needs: dimensions, depth, palette and image data."""

    offset = len(PNG_SIGNATURE)
    header: tuple[int, int, int, int, int] | None = None
    palette: bytes | None = None
    image = bytearray()
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        body = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if len(body) != length:
            raise AssetError("PNG chunk is truncated")
        if kind == b"IHDR":
            if len(body) != 13:
                raise AssetError("PNG IHDR chunk is not 13 bytes")
            width = int.from_bytes(body[0:4], "big")
            height = int.from_bytes(body[4:8], "big")
            header = (width, height, body[8], body[9], body[12])
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            raise AssetError(
                "PNG carries a tRNS transparency chunk, and a transparent image needs "
                "an alpha channel the backends do not carry"
            )
        elif kind == b"IDAT":
            image += body
        elif kind == b"IEND":
            break

    if header is None:
        raise AssetError("PNG has no IHDR chunk")
    width, height, depth, colour, interlace = header
    if width == 0 or height == 0:
        raise AssetError(f"PNG declares a {width}x{height} image")
    if colour in _PNG_ALPHA:
        raise AssetError(
            f"PNG has colour type {colour}, which carries an alpha channel; the "
            "backends carry opaque pictures only"
        )
    if colour not in _PNG_COLOURS:
        raise AssetError(f"PNG has colour type {colour}, which is not defined")
    if depth not in _PNG_DEPTHS[colour]:
        raise AssetError(f"PNG colour type {colour} cannot carry {depth}-bit samples")
    if colour == 3 and palette is None:
        raise AssetError("PNG indexes a palette but declares no PLTE chunk")
    if not image:
        raise AssetError("PNG carries no IDAT image data")
    if interlace:
        raise AssetError(
            f"PNG is interlaced (method {interlace}); its scanlines are stored in "
            "passes, so a PNG predictor cannot describe them"
        )
    return Picture(
        kind="png",
        width=width,
        height=height,
        bits=depth,
        colours=_PNG_COLOURS[colour],
        data=bytes(image),
        palette=palette,
    )


def samples(picture: Picture) -> bytes:
    """A PNG's rows with their filters undone, as `image` reads them.

    Undoing the filter rebuilds exactly the rows the encoder filtered, so the
    declared depth survives: a palette stays indexed and a sub-byte depth stays
    packed.
    """

    try:
        raw = zlib.decompress(picture.data)
    except zlib.error as exc:
        raise AssetError(f"PNG image data is not a deflate stream: {exc}") from None
    depth = picture.colours * picture.bits
    stride = (picture.width * depth + 7) // 8
    expected = (stride + 1) * picture.height
    if len(raw) != expected:
        raise AssetError(
            f"PNG image data holds {len(raw)} bytes where {picture.width} x "
            f"{picture.height} at {picture.bits} bits needs {expected}"
        )

    # The distance to the sample on the left: one byte for a sub-byte depth.
    pixel = max(1, (depth + 7) // 8)
    rows = bytearray(stride * picture.height)
    previous = bytes(stride)
    for row in range(picture.height):
        offset = row * (stride + 1)
        kind = raw[offset]
        if kind > 4:
            raise AssetError(f"PNG row {row + 1} has filter type {kind}, which is not defined")
        line = bytearray(raw[offset + 1 : offset + 1 + stride])
        if kind == 1:
            for i in range(pixel, stride):
                line[i] = (line[i] + line[i - pixel]) & 0xFF
        elif kind == 2:
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif kind in (3, 4):
            for i in range(stride):
                left = line[i - pixel] if i >= pixel else 0
                above = previous[i]
                corner = previous[i - pixel] if i >= pixel else 0
                if kind == 3:
                    predict = (left + above) >> 1
                else:
                    estimate = left + above - corner
                    near_left = abs(estimate - left)
                    near_above = abs(estimate - above)
                    near_corner = abs(estimate - corner)
                    if near_left <= near_above and near_left <= near_corner:
                        predict = left
                    elif near_above <= near_corner:
                        predict = above
                    else:
                        predict = corner
                line[i] = (line[i] + predict) & 0xFF
        rows[row * stride : (row + 1) * stride] = line
        # Each row starts a fresh `line`, so the undone row can be kept by reference.
        previous = line
    return bytes(rows)


def _jpeg(data: bytes) -> Picture:
    """Read the frame header of a JPEG and keep its entropy-coded stream as is."""

    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            raise AssetError(f"JPEG has no marker where one is expected at byte {offset}")
        marker = data[offset + 1]
        if marker == 0xFF:
            offset += 1
            continue
        if marker in (0xD8, 0xD9, 0x01) or 0xD0 <= marker <= 0xD7:
            offset += 2
            continue
        length = int.from_bytes(data[offset + 2 : offset + 4], "big")
        if marker in _JPEG_FRAMES:
            if offset + 10 > len(data):
                raise AssetError("JPEG frame header is truncated")
            precision = data[offset + 4]
            height = int.from_bytes(data[offset + 5 : offset + 7], "big")
            width = int.from_bytes(data[offset + 7 : offset + 9], "big")
            components = data[offset + 9]
            if precision != 8:
                raise AssetError(f"JPEG declares {precision}-bit samples; only 8-bit does")
            if components not in (1, 3, 4):
                raise AssetError(
                    f"JPEG has {components} colour components, and PDF has a device "
                    "colour space for 1, 3 and 4 only"
                )
            if width == 0 or height == 0:
                raise AssetError(f"JPEG declares a {width}x{height} image")
            return Picture(
                kind="jpeg",
                width=width,
                height=height,
                bits=precision,
                colours=components,
                data=data,
            )
        offset += 2 + length
    raise AssetError("JPEG has no baseline, extended or progressive frame header")


def picture(source: str) -> Picture:
    """Resolve one Section 7.2 `source` and read its header, leaving data untouched."""

    data = load(source)
    if data.startswith(PNG_SIGNATURE):
        return _png(data)
    if data.startswith(JPEG_START):
        return _jpeg(data)
    raise AssetError(
        f"asset source {source[:32]!r} is neither a PNG nor a JPEG; "
        "SVG and other formats are reported, not converted"
    )


class Registry:
    """The Section 7.2 `assets` list of one document, resolved on demand."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._entries: dict[str, tuple[str, str]] = {
            str(entry["id"]): (str(entry.get("type", "")), str(entry.get("source", "")))
            for entry in document.get("assets") or ()
        }
        self._pictures: dict[str, Picture] = {}

    def picture(self, asset_id: str, path: str) -> Picture:
        """The picture one Section 8.2.9 `asset_id` names."""

        entry = self._entries.get(str(asset_id))
        if entry is None:
            raise AssetError(
                f"{path}: asset_id {asset_id!r} is not registered in the Section 7.2 "
                "assets list"
            )
        kind, source = entry
        if kind == "svg":
            raise AssetError(
                f"{path}: asset {asset_id!r} is SVG, and SVG artwork is not implemented; "
                "only PNG and JPEG assets are rendered"
            )
        if source not in self._pictures:
            try:
                self._pictures[source] = picture(source)
            except AssetError as exc:
                raise AssetError(f"{path}: {exc}") from None
        return self._pictures[source]
