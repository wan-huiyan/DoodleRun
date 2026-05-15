# strav.art Phase 4c — Stream B: Option 4 refinements

**Branch:** `claude/stravart-phase4c-option4-refinements` (from `claude/stravart-phase4b-tighten-fallback`)
**Predecessor handoff:** `docs/handoffs/stravart_phase4b_wrap_handoff.md`
**Parallel session:** A (option 3 HMM) and C (dashboard + distance).
**File overlap:** `stravart/mapmatch.py` (B refines existing `via_nodes` selection; A adds HMM mode — additive). `stravart/reconstruct.py` and `stravart/crossref.py` may also be touched.

## The pitch

Option 4 (OCR anchors as Dijkstra via-points) shipped in Phase 4b but
produced a NEGATIVE result on the live sweep:

- #584 Elephant fidelity 0.190 → 0.162 (worse, +4km detour length)
- #53 Regent's Park fidelity 0.365 → 0.185 (much worse, frechet 134→1383m)

Diagnosis: Nominatim returns ONE point per street (the cluster-centroid
node). But streets are 1D objects — Felix Road is 800m long, the cartoon
crosses Felix Road at a specific point along its length, and Nominatim's
node may be far from that crossing. Pinning forces detours.

This stream tries TWO refinements that address the Nominatim-coarseness
problem directly:

### B1. Per-street node enumeration (refinement-1)

Instead of pinning to Nominatim's one centroid node, enumerate ALL OSM
nodes belonging to each OCR'd street via an Overpass query
(`way[name="Felix Road"]`), then pick the one CLOSEST TO WHERE THE
PROJECTED CONTOUR ACTUALLY CROSSES the street.

Algorithm:
1. For each RANSAC-inlier GCP, query Overpass: `way[name="<street>"](bbox)` filtered to the cluster bbox.
2. Collect all `nd` (way-member) node ids → fetch their (lat, lon) via Overpass `node(id:N)`.
3. From the projected polyline (already in `rec.geo_polyline`), find the point closest to ANY node on that street.
4. The OSM node nearest that "cartoon crossing point" is the right via-node.
5. Pass to `map_match(via_nodes=...)` (existing infrastructure).

Watch for: Overpass rate limits + ~3s extra per OCR'd street. For routes
with 15 streets that's ~45s extra. Cache per street name. Consider batching.

The existing `stravart/crossref.py` already does Overpass queries with
caching — extend that, don't reinvent.

### B2. Soft via constraint (refinement-2)

Alternative: instead of pinning to ONE specific node, treat each via as
"path must pass within R metres of (lat, lon)". Implementation could go
either of two ways:

**B2a. Pre-route filter** — for each via, identify the K closest OSM nodes
within R = 100m. Run `map_match` once per combination and pick the best by
shape fidelity. Combinatorial but K is small (3-5).

**B2b. Edge-weight modification** — bias the Dijkstra edge weights so
that staying near the via is cheaper than detouring. Concretely: for each
edge in the graph, subtract a Gaussian bonus based on distance to the
nearest via point.

B2b is structurally closer to HMM emission probabilities (Stream A's
territory). If Stream A is going well, B2 may be redundant. Build B1 first
— it's the cleaner mechanical fix and doesn't overlap with A.

## Expected outcome

B1 should land the via-nodes ON the cartoon's actual crossings, eliminating
the detour penalty. Target: option-4 fidelity 0.162 → ≥0.20 on the
elephant, ≥0.40 on Regent's Park. **If B1 STILL doesn't improve fidelity,
the failure isn't via-node selection — it's the fundamental cartoon-vs-real-
streets gap, and Stream A is the only path forward.**

## Validation

Same sweep harness as the prior negative-result evaluation:

```bash
python3 stravart/data/phase4b_diag/sweep_options.py 584
python3 stravart/data/phase4b_diag/sweep_options.py 53
```

Add a new sweep cell with `via_node_selection="per-street"` (the new
behaviour). RANSAC seed pinned per cell. Compare to baseline + existing
Phase 4b option 4 (Nominatim-centroid pinning).

Update `verdict_comparison.html` with the new sweep panel. Open via `open`
in browser.

## Done criteria

- [ ] Per-street Overpass query helper in `stravart/crossref.py` (reuses existing cache)
- [ ] Via-node selection refactored: dispatches between "nominatim-centroid" (current) and "per-street" (new)
- [ ] At least 4 new tests covering: per-street enumeration, crossing-point selection, cache hit, empty street result
- [ ] Live sweep shows measurable lift on #584 OR #53 (target: option-4 fidelity ≥1.2× the negative-result baseline)
- [ ] HTML report updated + opened in browser
- [ ] Commit + push, no PR
- [ ] If refinement-1 STILL doesn't lift fidelity, document the negative result and defer to Stream A's HMM

## Stream-A coordination

Stream A is building an HMM map-matcher. If A succeeds, B's value drops
(HMM emission probabilities subsume the soft-via-constraint problem). If A
fails or partially fails, B's per-street node enumeration becomes a
candidate input to a hybrid (HMM + accurate vias).

After both streams merge, a follow-up session can decide whether to
combine. For Phase 4c, keep them independent.

## Files you'll likely touch

- `stravart/crossref.py` — add per-street Overpass helper, reuse cache
- `stravart/mapmatch.py` — extend `via_nodes` to accept per-street pre-enumeration
- `stravart/reconstruct.py` — thread new selection mode through `_city_scale_fallback`'s neighbour (the affine snap path)
- `stravart/cli.py` — new `--via-node-selection` flag
- `stravart/tests/test_crossref.py` — new tests
- `stravart/tests/test_mapmatch.py` — new tests
- `stravart/data/phase4b_diag/sweep_options.py` — add sweep cell
- `stravart/data/phase4b_diag/verdict_comparison.html` — update report
