"""Read street-name labels from a strav.art map image.

Pipeline:
  1. Fetch the JPEG (or load from disk if a local path).
  2. Inpaint over the route stroke. The route is drawn in a saturated
     red/orange/yellow/blue/purple — we mask any *highly saturated* pixels
     and let OpenCV's TELEA inpainter rebuild the basemap underneath. This
     recovers most of the half-occluded street labels.
  3. Run EasyOCR on the cleaned image.
  4. Hand the (text, confidence) pairs to ``streets.filter_street_candidates``.

EasyOCR loads ~50 MB of model weights on first use; we keep a module-level
singleton so a batch run pays that cost once.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import httpx
import numpy as np

from .geocode import _make_ssl_context  # reuse the macOS keychain plumbing
from .streets import StreetCandidate, filter_street_candidates


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------- EasyOCR

_reader_lock = threading.Lock()
_reader = None  # type: ignore[var-annotated]


def get_reader(languages: tuple[str, ...] = ("en",)):
    """Return a process-wide EasyOCR Reader. Lazy + thread-safe."""
    global _reader
    if _reader is not None:
        return _reader
    with _reader_lock:
        if _reader is None:
            import easyocr  # heavy import; deferred
            logger.info("loading easyocr models (langs=%s) …", languages)
            _reader = easyocr.Reader(list(languages), gpu=False, verbose=False)
    return _reader


# ------------------------------------------------------------ image fetch

def fetch_image(url_or_path: str, *, timeout: float = 30.0) -> np.ndarray:
    """Return a BGR ndarray for the given URL *or* local path."""
    if url_or_path.startswith(("http://", "https://")):
        verify = _make_ssl_context()
        resp = httpx.get(url_or_path, timeout=timeout, verify=verify,
                         headers={"User-Agent": "DoodleRun/0.2 stravart-finder"})
        resp.raise_for_status()
        buf = np.frombuffer(resp.content, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError(f"cv2 could not decode image from {url_or_path!r}")
        return img
    path = Path(url_or_path)
    img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"could not read image at {path}")
    return img


# ----------------------------------------------------------- inpainting

def route_mask(bgr: np.ndarray, *, sat_min: int = 110, val_min: int = 70) -> np.ndarray:
    """Binary mask of "probably the drawn route" pixels.

    Strava-style runs use saturated colours that don't appear in the carto
    basemap (basemap greys, faded greens, faded blues — all desaturated). So
    we threshold in HSV: anything with high saturation **and** non-trivial
    brightness becomes mask. We then dilate by ~5px so the inpainter can pull
    clean source pixels from outside the bleed of anti-aliased edges.

    Tuned empirically against the strav.art Squarespace gallery — the dog
    image at ``data/raw.jsonl[0]`` is a representative test fixture.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    s = hsv[..., 1]
    v = hsv[..., 2]
    mask = ((s >= sat_min) & (v >= val_min)).astype(np.uint8) * 255
    # dilate to absorb anti-aliased halo around the line
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.dilate(mask, kernel, iterations=1)
    return mask


def inpaint_route(bgr: np.ndarray) -> np.ndarray:
    """Return a copy of ``bgr`` with the saturated route stroke removed."""
    mask = route_mask(bgr)
    if not mask.any():
        return bgr
    return cv2.inpaint(bgr, mask, inpaintRadius=5, flags=cv2.INPAINT_TELEA)


# -------------------------------------------------------------- OCR API

@dataclass
class OcrResult:
    """Output of one image's OCR pass."""

    fragments: list[tuple[str, float]]   # post-merge text fragments, with conf
    street_candidates: list[StreetCandidate]


def _bbox_metrics(bbox) -> tuple[float, float, float, float, float]:
    """Return (x_center, y_center, x_min, x_max, height) for an EasyOCR bbox.

    EasyOCR returns four polygon corners as ``[(x,y), …]`` floats.
    """
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return (
        (xs[0] + xs[1] + xs[2] + xs[3]) / 4.0,
        (ys[0] + ys[1] + ys[2] + ys[3]) / 4.0,
        min(xs),
        max(xs),
        max(ys) - min(ys),
    )


