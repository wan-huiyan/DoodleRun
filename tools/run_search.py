"""Driver: run multi-template search at a city, render top-K previews."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prototype.multi_template_search import load_templates_for, search
from prototype.osmnx_router import load_graph
from prototype.preview_render import render_candidate

CITIES = {
    'milton-keynes': (52.0406, -0.7594),
    'st-albans': (51.7520, -0.3360),
    'hertford': (51.7958, -0.0782),
    'cambridge': (52.2053, 0.1218),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--animal', required=True, choices=['pig', 'cat', 'dog', 'dragon', 'duck'])
    ap.add_argument('--city', required=True, choices=list(CITIES.keys()))
    ap.add_argument('--distance', type=float, default=6000.0, help='target route distance (m)')
    ap.add_argument('--n-templates', type=int, default=20)
    ap.add_argument('--n-finalists', type=int, default=4)
    ap.add_argument('--graph-radius', type=int, default=5000)
    ap.add_argument('--top-k', type=int, default=5)
    ap.add_argument('--out-dir', type=str, default='data/previews/runs')
    args = ap.parse_args()

    lat, lon = CITIES[args.city]
    out_root = Path(args.out_dir) / f'{args.city}_{args.animal}'
    out_root.mkdir(parents=True, exist_ok=True)

    print(f'== {args.city} {args.animal} target={args.distance:.0f}m ==')

    t0 = time.time()
    handle = load_graph(lat, lon, radius_m=args.graph_radius)
    print(f'graph: {len(handle.G)} nodes, {handle.G.number_of_edges()} edges '
          f'({time.time()-t0:.1f}s)')

    templates = load_templates_for(args.animal, n=args.n_templates)
    print(f'templates: {len(templates)} loaded')

    t0 = time.time()
    results = search(
        handle,
        templates,
        target_distance_m=args.distance,
        n_finalists=args.n_finalists,
        verbose=True,
    )
    elapsed = time.time() - t0
    print(f'search done in {elapsed:.1f}s, {len(results)} candidates')

    # Save top-K
    top = results[: args.top_k]
    summary = []
    for i, c in enumerate(top):
        out_path = out_root / f'rank{i+1:02d}_iou{c.iou:.3f}_{c.template.key_id[-8:]}.png'
        title = (
            f'{args.city} / {args.animal}: rank {i+1} | iou={c.iou:.3f} '
            f'rlen={c.route_length_m/1000:.1f}km | '
            f'rot={c.rotation_deg:.0f}° scale={c.scale_m:.0f}m '
            f'tmpl={c.template.key_id[-8:]}'
        )
        render_candidate(handle, c, out_path, title=title)
        summary.append({
            'rank': i + 1,
            'iou': c.iou,
            'score': c.score,
            'route_length_m': c.route_length_m,
            'template_key_id': c.template.key_id,
            'rotation_deg': c.rotation_deg,
            'scale_m': c.scale_m,
            'center_lat': c.center_lat,
            'center_lon': c.center_lon,
            'png': str(out_path),
        })
    (out_root / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(f'wrote {len(top)} previews to {out_root}')


if __name__ == '__main__':
    main()
