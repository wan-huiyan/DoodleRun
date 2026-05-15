# DoodleRun: New GPS Art Route Generation Plan

**Date:** 2026-05-03
**Status:** Ready for implementation
**Goal:** Replace the current broken route generation with an algorithm that actually produces recognizable animal shapes on street networks.

---

## 1. Why the Current Approach Fundamentally Fails

The current pipeline in `route_generator.py` does this:

1. Take 40 shape waypoints, project them onto (lat, lon)
2. Send ALL 40 waypoints to OSRM in a single `/route/v1/foot/` request
3. OSRM finds the shortest walking path that visits all 40 points in order
4. Score the result with Modified Hausdorff Distance

**The core problem is step 2-3.** OSRM routes between consecutive waypoints via the *shortest road path*. But the shortest road path between two points almost never follows the straight line between them. It follows whatever streets happen to exist — zigzagging through grid blocks, detouring around parks, doubling back at dead ends. The result is a route where:

- Each segment between consecutive shape points is a random-looking squiggle
- The squiggles compound — by the time you've connected 40 points, the route looks like spaghetti
- The "fidelity search" (`generate_search`) tries 5 centers × 3 scales = 15 candidates, but all 15 produce spaghetti because the algorithm itself is wrong
- Scoring with Modified Hausdorff after the fact can't fix a route that was never constrained to follow the shape *during* generation

**This is not a tuning problem.** No amount of adjusting scales, centers, waypoint counts, or search radii will fix it. The algorithm lacks any mechanism to make intermediate road segments follow the desired outline. It only constrains the *endpoints* (waypoints), not the *paths between them*.

### What successful GPS art creators actually do

From studying the research reports, GPS art galleries (Stephen Lund, Lenny Maughan), and academic papers:

1. **They pick the street grid first, then adapt the shape to fit it.** Stephen Lund: "I wish I could say I free-hand these, but it is all about the planning ahead of time." He spends hours with a paper map finding streets that naturally trace the shape.

2. **They use streets that run *parallel* to the desired outline.** The key insight: you don't route between shape vertices — you find road segments that already happen to run in the right direction, then chain them together.

3. **They accept that the shape must compromise with the street grid.** A pig's belly curve becomes a sequence of right-angle steps on a Manhattan grid. The route is recognizable because the *overall envelope* traces the shape, even though individual segments are straight streets.

4. **Route distance matters — 15-30km is the sweet spot.** Short routes (5km) don't have enough road segments to resolve shape features. Each distinctive feature (ear, tail, leg) needs to span at least 2-3 city blocks to read visually.

---

## 2. What the Research Says Actually Works

### 2.1 Waschk & Krüger (2019) — Per-Edge Shape-Fidelity Cost

**Paper:** "Automatic route planning for GPS art generation," Computational Visual Media 5(3):303-310. Open access, CC BY 4.0.

**Key idea:** Instead of routing between waypoints and scoring afterwards, bake shape fidelity into the routing cost function. For each road segment (edge) in the network, compute how far it deviates from the nearest target outline segment. Roads that run parallel to the outline are cheap; roads that deviate are expensive.

The cost function per edge:
```
C(P,N,S,E) = α·C₁(N,E) + β·C₂(P,N) + γ·C₃(P,N,S,E)
```
Where:
- C₁ = distance from current node N to the current target segment endpoint E (progress toward the goal)
- C₂ = edge length (discourages U-turns and long detours)
- C₃ = **Riemann-sum of perpendicular distances** between the edge (P→N) and the target segment (S→E), sampled at n equally-spaced points

C₃ is the critical innovation. It's ~30 lines of NumPy and measures how closely a candidate road edge runs alongside the desired outline segment.

**Why this is the right core algorithm for DoodleRun:** It processes the outline segment-by-segment with Dijkstra, naturally preferring roads that trace the shape. No post-hoc scoring needed — shape fidelity is built into every routing decision.

