"""Tests for `renderer/output.py`: the page plan and the PDF/PostScript artifacts."""

from __future__ import annotations

import base64
import re
import zlib
from pathlib import Path
from typing import Any

import pytest

from renderer import assets, fonts, output, pdf, postscript, renderspec
from renderer.layout import Box
from renderer.plan import Face, Fill, Image, Stroke, Text

FONT = (
    Path(__file__).resolve().parent
    / "conformance"
    / "fixtures"
    / "renderspec"
    / "fonts"
    / "probe.ttf"
)
ASSETS = (
    Path(__file__).resolve().parent / "conformance" / "fixtures" / "renderspec" / "assets"
)
JPEG = ASSETS / "mark.jpg"
PNG = ASSETS / "mark.png"


def document(
    objects: list[dict[str, Any]], *, width: float = 90.0, height: float = 29.0, **props: Any
):
    """A one-layer document on a `width` x `height` mm page."""

    return {
        "renderspec": "1.0",
        "id": "output_probe",
        "name": "Output Probe",
        "page": {"width": width, "height": height},
        "layers": [{"id": "base", "name": "Base", "objects": objects}],
        **props,
    }


def rect(object_id: str, **props: Any) -> dict[str, Any]:
    return {"id": object_id, "type": "rect", "width": 10.0, "height": 5.0, **props}


def text(object_id: str, content: str, **props: Any) -> dict[str, Any]:
    return {"id": object_id, "type": "text", "content": content, **props}


def font_uri() -> str:
    return "data:font/ttf;base64," + base64.b64encode(FONT.read_bytes()).decode("ascii")


def embedded(objects: list[dict[str, Any]], **props: Any) -> dict[str, Any]:
    """A document registering the probe face as `Probe Sans`, on one variant."""

    return document(
        objects,
        fonts=[
            {
                "family": "Probe Sans",
                "variants": [{"style": "normal", "weight": "normal", "source": font_uri()}],
            }
        ],
        **props,
    )


def stock(rows: int = 1, columns: int = 2) -> dict[str, Any]:
    return {
        "width": 40.0,
        "height": 20.0,
        "rows": rows,
        "columns": columns,
        "margin_left": 5.0,
        "margin_top": 5.0,
        "horizontal_pitch": 45.0,
        "vertical_pitch": 25.0,
    }


def ops(document_: dict[str, Any]) -> tuple[Any, ...]:
    """Every operation of the document's first page body."""

    (page,) = output.display_pages(document_)
    (body,) = page.bodies
    return body.ops


def test_page_absolute_document_paints_one_body_over_the_whole_page() -> None:
    (page,) = output.display_pages(document([rect("probe", fill_color="#000000")]))
    assert (page.box.width, page.box.height) == (90.0, 29.0)
    (body,) = page.bodies
    assert body.clip == page.box
    assert len(body.ops) == 1


def test_stock_grid_paints_one_body_at_each_record_frame() -> None:
    spec = document(
        [rect("probe", fill_color="#000000")],
        width=100.0,
        height=60.0,
        stock=stock(),
        data=[{"n": 1}, {"n": 2}],
    )
    (page,) = output.display_pages(spec)
    assert [(body.clip.x, body.clip.y) for body in page.bodies] == [(5.0, 5.0), (50.0, 5.0)]
    assert page.bodies[1].ops[0].matrix.e == 50.0
    assert page.bodies[1].ops[0].matrix.f == 5.0


def test_more_records_than_frames_adds_a_page() -> None:
    spec = document(
        [rect("probe", fill_color="#000000")],
        width=100.0,
        height=60.0,
        stock=stock(2, 2),
        data=[{"n": index} for index in range(5)],
    )
    pages = output.display_pages(spec)
    assert [len(page.bodies) for page in pages] == [4, 1]


def test_frames_without_a_record_paint_nothing() -> None:
    spec = document(
        [rect("probe", fill_color="#000000")],
        width=100.0,
        height=60.0,
        stock=stock(2, 2),
        data=[{"n": 1}, {"n": 2}],
    )
    (page,) = output.display_pages(spec)
    assert len(page.bodies) == 2


