"""Diagnostic renderer: color each waypoint-to-waypoint leg of the route
differently. Reveals which segments closely follow the template and which take
road-grid shortcuts that skip anatomy.

Usage:
  python -m multi_template.render_diagnostic --suffix _s04_xs
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection

from .graph_loader import load_graph
from .projection import project_template
from .router import route_through_waypoints
from .templates_loader import load_animal_templates


LOCATIONS = {
    "st_albans": "St Albans, Hertfordshire",
    "maidenhead_windsor": "Maidenhead / Windsor area, Berkshire",
    "milton_keynes": "Milton Keynes, Buckinghamshire",
}


def render(loc_key: str, cand: dict, vote_id: str, out_path: Path,
           router_alpha=3.0, router_beta=6.0, router_revisit=0.0, n_waypoints=64):
    tpls = load_animal_templates("elephant", vote_ids=[vote_id])
    tpl = tpls[0]
    label = LOCATIONS[loc_key]
    sg = load_graph(cand["center_lat"], cand["center_lon"], radius_m=12_000)

    waypoints, full_polyline = project_template(
        tpl.points,
        center_lat=cand["center_lat"], center_lon=cand["center_lon"],
        scale_m=cand["scale_m"], rotation_deg=cand["rotation_deg"],
        n_waypoints=n_waypoints,
    )
    routed = route_through_waypoints(
        sg.G, waypoints,
        alpha=router_alpha, beta=router_beta, revisit_penalty_m=router_revisit,
    )

    tpl_xy = np.array(full_polyline)
    legs = routed.legs  # list of RouteLeg with .polyline (lat,lon)

    fig, axes = plt.subplots(1, 2, figsize=(20, 11), dpi=130)

    # Left: route colored by leg, template thick grey underneath
    ax = axes[0]
    ax.plot(tpl_xy[:, 1], tpl_xy[:, 0], "-", color="#cccccc", lw=4.0, label=f"template ({vote_id})")
    cmap = plt.cm.hsv  # cycles through full color wheel
    for i, leg in enumerate(legs):
        poly = np.array(leg.polyline)
        if len(poly) < 2:
            continue
        c = cmap(i / max(1, len(legs) - 1))
        ax.plot(poly[:, 1], poly[:, 0], "-", color=c, lw=2.0, alpha=0.9, solid_capstyle="round")
    # Mark each waypoint
    wp = np.array(routed.waypoints)
    ax.scatter(wp[:, 1], wp[:, 0], c="black", s=18, zorder=5)
    for i, (la, lo) in enumerate(wp):
        ax.annotate(str(i), (lo, la), fontsize=6, color="black", xytext=(2, 2), textcoords="offset points")
    ax.set_aspect(1.0 / math.cos(math.radians(cand["center_lat"])))
    ax.set_title(
        f"PER-LEG DIAGNOSTIC — elephant @ {label}\n"
        f"{vote_id}  {len(legs)} legs, {len(wp)} waypoints  "
        f"scale={cand['scale_m']/1000:.2f}km  iou={cand['fidelity']['iou']:.3f}",
        fontsize=13,
    )
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right", fontsize=10)

    # Right: leg-length histogram — long legs are suspect (Dijkstra detour)
    ax = axes[1]
    leg_lens = [l.length_m / 1000.0 for l in legs]
    expected_leg_km = sum(leg_lens) / len(leg_lens)
    ax.bar(range(len(legs)), leg_lens, color="#1f77b4", edgecolor="black", lw=0.5)
    ax.axhline(expected_leg_km, color="red", ls="--", label=f"mean leg = {expected_leg_km:.2f} km")
    ax.axhline(expected_leg_km * 2, color="orange", ls=":", label=f"2× mean (suspect shortcuts)")
    ax.set_xlabel("waypoint segment #")
    ax.set_ylabel("leg length (km)")
    ax.set_title(
        f"Leg-length distribution  "
        f"(min={min(leg_lens):.2f}, max={max(leg_lens):.2f}, total={sum(leg_lens):.1f} km)",
        fontsize=11,
    )
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")
    return leg_lens, expected_leg_km


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suffix", default="_s04_xs")
    ap.add_argument("--locations", nargs="+", default=["st_albans", "maidenhead_windsor"])
    ap.add_argument("--out-dir", default="multi_template/previews/diagnostic")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    base = Path("multi_template/previews")
    for loc in args.locations:
        summary_path = base / f"elephant_{loc}{args.suffix}_summary.json"
        if not summary_path.exists():
            print(f"skip {loc} ({summary_path} missing)")
            continue
        meta = json.loads(summary_path.read_text())
        best = meta["best"]
        out = out_dir / f"DIAG_elephant_{loc}{args.suffix}.png"
        leg_lens, mean = render(loc, best, best["vote_id"], out)
        # Print outlier segments
        suspect = [(i, l) for i, l in enumerate(leg_lens) if l > 2 * mean]
        if suspect:
            print(f"  suspect legs (> 2× mean = {2*mean:.2f}km):")
            for i, l in suspect:
                print(f"    leg {i}: {l:.2f} km")
        else:
            print(f"  no suspect legs (all within 2× mean)")


if __name__ == "__main__":
    main()