def _is_alpha_label(text: str) -> bool:
    """A street-label-shaped fragment has at least 2 alphabetic chars and is
    majority-alphabetic. Drops the digit-only noise EasyOCR finds in the
    Strava distance-marker callouts that the inpainter leaves intact.
    """
    text = text.strip()
    if not text:
        return False
    alpha = sum(1 for ch in text if ch.isalpha())
    if alpha < 2:
        return False
    return alpha >= 0.5 * sum(1 for ch in text if not ch.isspace())


def _merge_horizontal_neighbors(
    raw: list[tuple[list, str, float]],
    *,
    y_tol: float = 0.7,
    x_gap_max: float = 1.5,
) -> list[tuple[str, float]]:
    """Glue together OCR fragments that sit on the same line.

    EasyOCR routinely splits "Dixon Ave" or "Partridge Ave" into two adjacent
    detections; without merging, the suffix-shape filter throws them away.
    Heuristic:

      * drop fragments that aren't alphabetic — Strava distance-callouts
        ("3", "5") otherwise glom onto neighbouring street names and break
        suffix detection,
      * group remaining fragments by horizontal band (``|Δy| < y_tol·h``),
      * within a band, sort by x and merge into the predecessor when the
        inter-bbox gap is at most ``x_gap_max·h``.

    Returns ``[(text, mean_confidence), ...]`` for the merged fragments.
    """
    items = []
    for bbox, text, conf in raw:
        text = (text or "").strip()
        if not _is_alpha_label(text):
            continue
        xc, yc, x_min, x_max, h = _bbox_metrics(bbox)
        items.append({
            "text": text, "conf": float(conf),
            "xc": xc, "yc": yc,
            "x_min": x_min, "x_max": x_max,
            "h": max(h, 4.0),
        })

    items.sort(key=lambda it: (it["yc"], it["xc"]))

    merged: list[tuple[str, float]] = []
    while items:
        seed = items.pop(0)
        line = [seed]
        kept: list[dict] = []
        for it in items:
            ref_h = (line[-1]["h"] + it["h"]) / 2
            if abs(it["yc"] - line[-1]["yc"]) <= y_tol * ref_h:
                line.append(it)
            else:
                kept.append(it)
        items = kept

        # Within the horizontal band, merge in reading order if gaps are small.
        line.sort(key=lambda it: it["xc"])
        groups: list[list[dict]] = [[line[0]]]
        for it in line[1:]:
            prev = groups[-1][-1]
            ref_h = (prev["h"] + it["h"]) / 2
            gap = it["x_min"] - prev["x_max"]
            if gap <= x_gap_max * ref_h:
                groups[-1].append(it)
            else:
                groups.append([it])

        for g in groups:
            text = " ".join(it["text"] for it in g)
            avg_conf = sum(it["conf"] for it in g) / len(g)
            merged.append((text, avg_conf))

    return merged


def ocr_image(
    bgr: np.ndarray,
    *,
    languages: tuple[str, ...] = ("en",),
    inpaint: bool = True,
    min_confidence: float = 0.20,
    mag_ratio: float = 2.0,
) -> OcrResult:
    """Run the full OCR pipeline on a single image, return text + streets.

    ``mag_ratio>1`` makes EasyOCR upscale the input before detection — strav.art
    map labels are 8-12pt and benefit substantially. ``min_confidence`` defaults
    to 0.20 because, after spatial merging, even merged-fragment confidence
    averages tend to land in the 0.4-0.7 range.
    """
    src = inpaint_route(bgr) if inpaint else bgr
    reader = get_reader(languages)
    raw = reader.readtext(
        src, detail=1, paragraph=False,
        mag_ratio=mag_ratio,
        low_text=0.3,
        text_threshold=0.5,
    )
    fragments = _merge_horizontal_neighbors(raw)
    streets = filter_street_candidates(fragments, min_confidence=min_confidence)
    return OcrResult(fragments=fragments, street_candidates=streets)


def ocr_url(url: str, **kw) -> OcrResult:
    """Convenience: fetch + ocr one URL."""
    return ocr_image(fetch_image(url), **kw)