**Limitations noted by the authors:** Fails in rural areas (not enough roads), fine details lost in checkerboard grids, requires manual placement/scale/orientation (our grid search addresses this).

### 2.2 Inverse Map-Matching — Treat the Outline as a GPS Trace

**Key insight from research report:** The GPS map-matching problem (noisy GPS points → road-snapped path) is exactly DoodleRun's problem in reverse. Densely sample the animal outline (~1 point per 10m), pretend it's a GPS trace, and let an HMM map matcher find the most likely road path.

**Best tools:**
- **Valhalla `trace_attributes` with `shape_match: "map_snap"`** — single HTTP call, tunable `gps_accuracy` and `turn_penalty_factor`. Lowest implementation cost.
- **FMM (Fast Map Matching)** — C++ with Python bindings, 946 stars. HMM + precomputed shortest-path tables. Highest quality but more infrastructure.
- **LeuvenMapMatching** — pure Python, easiest to hack the cost function.

**Why this could work:** HMM matchers consider the *entire trajectory* holistically, not just point-by-point snapping. They naturally handle the tradeoff between "follow the desired path closely" and "stay on real roads."

**Risk:** Map matchers are designed for *real* GPS noise (5-30m). A synthetic outline from a pig shape has very different characteristics — sharp corners, no noise, potentially no nearby roads. The `gps_error` / `radius` parameters may need aggressive tuning.

### 2.3 Li & Fu (2026) — Subgraph Matching

**Paper:** "Invariant Spatial Relation-Based Road Network Graphics Retrieval for GPS Art," ISPRS Int. J. Geo-Inf. 15(3):98. Code at `github.com/liganggis/run_drawing`.

**Completely different paradigm:** Instead of projecting a shape onto roads, search the road network for subgraphs that *inherently* match the shape's geometry. They represent both shape and road network as graphs with edges labeled by (turning angle, length ratio), then use backtracking subgraph isomorphism to find matches.

**Strengths:** Finds locations where the street grid naturally traces the shape — the holy grail. No need for the runner to force a shape onto an unwilling grid.

**Limitations:** Authors admit "complex graphics have stricter shape requirements" and single characters can take 0.3-1.7 seconds while multi-character combos take up to 30 minutes. Animal outlines with curves and appendages may be too complex.

**Verdict:** Worth piloting on one animal, but not the primary approach.

### 2.4 dsleo/stravart — Optuna Grid Search + Area Scoring

**Repo:** `github.com/dsleo/stravart`. Similar to our current approach but with two improvements:

1. **Area-difference scoring** (symmetric difference between desired polygon and routed polygon) — catches "cut the corner" detours that Hausdorff misses
2. **Optuna TPE sampler** instead of uniform grid search — much faster convergence over (center, scale, rotation, dilation)

**Verdict:** Same fundamental problem as our approach (routes between successive contour points), but the scoring is better. Worth stealing the area-difference metric; not worth adopting the overall architecture.

---

## 3. The New Algorithm

### 3.1 Architecture Overview

Replace the single OSRM call with a segment-by-segment OSMnx-based router that uses shape-fidelity-aware edge costs.

```
Input: animal outline (30-50 waypoints), center (lat/lon), target distance (15-30km)

1. SEARCH PHASE: Try multiple (center, scale, rotation) candidates
   For each candidate:
     a. Project outline onto geographic coordinates
     b. Load OSMnx walking graph for the area
     c. ROUTE PHASE: For each consecutive pair of outline segments:
        - Run modified Dijkstra with Waschk-Krüger C₃ cost
        - The router naturally follows roads that parallel the outline
     d. Score the complete route (multi-metric ensemble)
     e. Check distance constraints

2. Return the best-scoring candidate that meets distance bounds

Output: road-snapped polyline + GPX/KML
```

### 3.2 Core Routing: Segment-by-Segment Shape-Aware Dijkstra

This is the critical change. Instead of one OSRM call with 40 waypoints, we:

