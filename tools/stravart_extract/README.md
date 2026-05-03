# strav.art template extractor

Vision-extract template polylines from the [strav.art](https://www.strav.art)
gallery — animal silhouettes that real runners traced on real street grids.
We don't need their routes; we need their **shape priors**: "what does a
strong pig outline look like before any street snapping?"

## Pipeline

```
strav.art gallery page
  → scrape.py  (regex on rendered HTML, no JS)
  → scratch/stravart_images/<category>/*.{jpg,png,webp}    (gitignored)
  → extract.py (HSV red-mask → largest contour → VW simplify → normalize)
  → templates_stravart/<category>/*.json                   (tracked)
  → preview.py (numbered grids, 24 per PNG)
  → previews/<category>_grid_NN.png                        (tracked)
```

### Run

```bash
python3 -m pip install opencv-python-headless beautifulsoup4 requests \
    numpy pillow simplification matplotlib
python3 tools/stravart_extract/scrape.py            # ~1200 images, ~250 MB
python3 tools/stravart_extract/extract.py           # writes templates_stravart/
python3 tools/stravart_extract/preview.py           # writes previews/
```

`scrape.py` auto-handles macOS keychain TLS-inspection roots (Netskope etc.)
the same way `prototype/osrm_client.py:macos_keychain_bundle` does.

## Template JSON schema

```json
{
  "category": "elephants",
  "source_image": "ChelseaElephant.jpg",
  "source_url": "https://images.squarespace-cdn.com/...",
  "points": [[0.12, 0.34], ...],   // closed polygon in [0,1]^2, y-up cartesian
  "n_anchors": 27,                  // unique vertices (excludes closing duplicate)
  "bbox_aspect": 1.42,
  "fill_ratio": 0.18,               // contour bbox / source frame
  "contour_solidity": 0.71,         // area / convex_hull_area
  "dominance": 0.93                 // largest_contour_pixels / total_red_pixels
}
```

Coordinates are **abstract** — origin and scale of the source map are
discarded. Only the silhouette in its own normalized frame survives.

## Quality filters (in `extract.py`)

A template is rejected if any of:

- Largest red contour < 0.5 % of frame area (no trace) or > 85 % (zoom-in).
- Bounding-box aspect outside [0.25, 4.0] (sliver, not an animal).
- Contour perimeter < 200 px (too short to carry shape).
- Largest contour < 55 % of *total* red pixels (fragmented; e.g. trace
  has multiple disconnected segments — we'd only capture one slice).
- VW-simplified vertex count outside [12, 60].

## Legal

Fair use: transformative analysis of publicly visible imagery to learn
structural priors. We never redistribute strav.art images — `scratch/` is
gitignored. We track only abstract normalized coordinates and our own
preview renders. We're learning *"what shape works as a pig on streets,"*
not copying their routes.

## Failure modes worth knowing

- **Multi-piece artworks** (e.g. animal + word + label) → rejected by
  dominance filter. Acceptable loss.
- **Open polylines** (animal drawn as a line, not a closed loop) →
  `RETR_EXTERNAL` returns the outer perimeter of the thick stroke
  band, which slightly inflates the silhouette (≈ stroke half-width).
  Acceptable for templates; will smooth out under VW.
- **Non-red traces** (some artists use blue/green) → rejected at HSV
  threshold. Re-run with adjusted ranges if needed.