def test_no_records_still_render_the_sheet_with_every_frame_empty() -> None:
    spec = document([rect("probe", fill_color="#000000")], width=100.0, height=60.0, stock=stock())
    (page,) = output.display_pages(spec)
    assert page.bodies == ()
    assert (page.box.width, page.box.height) == (100.0, 60.0)


def test_text_baseline_follows_valign() -> None:
    size = 10.0 * 25.4 / 72.0
    top = ops(document([text("run", "A")]))
    middle = ops(document([text("run", "A", width=30.0, height=10.0, valign="middle")]))
    bottom = ops(document([text("run", "A", width=30.0, height=10.0, valign="bottom")]))
    assert top[0].baseline == pytest.approx(output.ASCENT * size)
    assert middle[0].baseline == pytest.approx((10.0 - size) / 2.0 + output.ASCENT * size)
    assert bottom[0].baseline == pytest.approx(10.0 - output.DESCENT * size)
    assert middle[0].size == pytest.approx(size)


def test_text_keeps_its_content_and_base_fourteen_face() -> None:
    (run,) = ops(document([text("run", "SHIP TO:", font_weight="bold", color="#333333")]))
    assert isinstance(run, Text)
    assert (run.content, run.font) == ("SHIP TO:", "Helvetica-Bold")
    assert run.size == pytest.approx(10.0 * 25.4 / 72.0)
    assert run.baseline == pytest.approx(output.ASCENT * run.size)
    assert run.colour.space == "rgb"
    assert run.colour.values == pytest.approx((0.2, 0.2, 0.2))


@pytest.mark.parametrize(
    ("family", "weight", "style", "expected"),
    [
        (None, "normal", "normal", "Helvetica"),
        ("Helvetica", "bold", "normal", "Helvetica-Bold"),
        ("helvetica", "normal", "italic", "Helvetica-Oblique"),
        ("Helvetica", "bold", "oblique", "Helvetica-BoldOblique"),
        ("Times", "normal", "normal", "Times-Roman"),
        ("Times", "bold", "italic", "Times-BoldItalic"),
        ("Courier", "bold", "normal", "Courier-Bold"),
        ("Inter", "normal", "normal", "Helvetica"),
    ],
)
def test_font_name_maps_the_standard_stack(
    family: str | None, weight: str, style: str, expected: str
) -> None:
    assert output.font_name(family, weight, style) == expected


@pytest.mark.parametrize(
    ("value", "space", "expected"),
    [
        ("#0066cc", "rgb", (0.0, 0.4, 0.8)),
        ("#06c", "rgb", (0.0, 0.4, 0.8)),
        ("rgb(0, 102, 204)", "rgb", (0.0, 0.4, 0.8)),
        ("#000000", "cmyk", (0.0, 0.0, 0.0, 1.0)),
        ("#ff0000", "cmyk", (0.0, 1.0, 1.0, 0.0)),
        ("#ffffff", "grayscale", (1.0,)),
        ("#000000", "grayscale", (0.0,)),
    ],
)
def test_colour_resolves_every_section_7_3_form(
    value: str, space: str, expected: tuple[float, ...]
) -> None:
    resolved = output.colour(value, space)
    assert resolved.space == space
    assert resolved.values == pytest.approx(expected)


def test_colour_keeps_the_alpha_of_eight_digit_hex_and_rgba() -> None:
    assert output.colour("#00000080").alpha == pytest.approx(128 / 255)
    assert output.colour("rgba(0, 102, 204, 0.5)").alpha == 0.5
    assert output.colour("rgb(0, 102, 204)").alpha == 1.0


def test_grayscale_uses_the_documented_luma() -> None:
    assert output.colour("#808080", "grayscale").values[0] == pytest.approx(128 / 255)


@pytest.mark.parametrize("value", ["none", "#GGG", "rgb(1, 2)", "hsl(0, 0%, 0%)", "#000000x"])
def test_malformed_colours_are_reported(value: str) -> None:
    with pytest.raises(output.OutputError):
        output.colour(value)


def test_fill_and_stroke_are_separate_operations() -> None:
    obj = rect("probe", fill_color="#ff0000", stroke_color="#000000", stroke_width=0.5)
    drawn = ops(document([obj]))
    assert [type(op) for op in drawn] == [Fill, Stroke]
    assert drawn[1].width == 0.5


def test_a_none_colour_paints_nothing() -> None:
    assert ops(document([rect("probe", fill_color="none", stroke_color="none")])) == ()


