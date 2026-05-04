"""Registry mapping shape names → outline polylines.

Two views on the same registry:

- ``SHAPES``      — ``Dict[str, List[Point]]``: the single canonical
                    outline per animal. Source of truth for legacy
                    callers (CLI, Phase-1 generate / generate_v2).
- ``SHAPE_VARIANTS`` — ``Dict[str, List[List[Point]]]``: a list of
                    outlines per animal, with the canonical outline
                    first and Quick Draw! exemplars appended (when the
                    auto-generated module exists). Phase-2/3 search
                    iterates over this list to pick the variant that
                    best fits the local street grid.

To add a new animal:
1. Create ``<name>_shape.py`` exporting ``<NAME>_OUTLINE: List[Point]``.
2. Import it here and add an entry to SHAPES.
3. (Optional) Run ``tools/quickdraw_to_shape.py <name>`` to populate
   ``prototype/quickdraw_variants/<name>_quickdraw.py``.
"""

from __future__ import annotations

from typing import Dict, List

from cat_shape import CAT_OUTLINE
from chicken_shape import CHICKEN_OUTLINE
from dino_shape import DINO_OUTLINE
from dog_shape import DOG_OUTLINE
from pig_shape import PIG_OUTLINE
from shape_utils import Point

SHAPES: Dict[str, List[Point]] = {
    "pig": PIG_OUTLINE,
    "cat": CAT_OUTLINE,
    "dog": DOG_OUTLINE,
    "dino": DINO_OUTLINE,
    "chicken": CHICKEN_OUTLINE,
}


def _load_quickdraw_variants(animal: str) -> List[List[Point]]:
    """Best-effort import of the auto-generated Quick Draw module for an
    animal. Returns an empty list if the module hasn't been generated yet
    (the curation tool is opt-in)."""
    try:
        mod = __import__(f"quickdraw_variants.{animal}_quickdraw",
                         fromlist=[f"{animal.upper()}_QUICKDRAW"])
        return list(getattr(mod, f"{animal.upper()}_QUICKDRAW", []))
    except ImportError:
        return []


SHAPE_VARIANTS: Dict[str, List[List[Point]]] = {
    name: [outline] + _load_quickdraw_variants(name)
    for name, outline in SHAPES.items()
}