1. Load the road network with OSMnx into a NetworkX MultiDiGraph
2. Process the outline as a sequence of line segments (S₁→S₂, S₂→S₃, ..., Sₙ→S₁)
3. For each segment, run Dijkstra from the end of the previous segment's route to a node near the next shape vertex
4. The edge cost function for Dijkstra includes the C₃ Riemann-sum term — edges that run parallel to the current target segment are cheap, edges that deviate are expensive

**Edge cost function (pseudocode):**
```python
def shape_aware_cost(u, v, edge_data, target_segment_start, target_segment_end):
    edge_geom = edge_data.get('geometry', LineString([(u_lon, u_lat), (v_lon, v_lat)]))
    edge_length = edge_data['length']

    # C1: How much closer does this edge bring us to the target endpoint?
    dist_to_target = haversine(v, target_segment_end)

    # C2: Edge traversal cost (penalizes long detours)
    travel_cost = edge_length

    # C3: Riemann-sum of perpendicular distances from edge to target segment
    # Sample n points along the target segment, measure distance to the edge
    n_samples = max(3, int(edge_length / 50))  # sample every ~50m
    perp_distances = []
    for i in range(n_samples):
        t = i / (n_samples - 1)
        sample_pt = interpolate(target_segment_start, target_segment_end, t)
        d = point_to_line_distance(sample_pt, u, v)
        perp_distances.append(d)
    shape_deviation = sum(perp_distances) / n_samples

    return alpha * dist_to_target + beta * travel_cost + gamma * shape_deviation
```

**Why this works:** Every edge the router considers is evaluated against the current target segment. Roads running alongside the pig's belly are cheap. Roads cutting across it are expensive. The router naturally traces the shape.

### 3.3 Outline Pre-Processing

**Switch from RDP to Visvalingam-Whyatt simplification.** VW preserves visual area (removes smallest-triangle vertices first), which is perceptually better for rounded animal shapes. Use the `simplification` library (Rust-backed, microsecond-fast).

**Target: 30-50 waypoints per outline.** Fewer waypoints = fewer routing segments = faster. But too few loses distinctive features. 30-50 is the sweet spot based on the research.

**Quick Draw! dataset as a shape source.** Google's Quick, Draw! dataset has ~75K simplified human-drawn samples per category for all 5 DoodleRun animals. Instead of one fixed outline per animal, maintain a gallery of 10-50 curated variants. The search phase can try multiple templates and pick the one that best fits the local street grid. This is potentially the single biggest quality win — different street grids suit different shape variants.

### 3.4 Multi-Metric Scoring Ensemble

Replace the current MHD-only scorer with an ensemble:

| Metric | Library | What it catches |
|--------|---------|-----------------|
| Modified Hausdorff | Current impl | Overall proximity, outlier-robust |
| Discrete Fréchet | `shapely.frechet_distance` | Order-preserving — catches "right shape, wrong direction" |
| Buffered IoU | `shapely.symmetric_difference` after `buffer()` | Detour shortcuts that Hausdorff misses |
| Turning function | `pip install turning_function` | Rotation-invariant angular similarity |

Combined score:
```python
score = 0.35 * hausdorff + 0.30 * frechet + 0.20 * area_iou + 0.15 * turning
```

The turning function is rotation-invariant, which means we can remove rotation from the grid search (one fewer dimension = much faster search).

### 3.5 Distance Constraints

**Default target: 15-30km.** The research and real GPS art consistently show that routes under 10km don't have enough road segments to resolve shape features.

**Soft penalty with hard cap:**
```python
def distance_adjusted_score(fidelity, route_distance_m, target_distance_m):
    max_distance = 2.0 * target_distance_m
    if route_distance_m > max_distance:
        return float('inf')  # hard cap
    distance_penalty = abs(route_distance_m - target_distance_m) / target_distance_m
    return fidelity + 0.3 * distance_penalty
```

### 3.6 Grid Search Parameters

