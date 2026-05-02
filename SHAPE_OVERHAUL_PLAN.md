# DoodleRun Shape Overhaul Plan

**Date:** 2026-05-03
**Status:** Draft — ready for review
**Scope:** Finalize animal shapes, improve street-snap fidelity, automate SVG pipeline, distance budgets

---

## 1. Current State Summary

### Architecture

The prototype has a clean three-layer shape format per animal:

- **OUTLINE** — closed silhouette polyline (`List[Point]`, 30–80 waypoints)
- **INTERIOR_FEATURES** — list of interior-detail polylines (eyes, nostrils, whiskers)
- **METADATA** — description, source, license

The shape registry (`prototype/shapes.py`) auto-discovers shape files. The SVG pipeline (`tools/svg_to_shape.py`) supports two modes: `--mode single` (trace one sub-path) and `--mode union` (shapely-union multiple sub-paths into a merged silhouette), plus `--with-interior` for extracting interior strokes. Interior lines are wired into the route so the runner traces them during the run.

### Fidelity scoring

`prototype/fidelity.py` implements Modified Hausdorff Distance (Dubuisson & Jain 1994) — symmetric mean-nearest-neighbor distance, normalized by bounding-box diagonal. The grid-search algorithm (`route_generator.generate_search()`) tries multiple (center, scale) pairs and picks the lowest-fidelity-score candidate.

### Candidate shapes (v6)

Five animals with 5 candidates each were generated via `tools/gen_candidates.py`. The v6 preview (`samples/previews/v6/all_candidates.png`) shows outlines (blue) + interior features (red). Mix of full-body profiles, face-only designs, and sitting/walking poses.

### User picks from v6 review

| Animal  | Picked candidates | Notes |
|---------|------------------|-------|
| Pig     | 3, 4             | #3 chubby seated pig with curly tail; #4 side-profile with floppy ear |
| Cat     | 1                | Kawaii cat from freesvg.org — pointy ears, curled tail |
| Dog     | 1, 3             | #1 beagle with floppy ear; #3 sitting dog with perky ears |
| Dino    | 1, 2, 4          | #1 brontosaurus/stego hybrid; #2 T-Rex; #4 stegosaurus with plates |
| Chicken | 1                | Cartoon rooster from freesvg.org — jagged comb, tail feathers |

---

## 2. Finalizing Picked Shapes

### 2.1 Default shape selection

Each animal needs exactly one default. Recommendation based on visual distinctiveness at thumbnail scale and street-snap friendliness (fewer tight curves = better snapping):

| Animal  | Default | Rationale |
|---------|---------|-----------|
| Pig     | **Candidate 4** | Side-profile reads clearly at all scales. The round ear is a strong differentiator. Candidate 3's seated pose is charming but the curly-tail spiral is extremely hard to street-snap — tight spirals don't map to road grids. Keep #3 as an alternate. |
| Cat     | **Candidate 1** | Only pick. Kawaii blob with pointy triangle ears is the cat archetype. Already SVG-sourced with known CC0 license. |
| Dog     | **Candidate 1** | Floppy-ear beagle profile. The drooping ear is the key cat-vs-dog differentiator per the issue spec. Candidate 3 (sitting, perky ears) reads more like a cat at small scale — keep as alternate. |
| Dino    | **Candidate 1** | Brontosaurus + back plates. Long neck is the signature feature and creates a tall, distinctive silhouette. #2 (T-Rex) and #4 (stegosaurus) kept as alternates. |
| Chicken | **Candidate 1** | Only pick. Jagged comb + tail feathers are the identifiers. |

### 2.2 Promotion steps

1. Copy the chosen candidate file into `prototype/<animal>_shape.py`, adopting the new OUTLINE + INTERIOR_FEATURES + METADATA format.
2. Update `prototype/shapes.py` to import the new constants. The registry should expand to expose interior features and metadata, not just OUTLINE:
   ```python
   SHAPES: Dict[str, ShapeData] = { ... }  # ShapeData = namedtuple(outline, interior, metadata)
   ```
3. Keep non-default candidates in `prototype/alternates/` for user selection (future UI: "pick your pig style").
4. Regenerate preview images for the promoted defaults.

### 2.3 Shape refinements before promotion

Based on the v6 preview and the issue's design principles ("exaggerate distinctive features, simplify everything else"):

