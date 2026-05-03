"""Curate animal outlines from the Google Quick, Draw! dataset.

The dataset publishes one ``simplified.ndjson`` file per category at
``https://storage.googleapis.com/quickdraw_dataset/full/simplified/<animal>.ndjson``
(CC BY 4.0). Each line is one drawing: a list of stroke arrays in a
[0, 255]² coordinate space, already RDP-simplified by Google.

This tool downloads (or reads from disk) the ndjson, filters down to
recognisable single-stroke (or near-single-stroke) drawings of a chosen
size, normalises them to the prototype's (x, y) shape units, and emits
ready-to-import Python files into ``prototype/quickdraw_variants/``.

Usage:

    python tools/quickdraw_to_shape.py pig --n-variants 5
    python tools/quickdraw_to_shape.py cat dog --n-variants 3 --no-download

Run without args to curate all five DoodleRun animals.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import urllib.request
from pathlib import Path
from typing import List, Tuple

# Allow running from anywhere; we want the prototype/simplification helper
# without hard-coding sys.path inside the tool.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "prototype"))

QD_BASE_URL = "https://storage.googleapis.com/quickdraw_dataset/full/simplified"
DATA_DIR = ROOT / "prototype" / "quickdraw_data"
OUT_DIR = ROOT / "prototype" / "quickdraw_variants"
DEFAULT_ANIMALS = ["pig", "cat", "dog", "dino", "chicken"]

# DoodleRun's `dino` and `chicken` aren't Quick Draw categories. We
# substitute the closest large-silhouette match: dragon for the lizardy
# four-legged thing, bird for chicken. The mapping is data-driven so
# anyone scanning sample outlines knows where they came from.
QD_CATEGORY_ALIASES = {
    "dino": "dragon",
    "dinosaur": "dragon",
    "chicken": "bird",
}

# Filtering knobs — tuned from a quick scan of the pig file:
#   stroke_count <= 2                 — single-line outlines beat multi-stroke faces
#   point_count   in [25, 80]         — too few = blocky; too many = scribbles
#   path_length   in 25th-75th pct    — drop outliers
# With multi-stroke drawings concatenated, most animals have 30-200 points
# total. The 8-stroke cap is permissive but keeps out the busy "body + 4
# legs + 2 ears + eye + tail + smile" sketches that don't read as outlines.
DEFAULT_MIN_POINTS = 30
DEFAULT_MAX_POINTS = 200
DEFAULT_MAX_STROKES = 8

XY = Tuple[float, float]


def fetch_ndjson(animal: str, *, force_download: bool = False) -> Path:
    """Download (once) the simplified ndjson for an animal class.

    The full files are 75K-100K samples; we cap downloads at 10 MiB so we
    don't pull the whole thing for what is effectively a curation pass.
    Categories with no Quick Draw match are aliased — see
    ``QD_CATEGORY_ALIASES``.
    """
    qd_cat = QD_CATEGORY_ALIASES.get(animal, animal)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = DATA_DIR / f"{animal}.ndjson"
    if target.exists() and not force_download:
        return target
    url = f"{QD_BASE_URL}/{qd_cat}.ndjson"
    if qd_cat != animal:
        print(f"  ({animal!r} aliased → Quick Draw {qd_cat!r})")
    print(f"  downloading {url} → {target}")
    # Stream + cap at ~10 MiB. The first ~5K samples are plenty.
    cap_bytes = 10 * 1024 * 1024
    req = urllib.request.Request(url, headers={"User-Agent": "DoodleRun-curate/0.1"})
    with urllib.request.urlopen(req) as r, open(target, "wb") as f:
        written = 0
        while written < cap_bytes:
            chunk = r.read(64 * 1024)
            if not chunk:
                break
            f.write(chunk)
            written += len(chunk)
    return target


def _strokes_to_polyline(strokes: List[List[List[float]]]) -> List[XY]:
    """Concatenate Quick Draw stroke arrays into one polyline.

    Each stroke is `[xs, ys]`, lists of equal length. We bridge
    consecutive strokes with a short segment from the previous stroke's
    last point to the next stroke's first point. This produces a single
    closed-ish curve that the resampler can handle.
    """
    pts: List[XY] = []
    for stroke in strokes:
        xs, ys = stroke[0], stroke[1]
        for x, y in zip(xs, ys):
            # Quick Draw's y-axis is flipped vs ours: top-left origin.
            pts.append((float(x), 255.0 - float(y)))
    return pts


def _normalise_to_unit(points: List[XY]) -> List[XY]:
    """Centre the polyline in [-0.5, 0.5]² (preserving aspect ratio)."""
    if not points:
        return points
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1.0)
    return [((x - cx) / span, (y - cy) / span) for x, y in points]


def _polyline_length(pts: List[XY]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(pts, pts[1:]))


def _quantile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(round((len(s) - 1) * q))
    return s[idx]


def curate_variants(
    animal: str,
    *,
    n_variants: int = 5,
    min_points: int = DEFAULT_MIN_POINTS,
    max_points: int = DEFAULT_MAX_POINTS,
    max_strokes: int = DEFAULT_MAX_STROKES,
    target_outline_points: int = 40,
    seed: int = 0,
) -> List[List[XY]]:
    """Return ``n_variants`` curated outlines (each a list of (x, y) points
    in centred [-0.5, 0.5] units) for the given animal class."""
    from shape_utils import resample, simplify_vw

    nd_path = fetch_ndjson(animal)
    raw_drawings = []
    with open(nd_path) as f:
        for i, line in enumerate(f):
            try:
                d = json.loads(line)
            except Exception:
                continue
            if not d.get("recognized", False):
                continue
            strokes = d.get("drawing", [])
            if not strokes or len(strokes) > max_strokes:
                continue
            polyline = _strokes_to_polyline(strokes)
            if not (min_points <= len(polyline) <= max_points):
                continue
            raw_drawings.append(polyline)
            if i > 5_000:  # cap for cost
                break

    if not raw_drawings:
        raise RuntimeError(f"No usable Quick Draw samples found for {animal!r}")

    # Drop length outliers (keep middle 50%).
    lengths = [_polyline_length(p) for p in raw_drawings]
    lo = _quantile(lengths, 0.25)
    hi = _quantile(lengths, 0.75)
    keepers = [p for p, L in zip(raw_drawings, lengths) if lo <= L <= hi]
    print(f"  {animal}: {len(raw_drawings)} candidates → {len(keepers)} after length filter")

    rng = random.Random(seed)
    rng.shuffle(keepers)
    picked = keepers[:n_variants]

    out: List[List[XY]] = []
    for raw in picked:
        # Resample to target count, then VW-simplify slightly so adjacent
        # near-duplicate vertices don't bias the routing.
        try:
            resampled = resample(raw, target_outline_points)
        except Exception:
            continue
        simplified = simplify_vw(resampled, target_count=target_outline_points)
        normalised = _normalise_to_unit(simplified)
        out.append(normalised)
    return out


def emit_python_module(animal: str, variants: List[List[XY]]):
    """Write a `<animal>_quickdraw.py` to prototype/quickdraw_variants/.

    Each module exports `<ANIMAL>_QUICKDRAW: List[List[Point]]` — a list
    of outlines. Imported lazily by `shapes.py` (Phase 3 will wire it
    into the multi-variant registry).
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    init = OUT_DIR / "__init__.py"
    if not init.exists():
        init.write_text('"""Auto-generated Quick Draw! variants. See tools/quickdraw_to_shape.py."""\n')

    module_path = OUT_DIR / f"{animal}_quickdraw.py"
    lines = [
        '"""Auto-generated Quick Draw! variants for {0}.',
        '',
        'Source: Google Quick, Draw! dataset (CC BY 4.0).',
        'Curated by tools/quickdraw_to_shape.py — do not hand-edit.',
        '"""',
        '',
        'from __future__ import annotations',
        '',
        'from typing import List, Tuple',
        '',
        'Point = Tuple[float, float]',
        '',
        f'{animal.upper()}_QUICKDRAW: List[List[Point]] = [',
    ]
    for variant in variants:
        lines.append('    [')
        for x, y in variant:
            lines.append(f'        ({x:.5f}, {y:.5f}),')
        lines.append('    ],')
    lines.append(']')
    lines.append('')
    module_path.write_text('\n'.join(lines).format(animal))
    print(f"  wrote {module_path.relative_to(ROOT)}  ({len(variants)} variants)")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("animals", nargs="*", default=DEFAULT_ANIMALS,
                   help=f"Animal class names (default: {DEFAULT_ANIMALS})")
    p.add_argument("--n-variants", type=int, default=5,
                   help="Variants per animal (default 5)")
    p.add_argument("--target-points", type=int, default=40,
                   help="Resample each curated outline to this many points")
    p.add_argument("--no-download", action="store_true",
                   help="Skip download even if ndjson is missing — fail loud instead")
    return p.parse_args()


def main():
    args = parse_args()
    for animal in args.animals:
        print(f"\n[{animal}]")
        if args.no_download and not (DATA_DIR / f"{animal}.ndjson").exists():
            raise FileNotFoundError(
                f"prototype/quickdraw_data/{animal}.ndjson missing and --no-download set"
            )
        variants = curate_variants(animal,
                                   n_variants=args.n_variants,
                                   target_outline_points=args.target_points)
        emit_python_module(animal, variants)


if __name__ == "__main__":
    main()
