# Next session — Roll out v3 elephant recipe to the other 5 animals

**Predecessor:** `docs/handoffs/multi_template_elephant_lockin_handoff.md`
**Branch to start from:** `claude/review-demo-route-yo15w` (commit `f7df239`),
or branch off main once that branch is merged.

## Context (paste-ready cold start)

The elephant route is locked at two UK locations with the **v3 recipe** in
`multi_template/locked_routes.json`. Same recipe should now lock pig / cat /
dog / dragon / duck. The recipe is captured in skill
`gps-art-splice-loop-template-routing` v1.1.0 (locally authored — read
`~/.claude/skills/gps-art-splice-loop-template-routing/SKILL.md` first).

**Three knobs that mattered:**
1. `revisit_penalty_m=0`, `beta=6`, `n_waypoints=64`, rotation [-30°, +30°],
   length penalty off — verbatim from elephant v3
2. **Manual iconic-template whitelist per animal** — don't trust Optuna's
   rank-1; render the gallery, pick the 1-5 clearest profile templates by eye
3. **Scale 3-4 km** for ~40-50 km routes (compact, anatomy preserved)

**Two bugs already fixed:**
- `router.py` snaps waypoints to DISTINCT graph nodes (cKDTree, k=50). Don't
  revert this — it's load-bearing.
- `render_locked.py` uses the full template polyline as grey reference, not
  the sparse waypoint resample. `preview.py` was always correct.

## Start files to read

1. `~/.claude/skills/gps-art-splice-loop-template-routing/SKILL.md` v1.1.0 —
   full recipe + the two bug stories
2. `~/.claude/projects/-Users-huiyanwan-Documents-DoodleRun/memory/lessons_elephant_lockin_config.md`
   — what to override Optuna with and why
3. `docs/decisions/0001-snap-waypoints-to-distinct-graph-nodes.md` — the snap fix
4. `docs/analysis/elephant_lockin_v1_v2_v3.md` — time-wasters to avoid
5. `multi_template/locked_routes.json` — the locked elephant config as the schema
   to mirror per-animal

## Priority tasks

### P1 — Per-animal template whitelist (loop for each animal)

For each animal in `[pig, cat, dog, dragon, duck]`:

a. **Render the gallery** to see what templates exist:
   ```bash
   python3 -c "
   import sys; sys.path.insert(0, '.')
   from multi_template.build_template_gallery import render
   render(animal='pig')   # repeat for each animal
   "
   # writes multi_template/previews/_GALLERY_<animal>.png
   ```

b. **Present the gallery to the user** and ask them to pick 1-5 iconic
   side-view templates. User-pick beats Optuna's rank-1 on visual recognition
   (verified for elephant; ELE-S04 was the user pick, not rank-1).

c. **Save the whitelist** somewhere durable so the next iteration can reuse
   it — e.g. add a `_template_whitelist` field to each animal block in
   `locked_routes.json`.

### P2 — Run v3 search per (animal, location)

For each animal × each of `[st_albans, maidenhead_windsor]`:

```bash
python3 -m multi_template.run_search \
  --animal <pig|cat|dog|dragon|duck> \
  --location st_albans \
  --location maidenhead_windsor \
  --n-trials 80 \
  --router-revisit-penalty-m 0 \
  --router-beta 6.0 \
  --template-ids "<comma-sep user-picked vote IDs>" \
  --rotation-min-deg -30 --rotation-max-deg 30 \
  --length-penalty-per-km 0 \
  --n-waypoints 64 \
  --scale-min-m 3000 --scale-max-m 4000 \
  --keep-top 8 --render-top 8 \
  --out-suffix _v3
```

Then build the dashboard so the user can pick:

```bash
python3 -m multi_template.dashboard  # refreshes the HTML
open multi_template/previews/dashboard.html
```

### P3 — Verify and lock each animal

For each animal:
- Run `render_diagnostic` to confirm no Dijkstra-shortcut legs >2× mean.
- Run `render_big` for the LOCKED single-panel view.
- Pull the full-precision values from the chosen `_summary.json`
  (`top_candidates[N]`) and write them into `locked_routes.json` under
  `<animal>_<location>` keys. **Do NOT round** — center_lat/lon snap to
  nearest OSM nodes and rounding changes the leg sequence.
- Re-run `render_locked.py` to verify the length-band assertion passes (100m
  tolerance). If it fails, the router or graph cache changed; re-search.

### P4 — Update `render_locked.py` for multi-animal

Currently `render_locked.py` only handles `elephant_<location>` keys. Update
to iterate over all animals:

```python
animals = sorted({k.split("_")[0] for k in cfg if k.startswith(("elephant_", "pig_", "cat_", "dog_", "dragon_", "duck_"))})
for animal in animals:
    for loc in sorted(loc for loc in LOCATIONS if f"{animal}_{loc}" in cfg):
        ...
```

Or simpler: prefix all keys with the animal name and discover dynamically
(already partially done — `render_locked.py` discovers `elephant_<loc>` keys;
generalize the prefix).

## Tuning notes (per-animal differences to expect)

- **Pig:** rounder body, no tail-spike. May want smaller scale (2.5-3.5 km)
  since fewer appendages to spread waypoints across. Expect higher iou.
- **Cat:** narrow body with prominent ears. Ears may produce upward spikes
  similar to elephant's ear-bump artifact. Test smoothing sigma=2-3 if so.
- **Dog:** four legs + tail + ears. Similar to elephant. Use elephant's
  recipe verbatim; expect comparable iou.
- **Dragon:** tail + legs + wings. Wings have unusual geometry — may need
  to expand `--rotation-min-deg/-max-deg` to 60° (the dragon's "head" is
  often at an angle). Watch the diagnostic.
- **Duck:** mostly body + tail + a beak. Minimal appendage count. Expect
  highest iou but lowest visual complexity.

## What NOT to do (time-wasters from predecessor session)

- **Don't build an explicit anatomy decomposition** (pinch-pair, hull-concavity,
  tip-first spike detection). All three failed for elephant; the outline
  already encodes anatomy via splice loops. The denser-waypoints lever is
  simpler and works.
- **Don't tune `beta` per-animal upfront.** Default β=6 first; tighten to
  β=9-12 only if the per-leg diagnostic shows shortcuts AND a test render
  doesn't make St-Albans-style interior detours worse.
- **Don't trust Optuna's rank-1 by itself.** Render top-8 (`--render-top 8`)
  and let the user pick by eye. The fidelity metric does not capture "looks
  like an animal."
- **Don't use round numbers in `locked_routes.json`.** Always copy full-
  precision floats from the `_summary.json` top_candidates entry. The 100m
  length-band assertion in `render_locked.py` will fail otherwise.

## Output expected by end of next session

- `locked_routes.json` updated with 5 new animal blocks × 2 locations =
  10 new entries
- LOCKED PNGs for all 5 new animals at both locations in `multi_template/previews/locked/`
- Dashboard refreshed at `multi_template/previews/dashboard.html` showing all
  6 locked animals
- Single PR merging the rollout (probably from a branch like
  `feat/all-animals-locked-v3`) — or extend the current
  `claude/review-demo-route-yo15w` branch with the new commits.

## Pre-authorized commands

- All `python3 -m multi_template.*` invocations
- `gh repo view`, `gh pr list`, `gh issue list`
- `git push` only when the user explicitly asks