- **Pig #4**: The floppy ear loop is good but the body is too rectangular. Round out the belly curve. Add nostril dots as interior features.
- **Cat #1**: Ears could be slightly more exaggerated (taller triangles). The tail curl is subtle — make it more pronounced. Already has good kawaii proportions.
- **Dog #1**: Floppy ear droop is the right depth. Snout could be slightly longer to differentiate from cat. Tail-up angle is good.
- **Dino #1**: The three back plates are good but could be taller relative to the body to read at smaller scales. Neck height is already exaggerated — keep it.
- **Chicken #1**: Comb peaks should be sharper/taller. Tail feather fan could use one more peak. Beak needs to be more prominent.

---

## 3. Improving Shape Fidelity When Street-Snapped

This is the core technical challenge. The research reports and GitHub issue identify several approaches, ranked by implementation cost and expected impact.

### 3.1 Quick wins (this week)

**A. Add Fréchet distance as a secondary scoring metric.**

The current Modified Hausdorff scorer is good but has a known weakness: it's not order-preserving. A route that traces the pig backwards scores the same as one that traces it forwards. Discrete Fréchet distance (available in `shapely.frechet_distance` since Shapely 2.0) is order-aware and strictly better for "do these polylines trace the same path?"

Implementation: add a `frechet_score()` function to `fidelity.py` alongside the existing `fidelity_score()`. Combine as a weighted sum in the grid search:

```
combined_score = 0.6 * hausdorff_score + 0.4 * frechet_score
```

This is ~10 lines of code and uses a dependency already in the environment.

**B. Add buffered-IoU (area overlap) as a third metric.**

Stravart's key insight: area-difference between the desired polygon and the routed polygon penalizes "cut the corner" detours that Hausdorff misses. Use `shapely.symmetric_difference` after `buffer(width)` on both polylines.

**C. Switch from OSRM to OSMnx for local graph routing.**

Current pipeline makes HTTP round-trips to the public OSRM demo server for every waypoint pair. This is slow, rate-limited (1.1s delay in `osrm_client.py`), and prevents custom edge costs.

OSMnx loads the road network into a NetworkX MultiDiGraph in memory. For a ~5km shape, `ox.graph_from_point((lat,lon), dist=5000, network_type="walk")` fetches once and caches. All subsequent routing is local Python — no HTTP, no rate limits, no API costs.

This also unlocks the per-edge shape-fidelity cost from Waschk & Kruger (see 3.2).

### 3.2 Algorithmic upgrade (1-2 weeks)

**D. Implement Waschk & Kruger's C3 Riemann-sum edge cost.**

From "Automatic route planning for GPS art generation" (Computational Visual Media, 2019). Instead of routing between waypoints then measuring fidelity post-hoc, this approach bakes shape fidelity into the routing cost function itself:

```
C(P,N,S,E) = alpha * C1(N,E) + beta * C2(P,N) + gamma * C3(P,N,S,E)
```

Where C3 is a Riemann-sum approximation of the integrated distance between a candidate road edge and the target line segment. This makes the router naturally prefer roads that run parallel to the desired outline, rather than just hitting waypoints and hoping the connections look right.

Implementation: custom edge-weight function passed to `nx.shortest_path(G, u, v, weight=custom_cost)` on the OSMnx graph. Process the outline segment-by-segment with single-source Dijkstra. ~30 lines of NumPy for the C3 cost.

**E. Pilot inverse map-matching via Valhalla trace_attributes.**

The research reports identify this as potentially the lowest-cost, highest-impact approach. The idea: densely sample the animal outline (~1 point per 10m), treat it as a synthetic "GPS trace," and let an HMM map matcher find the best road-network path.

Valhalla's `trace_attributes` with `shape_match: "map_snap"` does this in a single HTTP call. Key parameters: `gps_accuracy` (set high to allow freedom) and `turn_penalty_factor`.

A/B test against the current grid search on 5 animals x 3 cities. If Valhalla matches within 10% on Hausdorff score, prefer it for operational simplicity.

**F. Add turning-function metric for rotation invariance.**

`pip install turning_function` — the Arkin et al. 1991 metric is rotation/scale/translation-invariant for closed polygons. This removes one dimension from the grid search (no longer need to try every rotation), making the search 5-10x faster at the same quality.

### 3.3 Advanced (if needed)

**G. Pilot Li & Fu's subgraph-matching approach.**

