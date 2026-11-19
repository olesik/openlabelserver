"""Tests for `renderer/clip.py`: the declared label shape decides the clip."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from renderer import clip, layout  # noqa: E402

TOLERANCE = 1e-9
EXAMPLES = ROOT / "specs" / "stockspec" / "examples"


def box(width: float, height: float, x: float = 0.0, y: float = 0.0) -> layout.Box:
    return layout.Box(x, y, width, height)


def stock(shape: str | None = None, **label: float) -> dict:
    result = {
        "stockspec": "1.0",
        "metadata": {"id": "probe", "name": "Probe"},
        "page": {"width": 100.0, "height": 100.0},
        "label": {"width": 80.0, "height": 60.0},
        "grid": {"rows": 1, "columns": 1},
        "margins": {"left": 10.0, "top": 10.0},
        "pitch": {"horizontal": 80.0, "vertical": 60.0},
    }
    result["label"].update(label)
    if shape is not None:
        result["label"]["shape"] = shape
    return result


def test_rectangle_clips_to_the_bounding_box() -> None:
    region = clip.label_clip(box(80.0, 60.0))
    for corner in ((0.0, 0.0), (80.0, 0.0), (80.0, 60.0), (0.0, 60.0)):
        assert region.contains(corner)
    assert not region.contains((-0.5, 30.0))
    assert not region.contains((40.0, 60.5))


def test_rounded_rectangle_cuts_each_corner_at_the_radius() -> None:
    region = clip.label_clip(box(80.0, 60.0), shape="rounded-rectangle", corner_radius=6.0)
    # Inside the arc, on it, and beyond it, measured from the corner centre (6, 6).
    assert region.contains((6.0 - 4.2, 6.0 - 4.2))
    assert region.contains((6.0 - 6.0, 6.0))
    assert not region.contains((0.5, 0.5))
    assert region.contains((6.0, 0.5))
    assert region.contains((40.0, 30.0))


def test_round_clips_to_the_inscribed_circle() -> None:
    region = clip.label_clip(box(50.0, 50.0), shape="round")
    centre = (25.0, 25.0)
    assert region.contains(centre)
    assert region.contains((25.0 + 25.0 * 0.5, 25.0 - 25.0 * 0.7071067811865476 * 0.5))
    assert region.contains((50.0, 25.0))
    assert not region.contains((0.5, 0.5))
    assert not region.contains((43.5, 6.5))


def test_oval_clips_to_the_inscribed_ellipse() -> None:
    region = clip.label_clip(box(80.0, 60.0), shape="oval")
    assert region.contains((40.0, 30.0))
    assert region.contains((40.0 + 40.0 * 0.5, 30.0 - 30.0 * 0.5))
    assert region.contains((40.0, 0.0))
    assert not region.contains((0.5, 0.5))
    assert not region.contains((70.0, 5.0))


def test_an_unknown_shape_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown label shape"):
        clip.label_clip(box(10.0, 10.0), shape="hexagon")


def test_stock_clips_reads_the_published_shape_and_radius() -> None:
    rounded = yaml.safe_load((EXAMPLES / "avery_5160.yaml").read_text(encoding="utf-8"))
    clips = clip.stock_clips(rounded)
    assert len(clips) == 30
    assert {region.shape for region in clips} == {"rounded-rectangle"}
    assert {region.corner_radius for region in clips} == {1.5}
    assert (clips[0].boundary.x, clips[0].boundary.y) == pytest.approx((4.76, 12.7))

    round_stock = yaml.safe_load((EXAMPLES / "round_2inch.yaml").read_text(encoding="utf-8"))
    regions = clip.stock_clips(round_stock)
    assert len(regions) == 15
    assert {region.shape for region in regions} == {"round"}
    assert not regions[0].contains((0.5, 0.5))


def test_a_stock_without_a_shape_clips_as_a_rectangle() -> None:
    clips = clip.stock_clips(stock())
    assert len(clips) == 1
    assert clips[0].shape == "rectangle"
    assert clips[0].contains((10.0, 10.0))
    assert not clips[0].contains((9.5, 10.0))