def test_a_path_object_paints_its_svg_commands() -> None:
    path = {"id": "probe", "type": "path", "d": "M 0 0 L 10 10", "stroke_color": "#000000"}
    (drawn,) = ops(document([path]))
    assert isinstance(drawn, Stroke)
    assert drawn.subpaths[0].end == (10.0, 10.0)


@pytest.mark.parametrize(
    "obj",
    [
        {
            "id": "probe",
            "type": "barcode",
            "content": "ABC",
            "symbology": "code128",
            "width": 20.0,
            "height": 8.0,
        },
        {"id": "probe", "type": "qrcode", "content": "x", "size": 10.0},
    ],
)
def test_code_objects_are_reported(obj: dict[str, Any]) -> None:
    with pytest.raises(output.OutputError, match="R2/R3"):
        ops(document([obj]))


def test_alignment_and_wrapping_are_reported() -> None:
    with pytest.raises(output.OutputError, match="align"):
        ops(document([text("run", "x", width=20.0, align="center")]))
    with pytest.raises(output.OutputError, match="wrap"):
        ops(document([text("run", "x", width=20.0, wrap=True)]))


def test_a_registered_family_is_embedded_as_a_pdf_subset() -> None:
    pdf = output.artifact(embedded([text("run", "AB", font_family="Probe Sans")]))
    assert b"/FontFile2" in pdf
    assert b"/Subtype /CIDFontType2" in pdf
    assert b"/Encoding /Identity-H" in pdf
    assert b"/CIDToGIDMap /Identity" in pdf
    assert re.search(rb"/BaseFont /[A-Z]{6}\+ProbeSans-Regular", pdf)
    assert b"<00010002> Tj" in _content(pdf)


def test_a_to_unicode_cmap_splits_blocks_of_at_most_one_hundred() -> None:
    cids = {chr(0x20 + index): index + 1 for index in range(150)}
    face = Face(name="ProbeSans-Regular", tag="ABCDEF", subset=b"\0", cids=cids)
    cmap = pdf._to_unicode(face)
    assert re.findall(r"^(\d+) beginbfchar$", cmap, re.MULTILINE) == ["100", "50"]
    assert cmap.count("endbfchar") == 2
    assert cmap.count("<0001> <0020>") == 1
    empty = pdf._to_unicode(Face(name="ProbeSans-Regular", tag="ABCDEF", subset=b"\0"))
    assert "0 beginbfchar" in empty


def test_the_pdf_embeds_only_the_glyphs_the_document_uses() -> None:
    pdf = output.artifact(embedded([text("run", "AB", font_family="Probe Sans")]))
    start = pdf.index(b"stream\n", pdf.index(b"/Length1")) + len(b"stream\n")
    end = pdf.index(b"\nendstream", start)
    subset = fonts.Sfnt(zlib.decompress(pdf[start:end]))
    assert subset.glyph_count == 3  # .notdef, A and B
    assert len(zlib.decompress(pdf[start:end])) < len(FONT.read_bytes())


def test_postscript_embeds_the_registered_face_as_type_42() -> None:
    program = output.artifact(
        embedded([text("run", "AB", font_family="Probe Sans")]), format="postscript"
    )
    assert b"/FontType 42" in program
    assert b"/FontMatrix [1 0 0 1 0 0] def" in program
    assert b"/sfnts [" in program
    assert b"/CharStrings 3 dict" in program
    assert b"/.notdef 0 def" in program
    assert b"dup 65 /c65 put" in program and b"dup 66 /c66 put" in program
    assert b"/c65 2 def" in program and b"/c66 3 def" in program
    assert re.search(rb"/[A-Z]{6}\+ProbeSans-Regular findfont", program)


def test_the_postscript_sfnts_strings_carry_the_pad_byte() -> None:
    program = output.artifact(
        embedded([text("run", "AB", font_family="Probe Sans")]), format="postscript"
    )
    strings = re.findall(rb"<([0-9A-F]+)>", program)
    assert strings
    # An odd byte count, so the hex digit count is two more than a multiple of four.
    assert all(len(value) % 4 == 2 for value in strings)