From "Invariant Spatial Relation-Based Road Network Graphics Retrieval for GPS Art" (ISPRS, 2026). Code at `github.com/liganggis/run_drawing`. This reframes the entire problem: instead of projecting a shape onto roads and measuring deviation, it searches the road network for subgraphs that inherently match the shape's turning angles and segment ratios.

Worth piloting on one animal in one city. If it produces visibly better results in <10s, refactor toward this paradigm. Their reported limitation ("complex graphics have stricter shape requirements") may be a blocker for detailed animals.

**H. Build an FMM-based pipeline.**

Fast Map Matching (C++ with Python bindings, 946 GitHub stars) with precomputed UBODT tables per city. Most principled formal framing but highest infrastructure cost. Only justified if DoodleRun serves many requests in the same cities.

---

## 4. Automated SVG-to-Route Pipeline

### 4.1 Current pipeline

`tools/svg_to_shape.py` already handles the SVG → shape conversion:

1. Parse SVG with `svgpathtools`
2. Sample sub-paths by arc length (200 points default)
3. Filter background rectangles
4. Pick largest sub-path (single mode) or union top-N (union mode)
5. RDP simplification to ~30-70 points
6. Y-flip, optional X-flip, normalize to target width
7. Optional interior feature extraction (`--with-interior`)

### 4.2 Recommended improvements

**Switch from RDP to Visvalingam-Whyatt simplification.**

Research report recommendation: VW preserves *visual area* (removes smallest-triangle vertices first), which is perceptually better for rounded animal shapes. RDP preserves perpendicular distance, which can produce visually awkward simplifications on curves.

Use `simplification` library (Rust-backed, microsecond-fast): `simplify_coords_vw(coords, number=30)` gives exactly 30 well-placed waypoints. The topology-preserving variant prevents self-intersections.

**Add automatic point-count targeting.**

Currently the user must tune `--rdp-eps` manually. Replace with `--target-points N` that uses VW's `number=` mode to hit exactly N points. Default to 35 for outlines, 8-12 per interior feature.

**Add shape validation step.**

After simplification, automatically check:
- Is the polygon simple (no self-intersections)? Use `shapely.Polygon(pts).is_valid`.
- Is the bounding-box aspect ratio reasonable (0.3 < w/h < 3.0)?
- Are distinctive features preserved? (Compare Fréchet distance of simplified vs. dense-sampled original; reject if > threshold.)

**Support Quick Draw dataset as input.**

The Google Quick, Draw! dataset (CC BY 4.0) has ~75,000 simplified human-drawn samples per category for all 5 DoodleRun animals. The `.ndjson` simplified format is already RDP-simplified at epsilon=2.0 and scaled to 256x256.

Add `tools/quickdraw_to_shape.py`:
1. Load category `.ndjson` (e.g., `pig.ndjson`)
2. Filter to `recognized=true`, stroke count <= 2
3. Concatenate strokes with bridging segments
4. VW-simplify to ~30 points
5. Output in standard shape-file format

This enables a "shape gallery" — instead of one fixed outline per animal, offer the user 10-50 curated variants. The grid search can also try multiple templates and pick the one that snaps best to the local street grid.

### 4.3 Pipeline for non-animal shapes

The architecture is already generic (OUTLINE + INTERIOR_FEATURES + METADATA). For future shapes (letters, numbers, logos, hearts, stars):

1. Source SVG or Quick Draw `.ndjson`
2. Run through `svg_to_shape.py` or `quickdraw_to_shape.py`
3. Shape file auto-discovered by glob in `shapes.py`
4. No animal-specific code needed

The only animal-specific logic is in `gen_candidates.py` (hand-crafted coordinate generation). For non-animal shapes, the SVG pipeline is the primary path.

---

## 5. Interior Line Strategy

### 5.1 Current implementation

Interior features are extracted as small sub-paths from the SVG that fall within the outline's bounding box. They're stored as `INTERIOR_FEATURES: List[List[Point]]` and wired into the route via `compose_route()` — the runner traces them between sections of the outline.

### 5.2 When interior lines add value

Interior features work best when:
- They're simple (2-4 point strokes — eyes, nostrils)
- They're close to the outline path (the runner doesn't have to detour far)
- They add recognizability (a pig face without nostril dots is less piggish)

Interior features hurt when:
- They require long detours from the outline (adds distance, breaks flow)
- They're too detailed to street-snap cleanly
- The shape is already recognizable from outline alone

