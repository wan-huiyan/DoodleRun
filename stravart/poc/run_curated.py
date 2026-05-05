"""Run the Phase 4a curated-20 PoC batch.

Reads ``stravart/data/phase4a_poc/curated_20.json`` and runs
:func:`stravart.reconstruct.reconstruct` on every image, persisting:
    - the original image bytes (so re-runs / diagnostics don't re-fetch),
    - the cleaned contour mask + skeleton (PNG),
    - the OCR result with bounding boxes overlayed (PNG),
    - the georectification GCPs + RMSE diagnostics (JSON),
    - the projected-vs-snapped polyline overlay (PNG),
    - the GPX file when confidence ≥ ``min_confidence``,
    - a single summary JSON ``reconstruction.json`` per row capturing
      every numeric/textual signal we used to compute confidence.

Resumable: if ``reconstruction.json`` already exists for a row, that row is
skipped unless ``--retry`` is passed. The Nominatim cache is shared across
all 20 rows by default.

Usage:
    python -m stravart.poc.run_curated \\
        --db stravart/data/stravart.sqlite \\
        --selection stravart/data/phase4a_poc/curated_20.json \\
        --out-dir stravart/data/phase4a_poc \\
        --crossref-cache stravart/data/nominatim_cache.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import sqlite3
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from stravart.crossref import NominatimStreetClient
from stravart.gpx_export import GpxMetadata
from stravart.reconstruct import Reconstruction, reconstruct


logger = logging.getLogger("stravart.poc")


# ---------- per-row directory layout --------------------------------------

def row_dir(out_dir: Path, route_id: int) -> Path:
    d = out_dir / "per_image" / f"route_{route_id:05d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def is_complete(d: Path) -> bool:
    return (d / "reconstruction.json").exists()


# ---------- artifact writers ----------------------------------------------

def save_original(d: Path, bgr: np.ndarray) -> str:
    p = d / "01_original.jpg"
    cv2.imwrite(str(p), bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return p.name


def save_contour(d: Path, bgr: np.ndarray, rec: Reconstruction) -> str | None:
    if rec.contour is None:
        return None
    h, w = bgr.shape[:2]
    canvas = bgr.copy()
    # Skeleton in lime green; mask edges in cyan.
    if rec.contour.mask is not None:
        edges = cv2.Canny(rec.contour.mask.astype(np.uint8), 50, 150)
        canvas[edges > 0] = (255, 255, 0)
    if rec.contour.polyline:
        pts = np.array(rec.contour.polyline, dtype=np.int32)
        for x, y in pts[::3]:
            if 0 <= x < w and 0 <= y < h:
                cv2.circle(canvas, (int(x), int(y)), 2, (0, 255, 0), -1)
    p = d / "02_contour.png"
    cv2.imwrite(str(p), canvas)
    return p.name


def save_ocr_overlay(d: Path, bgr: np.ndarray, rec: Reconstruction) -> str | None:
    if rec.ocr is None:
        return None
    canvas = bgr.copy()
    # Draw fragment bboxes (small magenta) + merged street candidates (yellow).
    if rec.ocr.fragment_boxes:
        for (xc, yc, w_, h_) in rec.ocr.fragment_boxes:
            x1, y1 = int(xc - w_ / 2), int(yc - h_ / 2)
            x2, y2 = int(xc + w_ / 2), int(yc + h_ / 2)
            cv2.rectangle(canvas, (x1, y1), (x2, y2), (255, 0, 255), 2)
    for cand in rec.ocr.street_candidates:
        text = f"{cand.normalized}"
        # Find first fragment box that overlaps this candidate roughly.
        # candidate_pixel_anchors gives the per-candidate centroid.
        pass
    from stravart.ocr import candidate_pixel_anchors
    for cand, (px, py) in candidate_pixel_anchors(rec.ocr):
        cv2.circle(canvas, (int(px), int(py)), 8, (0, 255, 255), 3)
        cv2.putText(
            canvas, cand.normalized, (int(px) + 10, int(py) - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2,
        )
    p = d / "03_ocr.png"
    cv2.imwrite(str(p), canvas)
    return p.name


def save_route_overlay(d: Path, rec: Reconstruction) -> str | None:
    """Render projected vs. snapped polyline in geographic coords (no basemap)."""
    if rec.geo_polyline is None:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    fig, ax = plt.subplots(figsize=(8, 8), dpi=120)
    proj = np.array(rec.geo_polyline)              # (lat, lon)
    ax.plot(proj[:, 1], proj[:, 0], color="#1f77b4", lw=1.0, label="projected (from contour)")
    if rec.matched is not None and rec.matched.coords:
        snap = np.array(rec.matched.coords)
        ax.plot(snap[:, 1], snap[:, 0], color="#d62728", lw=1.5, alpha=0.7, label="snapped (OSM)")
    ax.set_aspect("equal", adjustable="datalim")
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    ax.legend(loc="best", fontsize=9)
    ax.set_title(f"projected vs snapped — {len(proj)} pts, fidelity={getattr(rec.fidelity, 'score', float('nan')):.2f}")
    p = d / "05_snap.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    return p.name


def save_summary_panel(d: Path, route_id: int, title: str, rec: Reconstruction) -> str | None:
    """4-panel side-by-side: original / contour / OCR / snap."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return None

    files = [d / "01_original.jpg", d / "02_contour.png", d / "03_ocr.png", d / "05_snap.png"]
    titles = ["original", "contour + skeleton", "OCR anchors", "projected vs snapped"]
    fig, axes = plt.subplots(1, 4, figsize=(20, 6), dpi=110)
    for ax, fpath, t in zip(axes, files, titles):
        if fpath.exists():
            img = cv2.imread(str(fpath))
            if img is None:
                ax.text(0.5, 0.5, "(load failed)", ha="center", va="center")
            elif fpath.suffix == ".png" and t == "projected vs snapped":
                ax.imshow(img[:, :, ::-1])
            else:
                ax.imshow(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        else:
            ax.text(0.5, 0.5, "(missing)", ha="center", va="center")
        ax.set_title(t, fontsize=11)
        ax.axis("off")
    fig.suptitle(
        f"#{route_id:05d}  {title[:80]}    confidence={rec.confidence:.2f}    "
        f"failure={rec.failure or '—'}",
        fontsize=12,
    )
    fig.tight_layout()
    p = d / "summary.png"
    fig.savefig(p, bbox_inches="tight")
    plt.close(fig)
    # Mirror to top-level diagnostics dir for easy browsing.
    out_dir_root = d.parent.parent  # phase4a_poc/
    mirror = out_dir_root / "diagnostics" / f"route_{route_id:05d}_summary.png"
    mirror.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(mirror), cv2.imread(str(p)))
    return p.name