def test_the_type_42_font_box_is_in_the_font_units() -> None:
    face = Face(
        name="Wide",
        tag="ABCDEF",
        subset=b"\0",
        program=b"\0\0",
        units_per_em=2048,
        bbox=(-100, -200, 1000, 900),
    )
    assert "/FontBBox [-205 -410 2048 1843] def" in "\n".join(postscript._type42(face))


def test_two_variants_of_one_program_define_one_postscript_face() -> None:
    variants = [
        {"style": "normal", "weight": "normal", "source": font_uri()},
        {"style": "normal", "weight": "bold", "source": font_uri()},
    ]
    spec = document(
        [
            text("plain", "AB", font_family="Probe Sans"),
            text("bold", "BA", font_family="Probe Sans", font_weight="bold"),
        ],
        fonts=[{"family": "Probe Sans", "variants": variants}],
    )
    program = output.artifact(spec, format="postscript")
    assert program.count(b"/FontType 42") == 1


def test_embed_fonts_false_is_rejected_for_a_registered_face() -> None:
    spec = embedded([text("run", "A", font_family="Probe Sans")])
    spec["output"] = {"embed_fonts": False}
    with pytest.raises(output.OutputError, match="RO-104"):
        output.artifact(spec)


def test_a_character_the_face_lacks_is_reported() -> None:
    with pytest.raises(output.OutputError, match="no glyph"):
        output.artifact(embedded([text("run", "Z", font_family="Probe Sans")]))


def test_a_remote_font_source_is_reported() -> None:
    spec = document(
        [text("run", "A", font_family="Probe Sans")],
        fonts=[
            {
                "family": "Probe Sans",
                "variants": [
                    {
                        "style": "normal",
                        "weight": "normal",
                        "source": "https://example.org/probe.ttf",
                    }
                ],
            }
        ],
    )
    with pytest.raises(output.OutputError, match="remote"):
        output.artifact(spec)


def test_the_closest_variant_is_selected_deterministically() -> None:
    variants = [
        {"style": "normal", "weight": "normal", "source": font_uri()},
        {"style": "normal", "weight": "bold", "source": font_uri()},
    ]
    spec = document(
        [text("run", "A", font_family="Probe Sans", font_weight="700")],
        fonts=[{"family": "Probe Sans", "variants": variants}],
    )
    (bold,) = ops(spec)
    assert bold.font == "Probe Sans normal bold"

    spec = document(
        [text("run", "A", font_family="Probe Sans", font_weight="500")],
        fonts=[{"family": "Probe Sans", "variants": variants}],
    )
    (normal,) = ops(spec)
    assert normal.font == "Probe Sans normal normal"


def test_content_outside_winansi_is_reported() -> None:
    with pytest.raises(output.OutputError, match="WinAnsi"):
        ops(document([text("run", "\u4f60\u597d")]))


def test_the_output_format_defaults_to_pdf_and_rejects_anything_else() -> None:
    assert output.artifact(document([rect("probe", fill_color="#000000")])).startswith(b"%PDF-1.4")
    with pytest.raises(output.OutputError, match="output format"):
        output.artifact(document([]), format="svg")


def test_an_invalid_document_raises_before_an_artifact_exists() -> None:
    with pytest.raises(renderspec.RenderSpecError):
        output.artifact({"renderspec": "1.0", "id": "broken"})


def test_postscript_refuses_transparency() -> None:
    faded = document(
        [rect("probe", fill_color="#000000")],
    )
    faded["layers"][0]["opacity"] = 0.5
    with pytest.raises(output.OutputError, match="transparency"):
        output.artifact(faded, format="postscript")
    assert output.artifact(faded).startswith(b"%PDF-1.4")


def _media_box(pdf: bytes) -> tuple[float, float]:
    match = re.search(rb"/MediaBox \[0 0 ([0-9.]+) ([0-9.]+)\]", pdf)
    assert match is not None
    return (float(match.group(1)) * 25.4 / 72.0, float(match.group(2)) * 25.4 / 72.0)


def _content(pdf: bytes) -> bytes:
    start = pdf.index(b"stream\n") + len(b"stream\n")
    end = pdf.index(b"\nendstream", start)
    return zlib.decompress(pdf[start:end])


def _object_offsets(pdf: bytes) -> dict[int, int]:
    start = int(re.search(rb"startxref\n(\d+)\n", pdf).group(1))
    table = pdf[start:].split(b"\n")
    count = int(table[1].split()[1])
    return {ordinal: int(table[2 + ordinal].split()[0]) for ordinal in range(1, count)}