| Parameter | Current | New | Rationale |
|-----------|---------|-----|-----------|
| Search radius | 30km | 30km | Keep — need to search widely for suitable grids |
| Center candidates | 5 | 9-13 | More candidates, because we now route faster (local, no HTTP) |
| Scale candidates | 3 | 5-7 | Probe more scales; pre-filter by estimated perimeter |
| Rotation candidates | none | 4-8 (or 0 with turning function) | Rotation matters — a pig facing left on the grid is different from facing right |
| Template candidates | 1 | 3-5 | Try multiple Quick Draw! outlines per animal |
| Target distance default | 10km | 20km | Realistic minimum for recognizable shapes |
| Waypoints | 40 | 35 | Slightly fewer, better placed (VW vs RDP) |

**Total candidates per request:** 9 centers × 5 scales × 4 rotations × 3 templates = 540. With local OSMnx routing (~0.1-0.5s per candidate vs 1.1s OSRM), this is 1-5 minutes. Reduce with early termination (stop when score < threshold).

**Optimization: Optuna.** Replace the uniform grid with Optuna's TPE sampler (as dsleo/stravart does). After 20-30 uniform samples to seed the distribution, let Optuna focus on promising regions. Expect 3-5x speedup for the same quality.

---

## 4. Street Grid Pre-Screening

Before running the full search, do a fast pre-screen of candidate areas:

1. **Load OSMnx graph** for the candidate area
2. **Compute road density** = total edge length / area. Skip areas below 5 km/km² (rural, industrial)
3. **Compute grid regularity** = variance of edge bearing angles. Low variance = regular grid = easier to trace shapes
4. **Check connectivity** = is the walking graph connected in the candidate area? Disconnected components (parks, rivers, railways) kill routes

This avoids wasting compute on areas where no recognizable route is possible. Takes <1s per candidate area with OSMnx.

---

## 5. Fallback: Inverse Map-Matching via Valhalla

As a parallel implementation path, pilot Valhalla's `trace_attributes`:

1. Densely sample the animal outline (1 point per 10m → ~2000 points for a 20km route)
2. Call Valhalla with `shape_match: "map_snap"`, `gps_accuracy: 100` (high to allow freedom), `turn_penalty_factor: 50` (discourage U-turns)
3. Valhalla's HMM returns a road-snapped path in one call
4. Score with the multi-metric ensemble

**A/B test against the Waschk-Krüger approach on 5 animals × 3 cities.** If Valhalla produces comparable quality with 10x less code, prefer it. If not, use it as a fast "preview" mode and reserve W-K for "high quality" generation.

**Infrastructure:** Valhalla can be self-hosted via Docker (`ghcr.io/valhalla/valhalla:latest`), or use Mapbox's hosted API (free tier: 100K requests/month).

---

## 6. Implementation Phases

### Phase 1: Foundation (1 week)

**Goal:** Replace OSRM with OSMnx, implement basic shape-aware routing.

**Files to create/modify:**

- `prototype/osmnx_router.py` (NEW) — OSMnx graph loading, caching, and shape-aware Dijkstra
  - `load_graph(center_lat, center_lon, radius_m)` → NetworkX MultiDiGraph (cached to disk)
  - `shape_aware_route(graph, outline_segments, start_node)` → list of (lat, lon)
  - `waschk_kruger_cost(u, v, edge_data, segment_start, segment_end)` → float
- `prototype/fidelity.py` (MODIFY) — Add Fréchet distance and buffered IoU scorers
  - `frechet_score(idealized, snapped)` → float
  - `area_iou_score(idealized, snapped, buffer_m=50)` → float
  - `combined_score(idealized, snapped)` → float (weighted ensemble)
- `prototype/route_generator.py` (REWRITE) — New `generate_v2()` using OSMnx router
  - Keep `generate()` and `generate_search()` as legacy fallbacks
  - New `generate_v2(outline, center_lat, center_lon, target_distance_m, ...)` → GeneratedRoute
- `prototype/requirements.txt` (MODIFY) — Add `osmnx`, `shapely>=2.0`, `simplification`

**Key implementation detail for `osmnx_router.py`:**

