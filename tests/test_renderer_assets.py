"""Tests for `renderer/assets.py`: the Section 7.2 registry and raster headers."""

from __future__ import annotations

import base64
import struct
import zlib
from pathlib import Path

import pytest

from renderer import assets

ASSETS = (
    Path(__file__).resolve().parent / "conformance" / "fixtures" / "renderspec" / "assets"
)
PNG = ASSETS / "mark.png"
JPEG = ASSETS / "mark.jpg"


def chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def png_bytes(
    *,
    width: int = 2,
    height: int = 2,
    depth: int = 8,
    colour: int = 2,
    interlace: int = 0,
    palette: bytes | None = None,
    transparency: bool = False,
) -> bytes:
    """A PNG with `colour` samples per pixel, filters off and one IDAT chunk."""

    samples = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colour]
    row = b"\x00" + b"\x80" * (width * samples)
    body = row * height
    parts = [
        assets.PNG_SIGNATURE,
        chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)),
    ]
    if palette is not None:
        parts.append(chunk(b"PLTE", palette))
    if transparency:
        parts.append(chunk(b"tRNS", b"\x00\x00\x00"))
    parts += [chunk(b"IDAT", zlib.compress(body, 9)), chunk(b"IEND", b"")]
    return b"".join(parts)


def filtered_png(rows: list[bytes], kinds: list[int]) -> bytes:
    """A 8-bit RGB PNG whose scanlines carry the filters `kinds`."""

    stride = len(rows[0])
    previous = bytes(stride)
    body = bytearray()
    for row, kind in zip(rows, kinds, strict=True):
        line = bytearray(stride)
        for i in range(stride):
            left = row[i - 3] if i >= 3 else 0
            above = previous[i]
            corner = previous[i - 3] if i >= 3 else 0
            if kind == 0:
                predict = 0
            elif kind == 1:
                predict = left
            elif kind == 2:
                predict = above
            elif kind == 3:
                predict = (left + above) >> 1
            else:
                estimate = left + above - corner
                near = (abs(estimate - left), abs(estimate - above), abs(estimate - corner))
                if near[0] <= near[1] and near[0] <= near[2]:
                    predict = left
                elif near[1] <= near[2]:
                    predict = above
                else:
                    predict = corner
            line[i] = (row[i] - predict) & 0xFF
        body += bytes([kind]) + line
        previous = row
    parts = [
        assets.PNG_SIGNATURE,
        chunk(b"IHDR", struct.pack(">IIBBBBB", stride // 3, len(rows), 8, 2, 0, 0, 0)),
        chunk(b"IDAT", zlib.compress(bytes(body), 9)),
        chunk(b"IEND", b""),
    ]
    return b"".join(parts)


def write(tmp_path: Path, data: bytes, name: str = "picture.png") -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_a_png_keeps_its_header_and_its_own_deflate_stream() -> None:
    picture = assets.picture(str(PNG))
    assert (picture.kind, picture.width, picture.height) == ("png", 16, 8)
    assert (picture.bits, picture.colours, picture.palette) == (8, 3, None)
    assert picture.data in PNG.read_bytes()
    assert picture.data != PNG.read_bytes()


def test_a_jpeg_is_carried_whole_after_its_frame_header() -> None:
    picture = assets.picture(str(JPEG))
    assert (picture.kind, picture.width, picture.height) == ("jpeg", 16, 8)
    assert (picture.bits, picture.colours) == (8, 3)
    assert picture.data == JPEG.read_bytes()


def test_a_paletted_png_keeps_its_table(tmp_path: Path) -> None:
    table = b"\xff\x00\x00\x00\x00\xff"
    picture = assets.picture(write(tmp_path, png_bytes(colour=3, palette=table)))
    assert (picture.colours, picture.palette) == (1, table)
    assert assets.samples(picture) == b"\x80" * 4


def test_samples_undo_every_png_scanline_filter(tmp_path: Path) -> None:
    rows = [bytes((row * 37 + column * 11) & 0xFF for column in range(9)) for row in range(5)]
    picture = assets.picture(write(tmp_path, filtered_png(rows, [0, 1, 2, 3, 4])))
    assert assets.samples(picture) == b"".join(rows)


def test_a_png_stream_that_is_not_deflate_is_reported(tmp_path: Path) -> None:
    parts = [
        assets.PNG_SIGNATURE,
        chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)),
        chunk(b"IDAT", b"not a deflate stream"),
        chunk(b"IEND", b""),
    ]
    picture = assets.picture(write(tmp_path, b"".join(parts)))
    with pytest.raises(assets.AssetError, match="deflate"):
        assets.samples(picture)


