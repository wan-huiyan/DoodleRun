"""Registry mapping shape names → outline polylines.

To add a new animal:
1. Create `<name>_shape.py` exporting an `<NAME>_OUTLINE: List[Point]`.
2. Import it here and add an entry to SHAPES.
3. The CLI's `--shape` flag picks up new entries automatically.
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
