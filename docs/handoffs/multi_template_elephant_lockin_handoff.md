# Multi-template elephant lock-in — handoff

**Date:** 2026-05-15
**Branch:** `claude/review-demo-route-yo15w` (3 commits ahead of origin)
**Predecessor:** strav.art Phase 3 (last merged PR #6 on main)

## Session goal

Lock in a recognisable elephant route at two UK locations before rolling out to the
other 5 animals (pig / cat / dog / dragon / duck). User priorities (from session prompt):

1. **"Looking like the animal" is top priority** — distance / start / route length are secondary
2. Doubling back / out-and-back legs are FINE if they make the shape more recognisable

## What was completed

Three iterations of locked routes, each improving over the last as bugs surfaced:

| Lock | Commit | St Albans | Maidenhead | iou (max) | User verdict |
|---|---|---|---|---|---|
| v1 | `cc2c94d` | ELE-Q01, 36.9 km | (MK) ELE-Q07, 40.6 km | 0.189 | "still not enough" |
| v2 | `ea5ac53` | ELE-Q07, 63.2 km | (MK) ELE-Q07, 59.9 km | 0.193 | "doesn't look like elephant. incomplete" |
| **v3** | **`f7df239`** | **ELE-S04, 47.2 km** | ELE-S04, 41.3 km | **0.321** | **accepted (with one known artifact)** |

**v3 (locked) full-precision config** lives in `multi_template/locked_routes.json`:
- St Albans: lat 51.7538, lon -0.3225, scale 3764 m, rot -0.44°, iou 0.321
- Maidenhead/Windsor: lat 51.5237, lon -0.6211, scale 3082 m, rot 2.28°, iou 0.317

### Three combined fixes that unlocked v3

1. **Router knob recipe** (from v1): `revisit_penalty_m=0`, `n_waypoints=64`, `beta=6`,
   rotation clipped to [-30°, +30°], length penalty disabled, manual template whitelist.
   See lesson `lessons_elephant_lockin_config.md` and skill
   `gps-art-splice-loop-template-routing` v1.1.0.

2. **Snap-to-distinct-node fix** (new in v3, `multi_template/router.py`): replaced
   `list(dict.fromkeys(ox.distance.nearest_nodes(...)))` with a cKDTree-based
   nearest-unused-node snap (k=50). The naïve dedup was silently collapsing 9/64
   waypoints at St Albans scale=6.65km onto the same OSM graph node when they landed
   inside the road-grid spacing — typically leg-tip waypoints — so legs lost their
   routing target and disappeared from the trace.

3. **Render-against-full-polyline fix** (new in v3, `multi_template/render_locked.py`):
   the LOCKED PNGs were plotting the sparse 64-pt waypoint resample as the grey
   "template" reference, drawing chord-across-appendage straight lines. The route
   looked "incomplete" because the grey was incomplete. Fixed to use the full
   400-pt template polyline. (`preview.py` was always correct — only `render_locked`
   was wrong.)

### New tooling shipped

| File | Purpose |
|---|---|
| `multi_template/dashboard.py` | HTML dashboard auto-scanning all `*_summary.json`. Locked section single-column for big landscape PNGs. Open `multi_template/previews/dashboard.html` after each experiment. |
| `multi_template/render_big.py` | Big single-panel route+template PNG per location. Resolves "I can't see the route" by giving each render full width. |
| `multi_template/render_diagnostic.py` | Per-leg colored diagnostic + leg-length histogram. Outlier bars >2× mean = Dijkstra shortcut legs. |
| `multi_template/build_contact.py` | Top-K candidate contact sheet for cherry-picking. |
| `multi_template/build_template_gallery.py` | All 36 approved elephant templates as one sheet for picking. |
| `multi_template/previews/compare.html` | Before/after smoothing side-by-side. |

### Code knobs plumbed through (`run_search.py` CLI)

- `--router-revisit-penalty-m`, `--router-beta`, `--router-alpha`
- `--n-waypoints`
- `--scale-min-m`, `--scale-max-m`
- `--rotation-min-deg`, `--rotation-max-deg`
- `--length-penalty-per-km`
- `--smooth-sigma` (Gaussian outline smoothing in arc-length space)
- `--template-ids` (manual template whitelist)
- `--keep-top`, `--render-top`, `--out-suffix`

## What remains (priorities for follow-up session)

1. **Roll out v3 recipe to the other 5 animals** (pig / cat / dog / dragon / duck).
   - Each animal needs an iconic-template whitelist (gallery render at
     `multi_template/previews/_GALLERY_<animal>.png` once you build it for that animal).
   - Reuse v3 router knobs verbatim. Tune `scale_min_m/scale_max_m` per animal
     (3-4 km worked for elephant; pig/cat may want smaller, dragon larger).
   - User picks template + location per animal; don't trust Optuna's rank-1 alone.

2. **Add a known-artifact note on the locked elephant.** Small upward spike at
   waypoint 43 of the St Albans route is the elephant's ear in the template,
   faithfully traced. User accepted over the smoothed alternative. Already
   documented in `locked_routes.json._known_artifacts` and the v1.1.0 skill.

3. **Push `claude/review-demo-route-yo15w`** to remote and open a PR if rollout
   to the other animals is going to happen on a separate branch.

## Blockers & open issues

- None blocking. All three commits passed local smoke test.
- **Pending user action:** decide whether to merge `claude/review-demo-route-yo15w`
  into main now (locks elephant only) or wait and merge alongside the other 5
  animals later (single rollout PR).

## Key decisions

| Decision | Resolution | Rationale |
|---|---|---|
| Anatomy router vs denser waypoints | Denser waypoints (n=64) | Auto-anatomy detection (pinch-pair, hull-concavity, tip-first) all conflated multiple legs into one super-spike on near-linear bellies. Simpler waypoint lever worked. |
| revisit_penalty_m=4000 vs 0 | 0 | Splice-loop templates encode appendages as out-and-back; high penalty forced Dijkstra to detour through interior. Reverse of `gps-art-tangled-trace-fix` recipe. |
| Optuna's rank-1 vs human pick | Human override | Fidelity metric rewards templates whose outline noise matches road-grid noise; iconic profile elephants score worse but look more elephant. |
| Scale 6-8 km vs 3-4 km | 3-4 km | iou 0.32 vs 0.21 for same template+location; routes 40-50 km vs 60-87 km. Required snap-to-distinct fix first. |
| Smooth template (sigma=3) vs unsmoothed | Unsmoothed | User picked higher iou (0.32) over smoother outline (0.31) despite back-ear spike artifact. |
| ELE-Q01 (v1) vs ELE-Q07 (v2) vs ELE-S04 (v3) | ELE-S04 | User picked S04 from gallery as clearest anatomy. |
| Milton Keynes vs Maidenhead/Windsor | Switched to Maidenhead/Windsor for v3 | Denser road grid; iou 0.317 vs MK 0.193. |

## Files modified

| Path | What changed |
|---|---|
| `multi_template/router.py` | cKDTree distinct-node snap (replaces dict.fromkeys dedup) |
| `multi_template/search.py` | router/rotation/length/scale/n_waypoints/smooth knobs as kwargs |
| `multi_template/run_search.py` | CLI flags for all the above + `--template-ids` + `--out-suffix` |
| `multi_template/templates_loader.py` | `smooth_sigma` kwarg + `_smooth_outline` (Gaussian-1D, wrap mode) + `vote_ids` filter |
| `multi_template/render_locked.py` | full-polyline grey reference; length-band regression assert; dynamic location discovery; legs-count warning |
| `multi_template/locked_routes.json` | v3 lock: ELE-S04 at St Albans + Maidenhead/Windsor, full-precision values |
| `multi_template/dashboard.py` | NEW — HTML dashboard auto-scanning previews/ |
| `multi_template/render_big.py` | NEW — big single-panel route render |
| `multi_template/render_diagnostic.py` | NEW — per-leg colored render + leg-length histogram |
| `multi_template/build_contact.py` | NEW — top-K contact sheet builder |
| `multi_template/build_template_gallery.py` | NEW — animal-wide template gallery |
| `multi_template/previews/compare.html` | NEW — before/after smoothing |
| `multi_template/previews/dashboard.html` | regenerated by dashboard.py |
| `multi_template/previews/locked/LOCKED_*` | regenerated to v3 |
| `~/.claude/skills/gps-art-splice-loop-template-routing/SKILL.md` | bumped 1.0.0 → 1.1.0 with snap-fix, scale 3-4km, smoothing, render-against-full-polyline, dashboard pattern |
| `~/.claude/projects/.../memory/lessons_elephant_lockin_config.md` | v3 update with snap-dedup + render-grey-template bugs |

## Branch status

- `claude/review-demo-route-yo15w` — 3 commits ahead of `origin/claude/review-demo-route-yo15w`, NOT pushed
- 3 commits: `cc2c94d` v1, `ea5ac53` v2, `f7df239` v3
- Working tree clean apart from this handoff + new docs/ entries

## Cross-references

- ADR: `docs/decisions/0001-snap-waypoints-to-distinct-graph-nodes.md`
- Analysis: `docs/analysis/elephant_lockin_v1_v2_v3.md`
- Next-session prompt: `docs/handoffs/multi_template_animals_rollout_prompt.md`
- Live dashboard: `file://.../multi_template/previews/dashboard.html`
- Before/after: `file://.../multi_template/previews/compare.html`
