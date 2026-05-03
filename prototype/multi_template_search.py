"""Joint search over (template, placement, scale, rotation).

The core hypothesis: a doodle is a *family* of acceptable variants, not a
single fixed polyline. Pick whichever variant fits the local street grid
best at the user's location.

Strategy: two-stage search
  Stage 1 — Wide template scan: each candidate template is projected at
            a fixed (center, scale, rotation), routed, scored. The top K
            templates by score advance.
  Stage 2 — Refinement: each finalist is re-tried at (offset x scale x
            rotation) variations; best overall wins.

The routing is intentionally lazy (shortest_path on edge length only).
The multi-template prior compensates: enough variants exist that some
will naturally trace the local grid.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .area_scorer import composite_score
from .osmnx_router import (
    GraphHandle,
    project_template,
    route_length_m,
    route_through_template,
)
from .quickdraw_loader import Template, load_top_templates


@dataclass
class Candidate:
    template: Template
    center_lat: float
    center_lon: float
    scale_m: float
    rotation_deg: float
    projected: List[Tuple[float, float]] = field(default_factory=list)
    route: List[Tuple[float, float]] = field(default_factory=list)
    iou: float = 0.0
    score: float = -1.0
    route_length_m: float = 0.0


def _evaluate(
    handle: GraphHandle,
    template: Template,
    center_lat: float,
    center_lon: float,
    scale_m: float,
    rotation_deg: float,
    target_distance_m: float,
) -> Candidate:
    projected = project_template(
        template.coords, center_lat, center_lon, scale_m, rotation_deg
    )
    route = route_through_template(handle, projected)
    rlen = route_length_m(route)
    score, iou = composite_score(
        projected, route, rlen, target_distance_m,
    )
    return Candidate(
        template=template,
        center_lat=center_lat,
        center_lon=center_lon,
        scale_m=scale_m,
        rotation_deg=rotation_deg,
        projected=projected,
        route=route,
        iou=iou,
        score=score,
        route_length_m=rlen,
    )


def _scale_for_distance(target_distance_m: float, factor: float = 0.45) -> float:
    """Heuristic: bbox size that produces a route of ~target_distance_m.

    A closed outline of perimeter P traced on a grid produces a route
    that's roughly perimeter * sqrt(2)/2 to perimeter * 1 in practice.
    For a bbox of size S the perimeter is roughly 2.5-3.5 S. So a
    target route distance of D maps to S ≈ D / (factor * 6) ≈ 0.15 D.
    Tune `factor` empirically.
    """
    return target_distance_m * factor


def search(
    handle: GraphHandle,
    templates: List[Template],
    target_distance_m: float = 6_000.0,
    *,
    n_finalists: int = 5,
    placement_offsets_m: Tuple[float, ...] = (0.0, 600.0, -600.0),
    scale_multipliers: Tuple[float, ...] = (0.7, 1.0, 1.4),
    rotations: Tuple[float, ...] = (0.0, 90.0, 180.0, 270.0),
    verbose: bool = False,
) -> List[Candidate]:
    """Run two-stage search; returns sorted list of candidates (best first)."""
    base_scale = _scale_for_distance(target_distance_m)
    base_lat, base_lon = handle.center_lat, handle.center_lon
    deg_per_m_lat = 1.0 / 111_000.0
    deg_per_m_lon = 1.0 / (111_000.0 * math.cos(math.radians(base_lat)))

    # Stage 1: scan all templates at base placement / scale / rotation 0.
    if verbose:
        print(f'[stage1] {len(templates)} templates @ scale={base_scale:.0f}m')
    stage1: List[Candidate] = []
    t0 = time.time()
    for i, t in enumerate(templates):
        c = _evaluate(handle, t, base_lat, base_lon, base_scale, 0.0, target_distance_m)
        stage1.append(c)
        if verbose and (i + 1) % 10 == 0:
            elapsed = time.time() - t0
            best = max(s.iou for s in stage1)
            print(f'  [{i+1}/{len(templates)}] best_iou_so_far={best:.3f} elapsed={elapsed:.1f}s')
    stage1.sort(key=lambda c: c.score, reverse=True)
    finalists = stage1[:n_finalists]

    if verbose and finalists:
        b = finalists[0]
        print(f'[stage1 done] best score={b.score:.3f} iou={b.iou:.3f} '
              f'rlen={b.route_length_m/1000:.1f}km in {time.time()-t0:.1f}s')

    # Build placement candidates (origin plus 4 cardinal offsets).
    placements: List[Tuple[float, float]] = []
    for off in placement_offsets_m:
        if off == 0.0:
            placements.append((base_lat, base_lon))
        else:
            placements.append((base_lat + off * deg_per_m_lat, base_lon))
            placements.append((base_lat, base_lon + off * deg_per_m_lon))

    # Stage 2: refine top-K templates over (placement, scale, rotation).
    all_results: List[Candidate] = list(stage1)
    for finalist in finalists:
        if verbose:
            print(f'[stage2] refining {finalist.template.key_id[-6:]}')
        for lat_off, lon_off in placements:
            for sm in scale_multipliers:
                for rot in rotations:
                    if (lat_off, lon_off) == (base_lat, base_lon) and sm == 1.0 and rot == 0.0:
                        continue  # already covered in stage 1
                    c = _evaluate(
                        handle,
                        finalist.template,
                        lat_off, lon_off,
                        base_scale * sm,
                        rot,
                        target_distance_m,
                    )
                    all_results.append(c)
    all_results.sort(key=lambda c: c.score, reverse=True)
    return all_results


def load_templates_for(animal: str, n: int = 30, qd_dir: str = 'data/quickdraw') -> List[Template]:
    """Load top-N templates for an animal, preferring single-stroke."""
    path = Path(qd_dir) / f'{animal}.ndjson'
    pool = load_top_templates(path, n=n * 3, max_strokes=4)
    # prefer 1- or 2-stroke drawings
    pool.sort(key=lambda t: (t.n_strokes, -len(t.coords)))
    return pool[:n]


__all__ = ['Candidate', 'search', 'load_templates_for']