```python
import osmnx as ox
import networkx as nx
from shapely.geometry import LineString, Point
import numpy as np

def load_graph(center_lat, center_lon, radius_m=15000):
    """Load OSM walking graph, cached to disk."""
    cache_key = f"{center_lat:.3f}_{center_lon:.3f}_{radius_m}"
    cache_path = f"graph_cache/{cache_key}.graphml"
    if os.path.exists(cache_path):
        return ox.load_graphml(cache_path)
    G = ox.graph_from_point((center_lat, center_lon), dist=radius_m,
                            network_type="walk", simplify=True)
    ox.save_graphml(G, cache_path)
    return G

def shape_aware_route(G, outline_projected, alpha=1.0, beta=0.5, gamma=2.0):
    """Route through the road network following the outline shape.

    Process outline segment-by-segment. For each segment, run Dijkstra
    with a cost function that penalizes edges deviating from the target segment.
    """
    full_route = []

    for i in range(len(outline_projected)):
        seg_start = outline_projected[i]
        seg_end = outline_projected[(i + 1) % len(outline_projected)]

        # Find nearest graph nodes to segment endpoints
        start_node = ox.nearest_nodes(G, seg_start[1], seg_start[0])  # lon, lat
        end_node = ox.nearest_nodes(G, seg_end[1], seg_end[0])

        if start_node == end_node:
            continue

        # Custom weight function for this segment
        def weight_fn(u, v, data):
            return _segment_cost(G, u, v, data, seg_start, seg_end,
                                 alpha, beta, gamma)

        try:
            path = nx.shortest_path(G, start_node, end_node, weight=weight_fn)
            path_coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in path]
            full_route.extend(path_coords)
        except nx.NetworkXNoPath:
            # Fallback: straight snap, skip this segment
            full_route.append(seg_end)

    return full_route

def _segment_cost(G, u, v, data, seg_start, seg_end, alpha, beta, gamma):
    """Waschk-Krüger inspired edge cost."""
    u_lat, u_lon = G.nodes[u]['y'], G.nodes[u]['x']
    v_lat, v_lon = G.nodes[v]['y'], G.nodes[v]['x']

    edge_length = data.get('length', 0)

    # C1: distance from v to segment endpoint (progress)
    c1 = haversine((v_lat, v_lon), seg_end)

    # C2: edge length (travel cost)
    c2 = edge_length

    # C3: perpendicular distance from edge midpoint to target segment
    mid_lat = (u_lat + v_lat) / 2
    mid_lon = (u_lon + v_lon) / 2
    c3 = point_to_segment_distance((mid_lat, mid_lon), seg_start, seg_end)

    return alpha * c1 + beta * c2 + gamma * c3
```

**Verification step:** Generate pig/cat/dog routes at 3 locations each. Compare visually against current OSRM output. The new routes should show road segments that clearly follow outline edges rather than random zigzags.

### Phase 2: Search Optimization (1 week)

**Goal:** Effective grid search with distance constraints and multi-metric scoring.

**Files to create/modify:**

- `prototype/route_generator.py` (MODIFY) — Add `generate_search_v2()` with:
  - Wider search grid (9-13 centers, 5-7 scales, 4-8 rotations)
  - Multi-metric scoring ensemble
  - Distance soft penalty + hard cap
  - Early termination when score < threshold
  - Pre-screening of candidate areas (road density check)
- `prototype/grid_prescreener.py` (NEW) — Fast road density / connectivity checks
- `prototype/fidelity.py` (MODIFY) — Wire up the combined scorer with all 4 metrics