def test_pdf_page_size_is_the_declared_page() -> None:
    pdf = output.artifact(document([rect("probe", fill_color="#000000")]))
    width, height = _media_box(pdf)
    assert width == pytest.approx(90.0, abs=0.01)
    assert height == pytest.approx(29.0, abs=0.01)


def test_pdf_is_deterministic_and_carries_no_timestamp_or_identifier() -> None:
    spec = document([rect("probe", fill_color="#000000"), text("run", "Probe")])
    pdf = output.artifact(spec)
    assert pdf == output.artifact(spec)
    assert pdf.startswith(b"%PDF-1.4")
    assert b"/CreationDate" not in pdf
    assert b"/ModDate" not in pdf
    assert b"/ID" not in pdf[pdf.rindex(b"endstream") :]


def test_pdf_places_every_operation_through_its_matrix() -> None:
    spec = document(
        [
            rect("box", x=10.0, y=5.0, fill_color="#000000"),
            text("run", "Hi", x=12.0, y=6.0),
        ]
    )
    content = _content(output.artifact(spec))
    assert b"1 0 0 1 10 5 cm" in content
    assert b"1 0 0 1 12 6 cm" in content


def test_pdf_resources_name_the_fonts_and_alphas_the_stream_uses() -> None:
    spec = document([text("run", "Hi")])
    spec["layers"][0]["opacity"] = 0.5
    pdf = output.artifact(spec)
    assert b"/Font << /F1 " in pdf
    assert b"/ExtGState << /GS1 " in pdf
    content = _content(pdf)
    assert b"/F1 " in content
    assert b"/GS1 gs" in content


def test_pdf_xref_offsets_point_at_their_objects() -> None:
    pdf = output.artifact(document([rect("probe", fill_color="#000000")]))
    offsets = _object_offsets(pdf)
    assert len(offsets) == 4
    for ordinal, offset in offsets.items():
        assert pdf[offset:].startswith(f"{ordinal} 0 obj".encode("ascii"))


def test_pdf_compresses_streams_unless_asked_not_to() -> None:
    spec = document([text("run", "Probe")])
    assert b"/Filter /FlateDecode" in output.artifact(spec)
    plain = output.artifact({**spec, "output": {"format": "pdf", "compress": False}})
    assert b"/Filter" not in plain
    drawn = plain.split(b"stream\n", 1)[1].split(b"\nendstream", 1)[0]
    assert b"BT" in drawn and b"Tj" in drawn and b" re W n" in drawn
    assert b"/Subtype /Image" not in plain
    assert _content(output.artifact(spec)) == drawn


def test_postscript_program_is_deterministic_and_page_sized() -> None:
    spec = document([rect("probe", fill_color="#000000"), text("run", "Probe")])
    program = output.artifact(spec, format="postscript")
    assert program == output.artifact(spec, format="postscript")
    assert program.startswith(b"%!PS-Adobe-3.0")
    assert b"%%BoundingBox: 0 0 256 83" in program
    assert b"%%Pages: 1" in program
    assert b"%%CreationDate" not in program
    assert b"setpagedevice" in program
    assert program.count(b"showpage") == 1
    assert b"show" in program and b"rectclip" in program


def test_postscript_restores_the_page_transform_on_every_page() -> None:
    spec = document(
        [rect("probe", fill_color="#000000")],
        width=100.0,
        height=60.0,
        stock=stock(2, 2),
        data=[{"n": index} for index in range(5)],
    )
    program = output.artifact(spec, format="postscript")
    scale = postscript.number(postscript.SCALE)
    transform = f"[{scale} 0 0 -{scale}".encode("ascii")
    assert program.count(transform) == 2
    for chunk in program.split(b"%%Page: ")[1:]:
        assert transform in chunk


def test_postscript_reencodes_text_to_winansi() -> None:
    program = output.artifact(document([text("run", "M\u00fcnchen")]), format="postscript")
    assert b"/Helvetica findfont dup length dict begin" in program
    assert b"/Encoding 256 array" in program
    assert b"dup 77 /M put" in program
    assert b"dup 252 /udieresis put" in program
    assert b"WinAnsiEncoding" not in program
    assert b"currentdict end /Helvetica-WinAnsi exch definefont pop" in program
    assert b"/Helvetica-WinAnsi findfont" in program
    assert b"(M\xfcnchen) show" in program


