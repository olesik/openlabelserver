"""Layer and object composition (RenderSpec Sections 6, 8.1 and 9).

Section 6 makes `layers` an ordered list: index 0 is drawn first as the
background, the last index last. A layer `visible` defaults to `true` and a
`false` value means none of its objects is drawn (`RT-107`); a layer `opacity`
multiplies every element of the layer recursively (`RT-108`).

Section 8.1 gives every `RenderObject` the same `visible`, `opacity`, `x`, `y`,
`rotation`, `scale_x`, `scale_y` and `transforms` properties, and Section 8.2.12
makes `group` a container that applies its own transform, visibility and opacity
to its children. Section 9 composes one matrix per object:

    M = M_parent x T(x, y) x R(rotation) x S(scale_x, scale_y) x M_custom

`M_custom` is the cumulative product of the `transforms` array, so each entry is
expressed in the frame the previous entries establish and the last entry acts on
the object's own coordinates first (`RT-111`).

`draw_list` walks the layers in draw order and returns one `Drawn` per object an
output backend must paint, carrying its Section 9 matrix and its effective alpha:
the product of the layer, its ancestor groups and its own opacity (`RT-108`). A
hidden layer, group or object contributes nothing rather than a transparent entry
(`RT-107`). Matrices come from `renderer.coordinates` and page placement, bounds
and clipping from `renderer.layout` and `renderer.clip`, so `RT-109`-`RT-112`
follow from one implementation each; this module describes one body, and a
stock-grid document repeats that list once per frame.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from renderer.coordinates import IDENTITY, Affine, object_matrix


@dataclass(frozen=True)
class Drawn:
    """One object to paint, with its place in the document and its alpha."""

    path: str
    object: Mapping[str, Any]
    matrix: Affine
    alpha: float


def _hidden(value: Mapping[str, Any]) -> bool:
    """Section 6 and 8.1: visibility defaults to `true`; only `false` hides."""

    return value.get("visible", True) is False


def _opacity(value: Mapping[str, Any]) -> float:
    """Section 6 and 8.1: opacity defaults to `1.0`."""

    return float(value.get("opacity", 1.0))


def _collect(
    objects: Iterable[Mapping[str, Any]], path: str, parent: Affine, alpha: float
) -> Iterator[Drawn]:
    """Yield the drawn children of `objects`, groups in place of their children."""

    for index, obj in enumerate(objects):
        if _hidden(obj):
            continue
        child = f"{path}.{index}"
        matrix = object_matrix(obj, parent)
        alpha_here = alpha * _opacity(obj)
        if obj.get("type") == "group":
            yield from _collect(obj.get("objects") or (), f"{child}.objects", matrix, alpha_here)
        else:
            yield Drawn(path=child, object=obj, matrix=matrix, alpha=alpha_here)


def draw_list(document: Mapping[str, Any]) -> tuple[Drawn, ...]:
    """Every object to paint, in layer and then object order (Sections 6, 8.1, 9).

    Layers and objects are emitted in array order, a group is replaced by its
    children, and hidden layers, groups and objects are omitted (`RT-107`).
    """

    drawn: list[Drawn] = []
    for layer_index, layer in enumerate(document.get("layers") or ()):
        if _hidden(layer):
            continue
        drawn.extend(
            _collect(
                layer.get("objects") or (),
                f"layers.{layer_index}.objects",
                IDENTITY,
                _opacity(layer),
            )
        )
    return tuple(drawn)