**Optuna integration (optional but recommended):**
```python
import optuna

def generate_search_optuna(outline, center_lat, center_lon, target_distance_m,
                           n_trials=100, timeout_s=120):
    G = load_graph(center_lat, center_lon, radius_m=30000)

    def objective(trial):
        offset_lat = trial.suggest_float('offset_lat', -0.15, 0.15)
        offset_lon = trial.suggest_float('offset_lon', -0.15, 0.15)
        scale = trial.suggest_float('scale', 0.5, 3.0, log=True)
        rotation_deg = trial.suggest_float('rotation', 0, 360)

        lat = center_lat + offset_lat
        lon = center_lon + offset_lon
        projected = project_and_rotate(outline, lat, lon, scale, rotation_deg)
        route = shape_aware_route(G, projected)

        if not route:
            return float('inf')

        route_distance = polyline_length(route)
        fidelity = combined_score(projected, route)
        return distance_adjusted_score(fidelity, route_distance, target_distance_m)

    study = optuna.create_study(direction='minimize',
                                sampler=optuna.samplers.TPESampler(n_startup_trials=20))
    study.optimize(objective, n_trials=n_trials, timeout=timeout_s)
    # ... build and return best GeneratedRoute
```

**Verification step:** Run the Optuna search on 5 animals × 5 cities. Compare best scores and visual quality against Phase 1's fixed grid. Measure wall-clock time.

### Phase 3: Shape Gallery + Quick Draw! (3-5 days)

**Goal:** Multiple outline variants per animal for better grid-fitting.

**Files to create/modify:**

- `tools/quickdraw_to_shape.py` (NEW) — Download and curate Quick Draw! exemplars
  - Filter: `recognized=True`, stroke count ≤ 2, path length in 30th-70th percentile
  - Concatenate strokes with short bridging segments
  - VW-simplify to ~30-50 points
  - Output as standard shape format
- `prototype/shapes.py` (MODIFY) — Expand registry to support multiple variants per animal
  ```python
  SHAPES: Dict[str, List[ShapeData]] = {
      "pig": [pig_default, pig_alt_1, pig_alt_2, ...],
      ...
  }
  ```
- `prototype/route_generator.py` (MODIFY) — `generate_search_v2()` tries top-N templates per animal

**Verification step:** For each animal, generate routes with 5 different outline variants at the same location. The best-scoring variant should visually outperform the fixed default outline.

### Phase 4: Valhalla Pilot (3-5 days, parallel with Phase 2-3)

**Goal:** A/B test inverse map-matching against Waschk-Krüger.

**Files to create/modify:**

- `prototype/valhalla_client.py` (NEW) — Wrapper for Valhalla `trace_attributes`
  - `map_match_outline(outline_latlon, gps_accuracy=100, turn_penalty=50)` → road-snapped path
- `docker-compose.yml` (NEW or MODIFY) — Add Valhalla container with local OSM extract
- `prototype/route_generator.py` (MODIFY) — Add `generate_valhalla()` as alternative backend

**A/B test protocol:**
- 5 animals × 5 cities × 3 distances = 75 test cases
- Compare: combined fidelity score, visual quality (blind human ranking), generation time
- Decision threshold: if Valhalla matches W-K within 15% on fidelity and is 5x faster, prefer Valhalla for the default "fast" mode

### Phase 5: Server + App Integration (3-5 days)

**Goal:** Wire the new algorithm into the FastAPI server and iOS app.

**Files to modify:**

- `server/main.py` — Import `generate_v2` / `generate_search_v2` instead of legacy functions
- `server/models.py` — Add fields for: `algorithm` (v1/v2/valhalla), `rotation_deg`, `template_id`, `fidelity_breakdown` (per-metric scores)
- `server/static/app.html` — Update UI:
  - Default distance slider: 15-30km range (was 5-20km)
  - Add "quality" toggle: Fast (Valhalla) vs. Best (W-K + Optuna)
  - Show fidelity score breakdown
  - Display multiple route candidates (Pareto front)
- `ios/DoodleRun/` — Matching changes to Swift models and UI

---

## 7. Dependencies to Add

```
# prototype/requirements.txt additions
osmnx>=2.0
simplification>=0.7
shapely>=2.0
optuna>=3.0
turning_function>=0.1  # optional, for rotation-invariant scoring
similaritymeasures>=1.0  # optional, for additional metrics
```

