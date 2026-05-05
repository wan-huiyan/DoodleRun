"""Run multi-template Optuna search at one or more England locations.

Usage:
    python -m multi_template.run_search --animal elephant \
        --location st_albans --n-trials 60

England locations only — see ENGLAND_SITES below.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import List

from .graph_loader import load_graph
from .preview import render_candidate
from .search import search_animal_at_location
from .templates_loader import load_animal_templates


# All centers must be inside England.
ENGLAND_SITES = {
    "st_albans":     (51.7520, -0.3360, "St Albans, Hertfordshire"),
    "milton_keynes": (52.0406, -0.7594, "Milton Keynes, Buckinghamshire"),
    "hertford":      (51.7950, -0.0780, "Hertford, Hertfordshire"),
    "outer_london":  (51.5500, -0.1000, "Outer London (Hackney/Islington edge)"),
    "cambridge":     (52.2050, 0.1190,  "Cambridge, Cambridgeshire"),
}


def run_one(
    animal: str,
    location_key: str,
    *,
    n_trials: int,
    target_distance_m: float,
    radius_m: int,
    out_dir: Path,
    source_filter: str | None,
    max_templates: int | None,
):
    if location_key not in ENGLAND_SITES:
        raise SystemExit(f"unknown location {location_key}; must be one of {list(ENGLAND_SITES)}")
    lat, lon, label = ENGLAND_SITES[location_key]
    print(f"\n=== {animal} @ {label} ({lat:.4f},{lon:.4f}) ===")

    print("[load] templates")
    templates = load_animal_templates(animal, source_kind=source_filter, max_templates=max_templates)
    print(f"  {len(templates)} templates ({source_filter or 'all kinds'})")

    print("[load] OSM graph")
    sg = load_graph(lat, lon, radius_m=radius_m)
    print(f"  {sg.G.number_of_nodes()} nodes  {sg.G.number_of_edges()} edges")

    print(f"[search] Optuna n_trials={n_trials}")
    t0 = time.time()
    res = search_animal_at_location(
        templates, sg,
        target_distance_m=target_distance_m,
        n_trials=n_trials,
    )
    elapsed = time.time() - t0
    best = res.best
    print(f"  done in {elapsed:.1f}s — best obj={best.objective:.3f}")
    print(f"  template={best.template_vote_id} ({best.template_source})")
    print(f"  scale={best.scale_m/1000:.2f}km  rot={best.rotation_deg:.0f}°  "
          f"len={best.routed.total_length_m/1000:.2f}km")
    print(f"  fid: frechet={best.fidelity['frechet']:.3f} "
          f"mhd={best.fidelity['mhd']:.3f} iou={best.fidelity['iou']:.3f}")

    # render top-3
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(res.all_candidates[:3]):
        tpl = templates[c.template_idx]
        out = out_dir / f"{animal}_{location_key}_top{i+1}_{tpl.vote_id}.png"
        render_candidate(c, tpl, out_path=out, title=f"{animal} @ {label}  (rank {i+1})")
        print(f"  rendered {out}")

    # save metadata
    meta = {
        "animal": animal,
        "location_key": location_key,
        "location_label": label,
        "lat": lat, "lon": lon,
        "elapsed_s": elapsed,
        "n_trials": n_trials,
        "best": {
            "vote_id": best.template_vote_id,
            "source": best.template_source,
            "center_lat": best.center_lat,
            "center_lon": best.center_lon,
            "scale_m": best.scale_m,
            "rotation_deg": best.rotation_deg,
            "n_waypoints": best.n_waypoints,
            "route_length_m": best.routed.total_length_m,
            "objective": best.objective,
            "fidelity": best.fidelity,
        },
        "top_candidates": [
            {
                "rank": i + 1,
                "vote_id": c.template_vote_id,
                "source": c.template_source,
                "center_lat": c.center_lat, "center_lon": c.center_lon,
                "scale_m": c.scale_m, "rotation_deg": c.rotation_deg,
                "route_length_m": c.routed.total_length_m,
                "objective": c.objective,
                "fidelity": c.fidelity,
            }
            for i, c in enumerate(res.all_candidates)
        ],
    }
    meta_path = out_dir / f"{animal}_{location_key}_summary.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"  wrote {meta_path}")

    # also dump the routed polyline for the best
    poly_path = out_dir / f"{animal}_{location_key}_best_polyline.json"
    poly_path.write_text(json.dumps({
        "lat_lon": best.routed.polyline,
        "waypoints": best.routed.waypoints,
        "total_length_m": best.routed.total_length_m,
    }))
    print(f"  wrote {poly_path}")
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--animal", default="elephant")
    ap.add_argument("--location", action="append", default=None,
                    help="England location key; repeat for multiple")
    ap.add_argument("--n-trials", type=int, default=60)
    ap.add_argument("--target-distance-m", type=float, default=20_000)
    ap.add_argument("--radius-m", type=int, default=12_000)
    ap.add_argument("--source", default=None, choices=[None, "quickdraw", "stravart"])
    ap.add_argument("--max-templates", type=int, default=None)
    ap.add_argument("--out-dir", default="multi_template/previews")
    args = ap.parse_args()

    locs = args.location or ["st_albans", "milton_keynes"]
    out_dir = Path(args.out_dir)
    summary = []
    for loc in locs:
        meta = run_one(
            args.animal, loc,
            n_trials=args.n_trials,
            target_distance_m=args.target_distance_m,
            radius_m=args.radius_m,
            out_dir=out_dir,
            source_filter=args.source,
            max_templates=args.max_templates,
        )
        summary.append(meta)

    # write overall index
    idx = out_dir / f"{args.animal}_runs_index.json"
    idx.write_text(json.dumps(summary, indent=2))
    print(f"\nwrote index {idx}")


if __name__ == "__main__":
    main()