### 5.3 Recommendations

**Keep interior features optional and minimal.** For v1, limit to:
- Pig: 2 nostril dots (short out-and-back strokes near the snout)
- Cat: 2 whisker strokes (if face-forward candidate used)
- Dog: 1 eye dot
- Dino: none (outline is already complex with back plates)
- Chicken: 1 eye dot, 1 wattle stroke

**Interior routing strategy:** When composing the route, insert interior features at the nearest point on the outline (minimizing detour distance). If the detour exceeds 15% of the total outline perimeter, skip that feature.

**Future enhancement:** Let the user toggle interior features on/off. Some runners want a clean outline; others want the detail.

---

## 6. Distance Budget & Search Algorithm

### 6.1 The problem

The current grid search optimizes purely for fidelity. This means it picks the largest possible scale (bigger shape = more road segments to work with = better fidelity). Result: cat/dog/chicken routes blow up to 45-70 km.

### 6.2 Recommended approach: soft penalty with hard cap

Add to the fidelity scorer:

```python
def combined_score(fidelity, route_distance_m, target_distance_m, max_distance_m):
    if route_distance_m > max_distance_m:
        return float('inf')  # hard cap
    distance_penalty = abs(route_distance_m - target_distance_m) / target_distance_m
    return fidelity + 0.3 * distance_penalty
```

- **Hard cap:** `max_distance_m = 2.0 * target_distance_m` — never exceed 2x the target.
- **Soft penalty:** weighted distance deviation penalizes routes far from target but doesn't dominate fidelity.
- **Weight tuning:** 0.3 is a starting point. If routes consistently hit the cap, decrease the weight; if they're always at target but ugly, increase it.

### 6.3 Scale grid seeding

Currently the scale grid is a geometric sweep from 0.6x to 3.0x of the distance-implied base scale. With the distance penalty:

- Narrow the sweep to 0.5x - 1.8x (skip scales that would exceed the hard cap)
- Add more granularity in the 0.8x - 1.2x range (most likely sweet spot)
- Pre-compute approximate route distance from scale before running OSRM/OSMnx (using outline perimeter * scale * cos(latitude) as a rough estimate)

### 6.4 Pareto front (future)

Surface 2-3 alternatives to the user: "Here's the most recognizable route (12km), here's a shorter option (8km, slightly less detailed), here's the closest to your target 10km." The grid search already produces multiple scored candidates — just return the top-3 instead of top-1.

---

## 7. Additional Recommendations from Research

### 7.1 Doodle source diversification

Instead of one fixed outline per animal, maintain a curated gallery of 10-50 outlines per category sourced from Quick, Draw! dataset. When generating a route:

1. Try the default outline first
2. If fidelity score exceeds threshold (e.g., > 0.05), try 5-10 alternate outlines
3. Pick the outline that best fits the local street grid

This is potentially the single biggest visual-quality win — different street grids suit different shape variants.

### 7.2 "Bird Mode" escape hatches

From RouteDoodle's UX: when a section of the outline has no nearby roads (park, river, railway), allow a straight-line "as the crow flies" segment instead of forcing a long detour. Mark these segments differently in the GPX (e.g., as waypoints rather than track points).

Implementation: during route generation, if the shortest path between two consecutive waypoints exceeds 3x the straight-line distance, flag it as a potential bird-mode segment and offer the user the choice.

### 7.3 Street grid pre-screening

Before running the full grid search, do a fast pre-screen:
1. Load OSMnx graph for the candidate area
2. Compute road density (total edge length / area)
3. Compute grid regularity (variance of edge angles)
4. Skip areas with road density below threshold (rural areas, industrial zones)

This avoids wasting compute on areas where no recognizable route is possible.

### 7.4 Shape similarity ensemble

Use multiple metrics for robust scoring (from Research Report 2):

| Metric | Library | Strength |
|--------|---------|----------|
| Modified Hausdorff | Current impl | Outlier-robust, fast |
| Discrete Frechet | `shapely.frechet_distance` | Order-preserving |
| Turning function | `turning_function` (PyPI) | Rotation-invariant |
| Buffered IoU | `shapely.symmetric_difference` | Penalizes detour shortcuts |
| Chamfer distance | `scipy.spatial.KDTree` | Fast pre-filter |