def save_gpx(d: Path, rec: Reconstruction) -> str | None:
    if not rec.gpx_xml:
        return None
    p = d / "06_route.gpx"
    p.write_text(rec.gpx_xml)
    return p.name


# ---------- diagnostics serialisation -------------------------------------

def _safe(value: Any) -> Any:
    """Make any value JSON-serialisable. Drop large arrays."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {k: _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        # Truncate big sequences so the JSON stays readable.
        if len(value) > 100:
            return {"__truncated__": True, "len": len(value), "head": [_safe(v) for v in value[:5]]}
        return [_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return {"__ndarray__": True, "shape": list(value.shape), "dtype": str(value.dtype)}
    if dataclasses.is_dataclass(value):
        return _safe({f.name: getattr(value, f.name) for f in dataclasses.fields(value)})
    return repr(value)[:200]


def reconstruction_summary(route_id: int, title: str, rec: Reconstruction, elapsed_s: float) -> dict:
    contour = rec.contour
    ocr = rec.ocr
    cross = rec.crossref
    georef = rec.georectification
    fid = rec.fidelity
    matched = rec.matched

    summary = {
        "route_id": route_id,
        "title": title,
        "image_url": rec.image_url,
        "elapsed_s": round(elapsed_s, 2),
        "confidence": rec.confidence,
        "failure": rec.failure,
        "shipped": rec.gpx_xml is not None,
        "stages": {
            "contour": {
                "polyline_points": len(contour.polyline) if contour else 0,
                "length_px": getattr(contour, "length_px", None),
            } if contour else None,
            "ocr": {
                "n_street_candidates": len(ocr.street_candidates) if ocr else 0,
                "candidates": [
                    {"text": c.normalized, "conf": round(c.confidence, 3)}
                    for c in (ocr.street_candidates if ocr else [])
                ][:30],
                "n_fragments": len(ocr.fragment_boxes) if ocr and ocr.fragment_boxes else 0,
            } if ocr else None,
            "crossref": {
                "n_matches": {k: len(v) for k, v in (cross.matches or {}).items()} if cross else None,
                "cluster": _safe(cross.cluster) if cross else None,
            } if cross else None,
            "georef": {
                "n_anchors": getattr(georef, "n_anchors", None),
                "rmse_m": getattr(georef, "rmse_m", None),
                "max_residual_m": getattr(georef, "max_residual_m", None),
            } if georef else None,
            "mapmatch": {
                "n_snapped_points": len(matched.coords) if matched else 0,
                "unreachable_segments": getattr(matched, "unreachable_segments", None),
            } if matched else None,
            "fidelity": {
                "score": getattr(fid, "score", None),
                "frechet_m": getattr(fid, "frechet_m", None),
                "buffered_iou": getattr(fid, "buffered_iou", None),
            } if fid else None,
        },
        "diagnostics": _safe(rec.diagnostics),
    }
    return summary


# ---------- main loop -----------------------------------------------------

def run_one(
    route_id: int,
    title: str,
    image_url: str,
    out_dir: Path,
    client: NominatimStreetClient,
    *,
    min_confidence: float,
    download_graph: bool,
) -> dict:
    d = row_dir(out_dir, route_id)
    log_path = out_dir / "logs" / f"route_{route_id:05d}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_path, mode="w")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(file_handler)
    try:
        t0 = time.time()
        meta = GpxMetadata(name=title[:120], description=f"Phase 4a PoC reconstruction of strav.art route #{route_id}")
        try:
            rec = reconstruct(
                image_url,
                crossref_client=client,
                download_graph=download_graph,
                min_confidence=min_confidence,
                gpx_metadata=meta,
            )
        except Exception as exc:                                   # noqa: BLE001
            logger.exception("reconstruct() raised on route %d", route_id)
            rec = Reconstruction(image_url=image_url, failure=f"raised: {exc!r}")
        elapsed = time.time() - t0

        # Persist artifacts
        try:
            from stravart.ocr import fetch_image
            bgr = fetch_image(image_url)
            save_original(d, bgr)
            save_contour(d, bgr, rec)
            save_ocr_overlay(d, bgr, rec)
        except Exception:                                          # noqa: BLE001
            logger.exception("artifact save failure on route %d", route_id)
            bgr = None

        save_route_overlay(d, rec)
        save_gpx(d, rec)
        summary = reconstruction_summary(route_id, title, rec, elapsed)
        (d / "reconstruction.json").write_text(json.dumps(summary, indent=2, default=str))
        try:
            save_summary_panel(d, route_id, title, rec)
        except Exception:                                          # noqa: BLE001
            logger.exception("summary panel failure on route %d", route_id)

        return summary
    finally:
        root.removeHandler(file_handler)
        file_handler.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db",              required=True, type=Path)
    p.add_argument("--selection",       required=True, type=Path)
    p.add_argument("--out-dir",         required=True, type=Path)
    p.add_argument("--crossref-cache",  required=True, type=Path)
    p.add_argument("--min-confidence",  type=float, default=0.6)
    p.add_argument("--no-graph",        action="store_true",
                   help="Skip OSMnx Overpass call (faster; gets contour+OCR+georef only).")
    p.add_argument("--retry",           action="store_true",
                   help="Re-run rows that already have reconstruction.json.")
    p.add_argument("--only-id",         type=int, default=None,
                   help="Run a single id (for debugging).")
    args = p.parse_args()

    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    selection = json.loads(args.selection.read_text())
    routes = selection["routes"]
    if args.only_id is not None:
        routes = [r for r in routes if r["id"] == args.only_id]

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "diagnostics").mkdir(exist_ok=True)
    (args.out_dir / "gpx").mkdir(exist_ok=True)
    (args.out_dir / "logs").mkdir(exist_ok=True)

    client = NominatimStreetClient(args.crossref_cache)

    summaries: list[dict] = []
    for i, r in enumerate(routes, 1):
        rid = r["id"]
        d = row_dir(args.out_dir, rid)
        if is_complete(d) and not args.retry:
            logger.info("[%d/%d] skip route %d (already done)", i, len(routes), rid)
            summaries.append(json.loads((d / "reconstruction.json").read_text()))
            continue
        row = conn.execute(
            "SELECT id, title, image_url FROM routes WHERE id = ?", (rid,)
        ).fetchone()
        if row is None:
            logger.warning("route %d not in DB — skipping", rid)
            continue
        logger.info("[%d/%d] running route %d: %s", i, len(routes), rid, row["title"][:60])
        try:
            summary = run_one(
                rid, row["title"], row["image_url"], args.out_dir, client,
                min_confidence=args.min_confidence,
                download_graph=not args.no_graph,
            )
        except Exception as exc:                                  # noqa: BLE001
            logger.exception("hard failure on route %d", rid)
            summary = {
                "route_id": rid,
                "title": row["title"],
                "image_url": row["image_url"],
                "failure": f"hard: {exc!r}",
                "shipped": False,
                "confidence": 0.0,
                "stages": {},
                "diagnostics": {"traceback": traceback.format_exc()},
            }
            (args.out_dir / "per_image" / f"route_{rid:05d}").mkdir(parents=True, exist_ok=True)
            (args.out_dir / "per_image" / f"route_{rid:05d}" / "reconstruction.json").write_text(
                json.dumps(summary, indent=2, default=str)
            )
        summaries.append(summary)
        # Flush a running aggregate so we can monitor mid-run.
        (args.out_dir / "summary.json").write_text(json.dumps(summaries, indent=2, default=str))

    # Final aggregate
    n = len(summaries)
    n_shipped = sum(1 for s in summaries if s.get("shipped"))
    print()
    print(f"=== Phase 4a PoC results — {n} routes ===")
    print(f"  shipped (gpx written, conf >= {args.min_confidence}): {n_shipped}/{n} = {n_shipped/n:.0%}")
    print()
    print("Per-route outcomes:")
    for s in summaries:
        flag = "SHIP" if s.get("shipped") else "FAIL"
        conf = s.get("confidence") or 0.0
        title = (s.get("title") or "")[:55]
        print(f"  {flag}  conf={conf:.2f}  #{s['route_id']:>5}  {title}  ::  {s.get('failure') or ''}")


if __name__ == "__main__":
    main()
