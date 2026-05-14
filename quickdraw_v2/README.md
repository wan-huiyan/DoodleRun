# DoodleRun v2 — Multi-template GPS art route generation

A research-informed rebuild of DoodleRun's route generation. The thesis,
in one line:

> **The shape is a family of acceptable variants, not a single fixed polyline.**
> Search jointly over (template, placement, scale, orientation) and let the street
> grid do the work.

## Why v2 exists

The original DoodleRun project (`prototype/`, `server/`, `ios/`) used a single
canonical outline per animal and tried to project it onto whatever streets
existed at the user's tap point. The v1 fidelity-first grid search (Hausdorff
scoring + center/scale grid) was an improvement but routes still didn't
"look like" their target animal. See [GitHub issue #1](https://github.com/wan-huiyan/DoodleRun/issues/1).

v2 replaces the single-outline-per-animal assumption with a **template
library**, drawn from two complementary sources:

1. **Quick Draw** (Google Creative Lab, CC BY 4.0) — clean human sketches.
   Per the `quickdraw-outline-only-extraction` skill: take the longest stroke
   as the main silhouette, drop interior strokes that lie ≥70% inside the
   buffered convex hull, splice "appendage" strokes (legs, tail, ear) as
   out-and-back spikes — exactly what real GPS-art runners do when they reach
   a leg or tail tip.
2. **strav.art** — a curated 3,000+ gallery of finished real-world GPS art.
   We use OpenCV (HSV red-mask + morphological close + outermost contour) to
   recover the SHAPE polyline from each gallery image, then normalize and
   simplify. The original images are **not** redistributed; we keep only the
   abstract normalized shape coordinates. Cited as the visual gold standard
   the route generator aims to imitate.

## Animal coverage

The Quick Draw dataset has 345 fixed categories. `chicken` and `dinosaur` are
**not** among them, so we substitute the closest-shape neighbours:

| DoodleRun animal | Quick Draw category | strav.art gallery       |
|------------------|---------------------|-------------------------|
| pig              | `pig`               | `/mammals-copy`         |
| cat              | `cat`               | `/cats-dogs-copy`       |
| dog              | `dog`               | `/cats-dogs-copy`       |
| dinosaur         | `dragon`            | `/dinosaurs-copy`       |
| chicken          | `duck`              | `/birds-copy`           |
| elephant (bonus) | `elephant`          | `/elephants-copy`       |

Elephant is added as a 6th option because the strav.art elephant gallery is
the strongest evidence we have of "what GPS art should look like" (clear body
+ four downward leg-loops + trunk + ear + tail) — and because Google's
`elephant` dataset exists.

## Pipeline

```
data/
├── *.recognized.ndjson        # raw Quick Draw streams (gitignored, 3000 ea)
└── strav_raw/<animal>/        # raw gallery images (gitignored, ~80 ea)

scripts/
├── download_quickdraw.py      # streams ndjson, keeps recognized=true
├── extract_outlines.py        # outline-only-extraction skill
├── scrape_stravart.py         # gallery -> CDN image URLs -> jpg
├── extract_strav_templates.py # OpenCV HSV red mask -> contour -> simplify
└── make_preview_grids.py      # render numbered voting grids

sketches/<animal>/             # 200 normalized Quick Draw outlines per animal
templates_strav/<animal>/      # ~80 normalized strav.art templates per animal
previews/<animal>_combined.png # 30+30 vote grid
```

## How voting works

Each cell in `previews/<animal>_combined.png` is labelled with a vote ID:

- `<ANIMAL>-Q01` … `<ANIMAL>-Q30`  (warm orange tint = Quick Draw rows 1-5)
- `<ANIMAL>-S01` … `<ANIMAL>-S30`  (cool blue tint = strav.art rows 6-10)

Where `<ANIMAL>` is the first three letters: PIG, CAT, DOG, DRA (dragon/dino),
DUC (duck/chicken), ELE.

Reply with a list of vote IDs you approve — anything from "PIG-Q03 PIG-S07" to a
longer list. Approved templates form the search library for the multi-template
route generator (next phase).

## Current grid status

Run `python3 scripts/make_preview_grids.py` to regenerate. The current grids
combine top 30 Quick Draw + top 30 strav.art per animal (top 12 strav.art for
pig because the mammals gallery filename hint catches few pigs).

## Next phase (after voting)

Multi-template route search (planned, not yet implemented):

1. Load OSMnx graph for England target areas (St Albans, Milton Keynes,
   Hertfordshire, outer London) at 30 km radius.
2. For each approved template, sweep (placement × scale × rotation) and use
   Waschk-Krüger Riemann-sum cost as the per-edge weight in NetworkX Dijkstra.
3. Score each candidate route with an ensemble of metrics (Modified Hausdorff
   + discrete Fréchet + buffered-IoU) — and a perceptual gate against the
   nearest strav.art exemplar of the same animal.
4. Default route range: 15–30 km. Search within ~30 km radius of the user's
   tapped location.

## Licensing notes

- **Quick Draw data**: CC BY 4.0, attribution required if we redistribute.
  We don't redistribute the raw ndjson; we redistribute extracted normalized
  shape coordinates which are facts, not creative content.
- **strav.art images**: "All rights reserved" per their footer. We don't
  redistribute their images. We extract abstract shape coordinates for
  internal template-fitting use only — transformative analysis, not republication.
- **Our extracted templates and previews**: same licence as the rest of the
  DoodleRun repo.
