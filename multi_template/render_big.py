"""Render a SINGLE big PNG per locked candidate so the route is unambiguously
visible. Single panel, large figure, template grey thick + route crimson thick."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from .graph_loader import load_graph
from .projection import project_template
from .router import route_through_waypoints
from .templates_loader import load_animal_templates


LOCATIONS = {
    "st_albans": (51.7520, -0.3360, "St Albans, Hertfordshire"),
    "milton_keynes": (52.0406, -0.7594, "Milton Keynes, Buckinghamshire"),
    "maidenhead_windsor": (51.5030, -0.6620, "Maidenhead / Windsor area, Berkshire"),
}


def render(loc_key: str, cand: dict, vote_id: str, label: str, out_path: Path,
           router_alpha=3.0, router_beta=6.0, router_revisit=0.0, n_waypoints=64):
    tpls = load_animal_templates("elephant", vote_ids=[vote_id])
    tpl = tpls[0]
    lat0, lon0, _ = LOCATIONS[loc_key]
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
    rt = np.array(routed.polyline)
    tpl_xy = np.array(full_polyline)

    # plot — single panel, big
    fig, ax = plt.subplots(1, 1, figsize=(14, 11), dpi=130)
    ax.plot(tpl_xy[:, 1], tpl_xy[:, 0], "-", color="#bbbbbb", lw=4.0, label=f"template ({vote_id})", solid_capstyle="round")
    ax.plot(rt[:, 1], rt[:, 0], "-", color="#d6336c", lw=2.5, label=f"route ({routed.total_length_m/1000:.1f} km)", solid_capstyle="round")
    # waypoint dots
    wp = np.array(routed.waypoints)
    ax.scatter(wp[:, 1], wp[:, 0], c="#1f77b4", s=14, zorder=5, label=f"{len(wp)} waypoints")
    ax.set_aspect(1.0 / math.cos(math.radians(cand["center_lat"])))
    ax.set_title(
        f"elephant @ {label}\n"
        f"{vote_id}  scale={cand['scale_m']/1000:.2f}km  rot={cand['rotation_deg']:+.0f}°  "
        f"length={routed.total_length_m/1000:.1f}km  iou={cand['fidelity']['iou']:.3f}",
        fontsize=14,
    )
    ax.legend(loc="upper right", fontsize=12)
    ax.grid(alpha=0.25)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")
    return routed.total_length_m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suffix", default="_s04_xs")
    ap.add_argument("--out-dir", default="multi_template/previews/big")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    base = Path("multi_template/previews")
    for loc in ["st_albans", "maidenhead_windsor"]:
        summary_path = base / f"elephant_{loc}{args.suffix}_summary.json"
        if not summary_path.exists():
            print(f"skip {loc} ({summary_path} missing)")
            continue
        meta = json.loads(summary_path.read_text())
        best = meta["best"]
        label = meta["location_label"]
        out = out_dir / f"BIG_elephant_{loc}{args.suffix}.png"
        render(loc, best, best["vote_id"], label, out)


if __name__ == "__main__":
    main()
