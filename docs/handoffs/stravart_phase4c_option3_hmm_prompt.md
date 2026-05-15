# strav.art Phase 4c — Stream A: Option 3 (HMM map-matcher)

**Branch:** `claude/stravart-phase4c-option3-hmm` (from `claude/stravart-phase4b-tighten-fallback`)
**Predecessor handoff:** `docs/handoffs/stravart_phase4b_wrap_handoff.md`
**Parallel session:** B (option 4 refinements, `claude/stravart-phase4c-option4-refinements`) and C (dashboard + distance, `claude/stravart-phase4c-dashboard-distance`).
**File overlap:** `stravart/mapmatch.py` (A adds a new HMM mode, B refines via-node selection — additive, easy to merge). `stravart/reconstruct.py` (both A and B add knobs).

## The pitch

Options 1+2 (k-shortest-paths + Fréchet rerank) and Option 4 (OCR anchors as
hard via-points) both produced NEGATIVE results — see `stravart_phase4b_wrap_handoff.md`
for the diagnoses. The fundamental issue with both attempts: they operate
LOCALLY (one Dijkstra segment at a time), but the wrong-turn problem on
review-tier routes (#584 elephant, #53 Regent's Park) is GLOBAL — the cartoon's
overall shape disagrees with how real streets curve, and no per-segment
choice fixes it.

Option 3 is the right structural fix: a probabilistic / Hidden Markov Model
map matcher that scores *entire path likelihoods* against the observed shape,
not segment by segment. Standard solution in the GPS-trace literature.

## The three sub-options for this stream

Pick whichever installs cleanly. Try in this order:

### A1. `fmm` (Fast Map Matching) — first try

`pip install fmm` (or `pip install --user fmm`). Python+C++ wrapper.
Reference: https://github.com/cyang-kth/fmm.

If pip install works: thread an `fmm`-based map matcher into
`stravart/mapmatch.py` as an alternative to the current Dijkstra. Expose via
`reconstruct(mapmatch_mode="fmm" | "dijkstra")`.

Watch for: the `numpy 2.x` incompatibility documented in the predecessor
handoff. If `fmm` is built against `numpy<2`, you may need to coexist (we
already downgraded to `numpy<2` for `torch`).

### A2. In-house Viterbi over OSM edges — second try

If `fmm` won't install cleanly: build a Viterbi map matcher directly.

State: each OSM edge in the bbox subgraph.
Observation: each projected polyline point.
Emission probability: `exp(-d² / 2σ²)` where d = perpendicular distance from the observation to the edge centreline, σ ≈ 20m (cartoon stylisation tolerance).
Transition probability: high for staying-on-edge or stepping to an adjacent edge along shortest path; low for "teleporting" to a far edge.
Decode: standard Viterbi → globally most-likely edge sequence → reconstruct node path → coords.

Existing helpers to reuse:
- `mapmatch._haversine_m` for distances
- `fidelity_score.discrete_frechet_m` for the eventual fidelity score (unchanged)
- `osmnx`/`networkx` for the graph and edge geometry

### A3. Valhalla Meili — defer

Production-grade but needs a Valhalla server side-car. ~1 week including ops.
Don't attempt unless A1 and A2 both fail.

## Expected outcome on the curated 20

Predicted lift on the review-tier routes:

- **#584 Travelling Elephant** — currently fidelity 0.190 (review). HMM should push toward 0.5+ as the trunk no longer takes wrong turns.
- **#53 Regent's Park** — currently fidelity 0.365 (review). HMM should push toward 0.6+, possibly into strict-ship tier.
- **#910 London Marathon, #921 Hackney Horse** — already ship at 0.60/0.62. HMM should hold or lift slightly.

No expected change for OCR0 city-scale routes (no street snap involved).

## Validation

After implementation, run the same sweep harness used for options 1+2+4:

```bash
python3 stravart/data/phase4b_diag/sweep_options.py 584
python3 stravart/data/phase4b_diag/sweep_options.py 53
```

Extend `sweep_options.py` to include `mapmatch_mode="hmm"` cell. **Pin the
RANSAC seed** (`np.random.seed(42)` + `random.seed(42)` per cell) — this was
the lesson from the options 1+2 false-positive sweep.

Update `stravart/data/phase4b_diag/verdict_comparison.html` with the new
sweep table. Open via `open` in the browser per the user's preference.

## Done criteria

- [ ] `mapmatch_mode` knob threaded through (default "dijkstra" so existing tests pass)
- [ ] At least 5 new tests on the HMM matcher with the synthetic two-path-graph fixture
- [ ] Live sweep on #584 + #53 shows measurable fidelity lift (target: ≥1.5x baseline)
- [ ] HTML report updated + opened in browser
- [ ] Commit + push, no PR (user holds merge call)
- [ ] If HMM doesn't move the needle on either route, **document the negative result honestly** in the commit and HTML — same discipline as options 1+2+4

## Stream-B coordination

Stream B is working on option 4 refinements (per-street node enumeration via
Overpass, soft via constraint). The natural integration is: HMM
emission/transition probabilities could incorporate Stream B's per-street
node enumerations as additional soft signals. After both streams merge to
main, a follow-up could combine them. For Phase 4c, keep them independent.

## Files you'll likely touch

- `stravart/mapmatch.py` — new HMM matcher function (or class), `mapmatch_mode` dispatch
- `stravart/reconstruct.py` — thread `mapmatch_mode` parameter
- `stravart/reconstruct_pipeline.py` — same
- `stravart/cli.py` — new `--mapmatch-mode` flag
- `stravart/tests/test_mapmatch.py` — HMM tests
- `stravart/data/phase4b_diag/sweep_options.py` — extend sweep with HMM cell
- `stravart/data/phase4b_diag/verdict_comparison.html` — add a new sweep panel