def test_png_samples_that_do_not_fill_the_grid_are_reported(tmp_path: Path) -> None:
    parts = [
        assets.PNG_SIGNATURE,
        chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)),
        chunk(b"IDAT", zlib.compress(b"\x00" + b"\x80" * 6, 9)),
        chunk(b"IEND", b""),
    ]
    picture = assets.picture(write(tmp_path, b"".join(parts)))
    with pytest.raises(assets.AssetError, match="needs 14"):
        assets.samples(picture)


def test_a_png_row_with_an_undefined_filter_is_reported(tmp_path: Path) -> None:
    parts = [
        assets.PNG_SIGNATURE,
        chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0)),
        chunk(b"IDAT", zlib.compress(b"\x05" + b"\x80" * 6, 9)),
        chunk(b"IEND", b""),
    ]
    picture = assets.picture(write(tmp_path, b"".join(parts)))
    with pytest.raises(assets.AssetError, match="filter type 5"):
        assets.samples(picture)


@pytest.mark.parametrize(
    ("picture", "message"),
    [
        (png_bytes(interlace=1), "interlaced"),
        (png_bytes(colour=6), "alpha channel"),
        (png_bytes(colour=4), "alpha channel"),
        (png_bytes(transparency=True), "tRNS"),
    ],
)
def test_a_png_the_backends_cannot_carry_is_reported(
    tmp_path: Path, picture: bytes, message: str
) -> None:
    with pytest.raises(assets.AssetError, match=message):
        assets.picture(write(tmp_path, picture))


def test_a_truncated_png_is_reported(tmp_path: Path) -> None:
    with pytest.raises(assets.AssetError, match="IHDR"):
        assets.picture(write(tmp_path, assets.PNG_SIGNATURE + b"\x00\x00\x00\x00IHDR"))


def test_a_source_is_a_local_path_or_a_data_uri() -> None:
    data = PNG.read_bytes()
    uri = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    assert assets.load(str(PNG)) == data
    assert assets.load(uri) == data


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("https://example.test/mark.png", "remote"),
        ("data:image/png;base64,!!!", "base64"),
        ("data:image/png;base64", "data-URI"),
        ("tests/conformance/fixtures/renderspec/assets/absent.png", "cannot be read"),
    ],
)
def test_a_source_that_cannot_be_loaded_is_reported(source: str, message: str) -> None:
    with pytest.raises(assets.AssetError, match=message):
        assets.load(source)


def test_another_format_is_reported_rather_than_converted(tmp_path: Path) -> None:
    with pytest.raises(assets.AssetError, match="neither a PNG nor a JPEG"):
        assets.picture(write(tmp_path, b"GIF89a" + b"\x00" * 8, "picture.gif"))


def test_a_jpeg_without_a_frame_header_is_reported(tmp_path: Path) -> None:
    with pytest.raises(assets.AssetError, match="frame header"):
        assets.picture(write(tmp_path, assets.JPEG_START + b"\xff\xe0\x00\x04\x00\x00", "x.jpg"))


def test_the_registry_resolves_each_source_once_and_reports_the_rest() -> None:
    registry = assets.Registry(
        {"assets": [{"id": "mark", "type": "jpeg", "source": str(JPEG)}]}
    )
    assert registry.picture("mark", "layers/0") is registry.picture("mark", "layers/1")

    with pytest.raises(assets.AssetError, match="not registered"):
        registry.picture("absent", "layers/0")

    svg = assets.Registry({"assets": [{"id": "art", "type": "svg", "source": "art.svg"}]})
    with pytest.raises(assets.AssetError, match="SVG"):
        svg.picture("art", "layers/0")
