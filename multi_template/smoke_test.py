"""End-to-end smoke test: load templates, build small graph, route once, render.

Run from repo root:
    python -m multi_template.smoke_test
"""
from __future__ import annotations

import time
from pathlib import Path

from .graph_loader import load_graph
from .preview import render_candidate
from .projection import project_template
from .router import route_through_waypoints
from .search import Candidate
from .fidelity import score_route
from .templates_loader import load_animal_templates


def main():
    print("[1/4] load templates")
    templates = load_animal_templates("elephant", source_kind="stravart", max_templates=4)
    print(f"      loaded {len(templates)} elephant stravart templates")
    tpl = templates[0]

    print("[2/4] load 6km graph @ St Albans")
    sg = load_graph(51.7520, -0.3360, radius_m=6000)
    print(f"      G: {sg.G.number_of_nodes()} nodes, {sg.G.number_of_edges()} edges")

    print("[3/4] project + route")
    waypoints, ideal = project_template(
        tpl.points,
        center_lat=51.7520, center_lon=-0.3360,
        scale_m=4500, rotation_deg=0, n_waypoints=12,
    )
    t0 = time.time()
    routed = route_through_waypoints(sg.G, waypoints)
    t1 = time.time()
    print(f"      routed in {t1-t0:.1f}s  total={routed.total_length_m/1000:.2f}km  legs={len(routed.legs)}")

    print("[4/4] score + render preview")
    fid = score_route(tpl.points, routed.polyline, n_samples=120)
    print(f"      fid: frechet={fid['frechet']:.3f} mhd={fid['mhd']:.3f} iou={fid['iou']:.3f}")

    cand = Candidate(
        template_idx=0, template_vote_id=tpl.vote_id, template_source=tpl.source_kind,
        center_lat=51.7520, center_lon=-0.3360, scale_m=4500, rotation_deg=0,
        n_waypoints=12, routed=routed, fidelity=fid,
        objective=fid["frechet"] + 0.5 * fid["mhd"] + 0.5 * (1.0 - fid["iou"]),
    )
    out = Path("multi_template/previews/_smoke_elephant_stalbans.png")
    render_candidate(cand, tpl, out_path=out, title="SMOKE: elephant @ St Albans")
    print(f"      wrote {out}")


if __name__ == "__main__":
    main()