def test_a_stock_document_writes_one_page_per_record_grid() -> None:
    spec = document(
        [rect("probe", fill_color="#000000")],
        width=100.0,
        height=60.0,
        stock=stock(2, 2),
        data=[{"n": index} for index in range(5)],
    )
    assert output.artifact(spec).count(b"/Type /Page ") == 2
    assert output.artifact(spec, format="postscript").count(b"showpage") == 2


def test_a_stock_body_clips_to_its_frame() -> None:
    spec = document(
        [rect("probe", fill_color="#000000")],
        width=100.0,
        height=60.0,
        stock=stock(),
        data=[{"n": 1}],
    )
    (page,) = output.display_pages(spec)
    assert page.bodies[0].clip == Box(5.0, 5.0, 40.0, 20.0)


def image(asset_id: str = "mark", **props: Any) -> dict[str, Any]:
    return {
        "id": "photo",
        "type": "image",
        "x": 4.0,
        "y": 4.0,
        "asset_id": asset_id,
        "width": 40.0,
        "height": 16.0,
        **props,
    }


def picture_spec(*, asset_type: str = "jpeg", source: Path | None = None, **props: Any):
    return document(
        [image(**props)],
        assets=[{"id": "mark", "type": asset_type, "source": str(source or JPEG)}],
    )


def test_pdf_carries_a_jpeg_as_its_own_dct_stream() -> None:
    pdf_bytes = output.artifact(picture_spec())
    assert b"/DCTDecode" in pdf_bytes
    assert b"/Subtype /Image /Width 16 /Height 8" in pdf_bytes
    assert b"/ColorSpace /DeviceRGB" in pdf_bytes
    assert JPEG.read_bytes() in pdf_bytes
    assert b"/XObject << /Im1" in pdf_bytes
    assert b"/Im1 Do" in _content(pdf_bytes)
    assert pdf_bytes == output.artifact(picture_spec())


def test_pdf_carries_a_png_with_the_png_predictor() -> None:
    pdf_bytes = output.artifact(picture_spec(source=PNG))
    assert b"/Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns 16" in pdf_bytes
    assert b"/Filter /FlateDecode" in pdf_bytes
    assert b"DCTDecode" not in pdf_bytes
    assert assets.picture(str(PNG)).data in pdf_bytes


def test_preserve_aspect_ratio_fits_and_centres_the_picture() -> None:
    (page,) = output.display_pages(picture_spec(source=PNG))
    (drawn,) = [op for op in page.bodies[0].ops if isinstance(op, Image)]
    assert (drawn.width, drawn.height) == (32.0, 16.0)
    assert (drawn.matrix.e, drawn.matrix.f) == (8.0, 4.0)


def test_a_picture_stretches_when_preserve_aspect_ratio_is_false() -> None:
    (page,) = output.display_pages(picture_spec(source=PNG, preserve_aspect_ratio=False))
    (drawn,) = [op for op in page.bodies[0].ops if isinstance(op, Image)]
    assert (drawn.width, drawn.height) == (40.0, 16.0)
    assert (drawn.matrix.e, drawn.matrix.f) == (4.0, 4.0)


def test_an_unregistered_asset_is_reported() -> None:
    with pytest.raises(output.OutputError, match="not registered"):
        output.artifact(document([image()]))


def test_an_svg_asset_is_reported() -> None:
    spec = document([image()], assets=[{"id": "mark", "type": "svg", "source": "mark.svg"}])
    with pytest.raises(output.OutputError, match="SVG"):
        output.artifact(spec)


def test_postscript_carries_a_jpeg_and_refuses_a_png() -> None:
    program = output.artifact(picture_spec(), format="postscript")
    assert b"%%DocumentData: Binary" in program
    assert b"/DataSource currentfile /DCTDecode filter >> image" in program
    assert JPEG.read_bytes() in program
    assert b"%%DocumentData" not in output.artifact(document([rect("probe")]))

    with pytest.raises(output.OutputError, match="PNG"):
        output.artifact(picture_spec(source=PNG), format="postscript")