**OSMnx** replaces OSRM entirely for routing. No more HTTP round-trips, no rate limits, no dependency on the public demo server.

**Simplification** (Rust-backed) replaces the hand-rolled RDP in `svg_to_shape.py`.

**Optuna** replaces the uniform grid search for the (center, scale, rotation) parameter space.

---

## 8. What to Delete

- `prototype/osrm_client.py` — No longer needed once OSMnx routing is stable. Keep temporarily as fallback.
- The `REQUEST_DELAY_S = 1.1` bottleneck — gone entirely with local routing.
- The `macos_keychain_bundle()` SSL workaround — no more HTTPS calls for routing.
- The `scale *= ratio ** 0.5` iterative rescaling loop in `generate()` — replaced by proper grid search with distance constraints.

---

## 9. Risks and Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| OSMnx graph loading is slow for large areas (>1GB RAM) | Medium | Cache graphs to disk with `ox.save_graphml()`. Pre-compute for target cities. Limit radius to 15km per candidate. |
| Waschk-Krüger cost function produces poor results on irregular grids | Medium | A/B test against Valhalla. Fall back to inverse map-matching if W-K doesn't outperform. |
| 540-candidate search takes too long (>5 min) | Medium | Optuna with timeout=120s. Early termination. Pre-screen areas. Reduce to 100-200 candidates for interactive use. |
| Quick Draw! outlines are too abstract for some animals | Low | Manually curate the top 10 per category. Keep current SVG-sourced outlines as defaults. |
| Shape-aware Dijkstra gets stuck in local minima | Medium | Use k-shortest-paths (`nx.shortest_simple_paths`) and pick the one with best shape fidelity. Allow backtracking. |
| Turning function library has max-points limit | Low | Subsample both polylines to 100 points before scoring. |

---

## 10. Success Criteria

A route passes the "squint test": if you squint at it on a map, you can tell it's a pig/cat/dog/dino/chicken. Concretely:

1. **Fidelity:** Combined score (MHD + Fréchet + IoU + turning) < 0.04 (normalized) for at least 3 of 5 animals in at least 3 of 5 test cities
2. **Distance:** Within ±30% of the 20km default target
3. **Recognizability:** In a blind test, 7/10 people correctly identify the animal from the route map
4. **Speed:** < 2 minutes for interactive "fast" mode, < 5 minutes for "best quality" mode
5. **Distinctive features preserved:** Each animal's signature feature (pig's curly tail, cat's pointed ears, dog's floppy ear, dino's back plates, chicken's comb) is visually distinguishable in the route

---

## 11. Key References

### Must-read papers
- Waschk & Krüger (2019), "Automatic route planning for GPS art generation," Computational Visual Media — [PDF](https://link.springer.com/content/pdf/10.1007/s41095-019-0146-z.pdf)
- Li & Fu (2026), "Invariant Spatial Relation-Based Road Network Graphics Retrieval for GPS Art," ISPRS — code at [github.com/liganggis/run_drawing](https://github.com/liganggis/run_drawing)

### Must-study repos
- [dsleo/stravart](https://github.com/dsleo/stravart) — closest end-to-end analog (Optuna + area scoring)
- [gboeing/osmnx](https://github.com/gboeing/osmnx) — canonical OSM graph library
- [cyang-kth/fmm](https://github.com/cyang-kth/fmm) — Fast Map Matching
- [googlecreativelab/quickdraw-dataset](https://github.com/googlecreativelab/quickdraw-dataset) — shape source
- [urschrei/simplification](https://github.com/urschrei/simplification) — VW polyline simplification
- [cjekel/similaritymeasures](https://github.com/cjekel/similarity_measures) — Fréchet, DTW, area-between-curves

### GPS art inspiration
- [gpsdoodles.com](https://gpsdoodles.com) — Stephen Lund's 80+ GPS doodles
- [routedoodle.com](https://www.routedoodle.com) — UX benchmark, Bird Mode concept
- [strav.art](https://strav.art) — community GPS art gallery
