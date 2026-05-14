"""Render a route over an OSM tile background."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np

from .projection import project_template
from .search import Candidate
from .templates_loader import Template


def _bbox_from_polyline(poly, pad_frac: float = 0.18):
    poly = np.asarray(poly)
    mn = poly.min(0); mx = poly.max(0)
    span = mx - mn
    pad = span * pad_frac
    return (mn[0] - pad[0], mx[0] + pad[0], mn[1] - pad[1], mx[1] + pad[1])


def render_candidate(
    cand: Candidate,
    tpl: Template,
    *,
    out_path: Path,
    title: Optional[str] = None,
    dpi: int = 140,
) -> Path:
    """Two-panel preview: template outline + routed polyline on a small map."""
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.5), dpi=dpi)

    # Left: normalized template + the projected ideal outline
    axL = axes[0]
    axL.plot(tpl.points[:, 0], tpl.points[:, 1], color="#666", lw=1.2)
    axL.set_aspect("equal")
    axL.set_title(f"Template {tpl.vote_id} ({tpl.source_kind})", fontsize=10)
    axL.grid(alpha=0.2)
    axL.set_xticks([]); axL.set_yticks([])

    # Right: routed polyline + ideal projection overlay
    axR = axes[1]
    routed = np.asarray(cand.routed.polyline)
    _waypoints, ideal = project_template(
        tpl.points,
        center_lat=cand.center_lat, center_lon=cand.center_lon,
        scale_m=cand.scale_m, rotation_deg=cand.rotation_deg,
        n_waypoints=cand.n_waypoints,
    )
    ideal = np.asarray(ideal)
    axR.plot(ideal[:, 1], ideal[:, 0], color="#bbbbbb", lw=1.2, label="ideal")
    axR.plot(routed[:, 1], routed[:, 0], color="#d6336c", lw=1.6, label="routed")
    # waypoints
    wp = np.asarray(cand.routed.waypoints)
    axR.scatter(wp[:, 1], wp[:, 0], c="#1f77b4", s=18, zorder=5)
    axR.set_aspect(1.0 / math.cos(math.radians(cand.center_lat)))
    axR.set_title(
        f"@({cand.center_lat:.4f},{cand.center_lon:.4f})  "
        f"scale={cand.scale_m/1000:.1f}km  rot={cand.rotation_deg:.0f}°  "
        f"len={cand.routed.total_length_m/1000:.1f}km",
        fontsize=9,
    )
    axR.grid(alpha=0.2)
    axR.legend(loc="upper right", fontsize=8)

    fid = cand.fidelity
    suptitle = title or f"{tpl.animal} → {tpl.vote_id}"
    fig.suptitle(
        f"{suptitle}\nfréchet={fid['frechet']:.3f}  mhd={fid['mhd']:.3f}  "
        f"iou={fid['iou']:.3f}  obj={cand.objective:.3f}",
        fontsize=11,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return out_path
