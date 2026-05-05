"""Smoke tests for preview.py.

Renders are smoke-checked (file written, > 0 bytes) rather than pixel-
compared — the design is deliberately judged by eye, not asserted in code.
Matplotlib rendering is skipped if the lib isn't installed (it's optional).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from preview import (
    project_outline,
    render_preview_html,
    render_shape_png,
    scale_for_distance,
)
from shapes import SHAPES


@pytest.mark.parametrize("shape_id", sorted(SHAPES.keys()))
def test_project_outline_centers_on_lat_lon(shape_id):
    """The bbox center of the projected outline should be the input lat/lon."""
    outline = SHAPES[shape_id]
    pts = project_outline(outline, 51.75, -0.34, scale_m_per_unit=200.0)
    lats = [p[0] for p in pts]
    lons = [p[1] for p in pts]
    assert abs(((min(lats) + max(lats)) / 2) - 51.75) < 1e-6
    assert abs(((min(lons) + max(lons)) / 2) - -0.34) < 1e-6


def test_scale_for_distance_matches_router_seed():
    """preview.scale_for_distance must match the router's initial guess so
    `--preview-only` previews at the same size the router would start with."""
    from route_generator import generate  # only for inline doc-style sanity
    outline = SHAPES["pig"]
    s = scale_for_distance(outline, 10_000.0)
    # Sanity: 10 km / 1.3 / perimeter is the documented heuristic.
    from shape_utils import outline_perimeter
    expected = (10_000.0 / 1.3) / outline_perimeter(outline)
    assert abs(s - expected) < 1e-9


def test_render_preview_html_writes_file(tmp_path: Path):
    outline = SHAPES["pig"]
    pts = project_outline(outline, 51.75, -0.34, scale_m_per_unit=200.0)
    out = tmp_path / "preview.html"
    render_preview_html(pts, str(out), title="Pig preview")
    assert out.exists() and out.stat().st_size > 1000  # folium HTML is large


@pytest.mark.skipif(
    importlib.util.find_spec("matplotlib") is None,
    reason="matplotlib not installed (optional dev dep)",
)
@pytest.mark.parametrize("shape_id", sorted(SHAPES.keys()))
def test_render_shape_png_writes_file(tmp_path: Path, shape_id):
    out = tmp_path / f"{shape_id}.png"
    render_shape_png(SHAPES[shape_id], str(out), title=shape_id)
    assert out.exists() and out.stat().st_size > 500


def test_render_shape_png_rejects_empty(tmp_path: Path):
    pytest.importorskip("matplotlib")
    with pytest.raises(ValueError):
        render_shape_png([], str(tmp_path / "x.png"))


def test_render_preview_html_rejects_empty(tmp_path: Path):
    with pytest.raises(ValueError):
        render_preview_html([], str(tmp_path / "x.html"))
