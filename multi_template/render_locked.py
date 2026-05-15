"""Render the locked-in routes from `locked_routes.json`.

Loads the configuration, rebuilds the OSM graph at each location, re-projects
the template at the saved (center, scale, rotation), routes it with the
saved router knobs, and writes a final PNG per location plus a 2x2 comparison
sheet vs the pre-fix top-1 baselines (read from previews/*_summary.json).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt

from .graph_loader import load_graph
from .projection import project_template
from .router import route_through_waypoints
from .templates_loader import load_animal_templates


LOCATION_LABELS = {
    "st_albans": "St Albans, Hertfordshire",
    "milton_keynes": "Milton Keynes, Buckinghamshire",
}


def regenerate(location_key: str, cfg: dict, router_cfg: dict, radius_m: int = 12_000):
    label = LOCATION_LABELS[location_key]
    tpls = load_animal_templates("elephant", vote_ids=[cfg["vote_id"]])
    if not tpls:
        raise SystemExit(f"template {cfg['vote_id']} not found")
    tpl = tpls[0]
    sg = load_graph(cfg["center_lat"], cfg["center_lon"], radius_m=radius_m)

    waypoints, _ = project_template(
        tpl.points,
        center_lat=cfg["center_lat"], center_lon=cfg["center_lon"],
        scale_m=cfg["scale_m"], rotation_deg=cfg["rotation_deg"],
        n_waypoints=router_cfg.get("n_waypoints", 32),
    )
    routed = route_through_waypoints(
        sg.G, waypoints,
        alpha=router_cfg["alpha"],
        beta=router_cfg["beta"],
        revisit_penalty_m=router_cfg["revisit_penalty_m"],
    )
    if routed is None:
        raise SystemExit("routing failed")
    return tpl, waypoints, routed, label


def render_locked(out_dir: Path):
    cfg = json.loads((Path(__file__).parent / "locked_routes.json").read_text())
    router_cfg = cfg["router"]
    out_dir.mkdir(parents=True, exist_ok=True)
    length_tolerance_m = 100.0  # 100 m drift means the route has shifted to a different graph node sequence

    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    for row, loc in enumerate(["st_albans", "milton_keynes"]):
        sub = cfg[f"elephant_{loc}"]
        tpl, waypoints, routed, label = regenerate(loc, sub, router_cfg)
        expected_len = sub["route_length_m"]
        drift = routed.total_length_m - expected_len
        if abs(drift) > length_tolerance_m:
            raise SystemExit(
                f"REGRESSION at {loc}: regenerated route is {routed.total_length_m:.0f} m "
                f"but locked config records {expected_len:.0f} m (drift {drift:+.0f} m > "
                f"{length_tolerance_m:.0f} m tolerance). The router or graph changed; the locked "
                f"elephant no longer matches. Re-run multi_template.run_search and update locked_routes.json."
            )
        # Left: locked elephant route
        ax = axes[row, 0]
        ideal = np.array([w for w in waypoints])
        rt = np.array(routed.polyline)
        ax.plot(ideal[:, 1], ideal[:, 0], "-", color="lightgrey", lw=2.5, label="ideal")
        ax.plot(rt[:, 1], rt[:, 0], "-", color="crimson", lw=1.5, label="routed")
        ax.set_aspect("equal")
        ax.set_title(
            f"LOCKED  elephant @ {label}\n{sub['vote_id']}  scale={sub['scale_m']/1000:.1f}km  "
            f"rot={sub['rotation_deg']:+.0f}°  len={routed.total_length_m/1000:.1f}km",
            fontsize=10,
        )
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(alpha=0.2)

        # Right: pre-fix top-1 baseline (read from prior summary)
        base_path = Path("multi_template/previews") / f"elephant_{loc}_best_polyline.json"
        if base_path.exists():
            base_poly = json.loads(base_path.read_text())["lat_lon"]
            base_arr = np.array(base_poly)
            ax = axes[row, 1]
            # use ideal from same template if available (close enough)
            ax.plot(ideal[:, 1], ideal[:, 0], "-", color="lightgrey", lw=2.5, label="ideal (new tmpl)")
            ax.plot(base_arr[:, 1], base_arr[:, 0], "-", color="steelblue", lw=1.5, label="routed (PRE-fix top-1)")
            ax.set_aspect("equal")
            ax.set_title(f"PRE-FIX top-1  @ {label}\n(template+placement chosen by old Optuna run)", fontsize=10)
            ax.legend(loc="upper right", fontsize=8)
            ax.grid(alpha=0.2)
        else:
            axes[row, 1].text(0.5, 0.5, f"no baseline at {base_path}", ha="center")
            axes[row, 1].axis("off")

        # Save locked-only single PNG
        single = out_dir / f"LOCKED_elephant_{loc}.png"
        fig_s, ax_s = plt.subplots(1, 1, figsize=(8, 7))
        ax_s.plot(ideal[:, 1], ideal[:, 0], "-", color="lightgrey", lw=2.5, label="template")
        ax_s.plot(rt[:, 1], rt[:, 0], "-", color="crimson", lw=1.6, label="route")
        ax_s.set_aspect("equal")
        ax_s.set_title(
            f"elephant @ {label}\n{sub['vote_id']}  {routed.total_length_m/1000:.1f} km",
            fontsize=11,
        )
        ax_s.legend(loc="upper right", fontsize=9)
        ax_s.grid(alpha=0.2)
        fig_s.savefig(single, dpi=130, bbox_inches="tight")
        plt.close(fig_s)
        print(f"  wrote {single}")

        # Save GPX-friendly polyline JSON too
        poly_json = out_dir / f"LOCKED_elephant_{loc}_polyline.json"
        poly_json.write_text(json.dumps({
            "vote_id": sub["vote_id"],
            "center_lat": sub["center_lat"], "center_lon": sub["center_lon"],
            "scale_m": sub["scale_m"], "rotation_deg": sub["rotation_deg"],
            "router": router_cfg,
            "polyline_lat_lon": routed.polyline,
            "total_length_m": routed.total_length_m,
        }, indent=2))
        print(f"  wrote {poly_json}")

    fig.suptitle("DoodleRun elephant — locked routes vs pre-fix baseline", fontsize=13)
    out = out_dir / "LOCKED_elephant_compare.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="multi_template/previews/locked")
    args = ap.parse_args()
    render_locked(Path(args.out_dir))