Combine via weighted sum or max-rank. This is robust against any single metric's pathologies.

### 7.5 Study real GPS art

The issue comments link to several galleries of successful GPS art:
- strav.art/home/cats-dogs — real Strava animal GPS art
- gpsdoodles.com — Stephen Lund's 80+ GPS doodles
- motera.app/best-gps-art-routes — viral GPS art routes

Key learnings from successful GPS artists: they spend hours finding the right street grid *first*, then adjust the shape to fit. DoodleRun's grid search does this automatically, but the search radius and grid density may need to increase. Stephen Lund's advice: "it is all about the planning ahead of time."

---

## 8. Implementation Roadmap

### Phase 1: Shape finalization (2-3 days)

- [ ] Promote picked candidates as defaults (Section 2.2)
- [ ] Apply shape refinements (Section 2.3)
- [ ] Expand shapes.py registry to ShapeData namedtuple
- [ ] Move non-default candidates to `prototype/alternates/`
- [ ] Regenerate preview images
- [ ] Add `/preview` endpoint for outline-only rendering (no OSRM)

### Phase 2: Scoring & distance (3-5 days)

- [ ] Add Frechet distance to `fidelity.py` (Section 3.1A)
- [ ] Add buffered-IoU metric (Section 3.1B)
- [ ] Implement distance budget with soft penalty + hard cap (Section 6.2)
- [ ] Narrow scale grid sweep (Section 6.3)
- [ ] A/B test combined scoring vs. MHD-only on 5 animals x 3 cities

### Phase 3: OSMnx migration (1 week)

- [ ] Replace OSRM with OSMnx local graph routing (Section 3.1C)
- [ ] Cache city graph extracts to disk (`ox.save_graphml`)
- [ ] Implement Waschk & Kruger C3 edge cost (Section 3.2D)
- [ ] Benchmark routing speed and quality vs. OSRM baseline

### Phase 4: Pipeline automation (3-5 days)

- [ ] Switch SVG pipeline from RDP to Visvalingam-Whyatt (Section 4.2)
- [ ] Add `--target-points N` flag
- [ ] Add shape validation (Section 4.2)
- [ ] Build `quickdraw_to_shape.py` for Quick Draw dataset ingestion (Section 4.2)
- [ ] Curate 10 outlines per animal from Quick Draw

### Phase 5: Polish & ship (3-5 days)

- [ ] Wire search mode into web SPA (`server/static/app.html`)
- [ ] Wire search mode into iOS app (`ios/DoodleRun/`)
- [ ] Implement Pareto front (return top-3 routes)
- [ ] Add street grid pre-screening (Section 7.3)
- [ ] README pass
- [ ] Sample gallery regeneration

### Future / exploratory

- [ ] Valhalla trace_attributes pilot (Section 3.2E)
- [ ] Li & Fu subgraph matching pilot (Section 3.3G)
- [ ] Shape gallery with per-grid-search template selection (Section 7.1)
- [ ] Bird Mode escape hatches (Section 7.2)
- [ ] Sketch-RNN for generative shape variety

---

## 9. Key References

### Academic papers
- Waschk & Kruger (2019), "Automatic route planning for GPS art generation," Computational Visual Media — Riemann-sum edge cost function
- Li & Fu (2026), "Invariant Spatial Relation-Based Road Network Graphics Retrieval for GPS Art," ISPRS — subgraph matching, code at github.com/liganggis/run_drawing
- Dubuisson & Jain (1994) — Modified Hausdorff Distance (current scorer)

### Key repos
- dsleo/stravart — closest end-to-end analog (Optuna grid search + area-difference scoring)
- gboeing/osmnx — canonical OSM graph library
- cyang-kth/fmm — Fast Map Matching (inverse map-matching approach)
- martinohanlon/quickdraw_python — Quick Draw dataset access
- cjekel/similaritymeasures — Frechet, DTW, area-between-curves
- urschrei/simplification — Rust-backed RDP + Visvalingam-Whyatt

### Data sources
- Google Quick, Draw! dataset — 75K simplified drawings per animal category, CC BY 4.0
- freesvg.org — CC0 cartoon animal SVGs (current cat + chicken source)

### GPS art galleries (design inspiration)
- strav.art/home/cats-dogs
- gpsdoodles.com (Stephen Lund)
- motera.app/best-gps-art-routes
- routedoodle.com (UX benchmark)
