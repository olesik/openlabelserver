"""Tests for `renderer/fonts.py`: loading, sfnt parsing and subsetting (RO-104)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from renderer import fonts

FIXTURE = (
    Path(__file__).resolve().parent
    / "conformance"
    / "fixtures"
    / "renderspec"
    / "fonts"
    / "probe.ttf"
)


def program() -> bytes:
    return FIXTURE.read_bytes()


def data_uri() -> str:
    return "data:font/ttf;base64," + base64.b64encode(program()).decode("ascii")


def test_load_reads_a_data_uri_and_a_local_path() -> None:
    assert fonts.load(data_uri()) == program()
    assert fonts.load(str(FIXTURE)) == program()


def test_load_reports_a_remote_source_instead_of_fetching_it() -> None:
    with pytest.raises(fonts.FontError, match="remote"):
        fonts.load("https://example.org/probe.ttf")


def test_load_reports_a_missing_file_and_malformed_base64() -> None:
    with pytest.raises(fonts.FontError, match="cannot be read"):
        fonts.load("no-such-font.ttf")
    with pytest.raises(fonts.FontError, match="base64"):
        fonts.load("data:font/ttf;base64,not base64!")
    with pytest.raises(fonts.FontError, match="base64"):
        fonts.load("data:font/ttf,plain")


def test_metrics_come_from_the_program() -> None:
    sfnt = fonts.Sfnt(program())
    assert sfnt.metrics.units_per_em == 1000
    assert (sfnt.metrics.ascent, sfnt.metrics.descent) == (800, -200)
    assert sfnt.metrics.bbox == (0, 0, 600, 700)
    assert sfnt.metrics.cap_height == 700
    assert sfnt.metrics.postscript_name == "ProbeSans-Regular"
    assert sfnt.metrics.scaled(600) == 600


def test_every_character_maps_to_its_glyph_and_advance() -> None:
    sfnt = fonts.Sfnt(program())
    assert sfnt.glyph_id("A") == 2
    assert sfnt.glyph_id("ü") == 4
    assert sfnt.glyph_id("Z") is None
    assert [sfnt.advance(gid) for gid in range(5)] == [500, 250, 600, 600, 550]


def test_subset_keeps_notdef_and_the_used_glyphs() -> None:
    subset = fonts.Sfnt(program()).subset(["A"])
    assert subset.cids == {"A": 1}
    assert subset.widths[0] == 500
    assert subset.widths[1] == 600


def test_subset_is_smaller_repeatable_and_readable_again() -> None:
    whole = program()
    first = fonts.Sfnt(whole).subset(["A"])
    second = fonts.Sfnt(whole).subset(["A"])
    assert first.program == second.program
    assert first.tag == second.tag
    assert len(first.program) < len(whole)
    assert len(first.tag) == 6 and first.tag.isalpha() and first.tag.isupper()

    reparsed = fonts.Sfnt(first.program)
    assert reparsed.glyph_id("A") == first.cids["A"]
    assert reparsed.advance(first.cids["A"]) == 600


def test_subset_drops_characters_the_font_lacks() -> None:
    subset = fonts.Sfnt(program()).subset(["A", "Z"])
    assert subset.cids == {"A": 1}


def test_cff_and_collection_programs_are_reported() -> None:
    with pytest.raises(fonts.FontError, match="CFF"):
        fonts.Sfnt(b"OTTO" + b"\0" * 60)
    with pytest.raises(fonts.FontError, match="collection"):
        fonts.Sfnt(b"ttcf" + b"\0" * 60)
    with pytest.raises(fonts.FontError, match="TrueType"):
        fonts.Sfnt(b"XXXX" + b"\0" * 60)


def test_a_truncated_program_is_reported() -> None:
    with pytest.raises(fonts.FontError, match="past the end"):
        fonts.Sfnt(program()[:40])
    with pytest.raises(fonts.FontError, match="required table"):
        fonts.Sfnt(b"\x00\x01\x00\x00" + b"\0" * 8)
