"""Registry of shapes the runner can trace.

The registry is auto-discovered from `prototype/`:

* `<name>_shape.py` — a single canonical shape (the live route generator
  uses these). Must export `<NAME>_OUTLINE: List[Point]`.
* `<name>_candidate_<n>.py` — design candidates for picking among. Must
  export `OUTLINE: List[Point]` and may export `INTERIOR_FEATURES: List[List[Point]]`
  and `METADATA: dict`.

Adding a new shape (animal, heart, star, letter, landmark — anything) is just:
1. Drop the SVG into `prototype/svg_sources/`.
2. Run `tools/svg_to_shape.py --with-interior --output prototype/<name>_shape.py`.
3. The registry picks it up automatically.

No animal-specific code lives here — every shape is treated uniformly.
"""

from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

from shape_utils import Point, compose_route

PROTO_DIR = Path(__file__).resolve().parent

# Make sure imports of sibling modules (cat_shape, etc.) work whether or not
# the caller has already configured sys.path.
if str(PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(PROTO_DIR))


class Shape(NamedTuple):
    """A registered shape ready to be traced.

    `route` is the composed polyline (outline + interior detours) — this is
    what the route generator hands to the routing engine. `outline` and
    `interior_features` are kept separately for previews and editing.
    """
    name: str               # e.g. "pig" or "pig_candidate_3"
    family: str             # e.g. "pig" — useful for grouping candidates by source
    outline: List[Point]
    interior_features: List[List[Point]]
    route: List[Point]
    metadata: dict


_CANDIDATE_RE = re.compile(r"^(?P<family>[a-z0-9]+)_candidate_(?P<n>\d+)\.py$")
_SHAPE_RE = re.compile(r"^(?P<family>[a-z0-9]+)_shape\.py$")


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _shape_from_module(mod, name: str, family: str) -> Optional[Shape]:
    """Try the standardized OUTLINE / INTERIOR_FEATURES / METADATA interface
    first, then fall back to the legacy `<FAMILY>_OUTLINE` variable."""
    outline = getattr(mod, "OUTLINE", None)
    if outline is None:
        outline = getattr(mod, f"{family.upper()}_OUTLINE", None)
    if outline is None:
        return None
    interior = getattr(mod, "INTERIOR_FEATURES", []) or []
    metadata = getattr(mod, "METADATA", {}) or {}
    route = compose_route(outline, interior)
    return Shape(
        name=name,
        family=family,
        outline=list(outline),
        interior_features=[list(f) for f in interior],
        route=route,
        metadata=dict(metadata),
    )


def discover_shapes() -> Dict[str, Shape]:
    """Walk `prototype/` and register every `_shape.py` and `_candidate_N.py`
    file. Returns a dict keyed by shape name."""
    out: Dict[str, Shape] = {}
    for path in sorted(PROTO_DIR.glob("*.py")):
        m = _CANDIDATE_RE.match(path.name)
        if m:
            family = m.group("family")
            n = m.group("n")
            mod = _load_module(path)
            if mod is None:
                continue
            shape = _shape_from_module(mod, f"{family}_candidate_{n}", family)
            if shape is not None:
                out[shape.name] = shape
            continue
        m = _SHAPE_RE.match(path.name)
        if m:
            family = m.group("family")
            mod = _load_module(path)
            if mod is None:
                continue
            shape = _shape_from_module(mod, family, family)
            if shape is not None:
                out[shape.name] = shape
    return out


# Eagerly discover at import time so callers can do `from shapes import SHAPES`.
SHAPES_FULL: Dict[str, Shape] = discover_shapes()

# Backwards-compatible flat dict[name → outline polyline] for existing callers
# (route generator etc.) that just want the traced polyline. Uses the composed
# route (outline + interior detours) so interior features actually get drawn.
SHAPES: Dict[str, List[Point]] = {name: s.route for name, s in SHAPES_FULL.items()}
