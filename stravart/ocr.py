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

    fragments: list[tuple[str, float]]   # all OCR text, with confidence
    street_candidates: list[StreetCandidate]


def ocr_image(
    bgr: np.ndarray,
    *,
    languages: tuple[str, ...] = ("en",),
    inpaint: bool = True,
    min_confidence: float = 0.30,
) -> OcrResult:
    """Run the full OCR pipeline on a single image, return text + streets."""
    src = inpaint_route(bgr) if inpaint else bgr
    reader = get_reader(languages)
    raw = reader.readtext(src, detail=1, paragraph=False)
    fragments: list[tuple[str, float]] = []
    for entry in raw:
        # easyocr returns (bbox, text, conf) when detail=1, paragraph=False
        if len(entry) >= 3:
            _, text, conf = entry[0], entry[1], float(entry[2])
        elif len(entry) == 2:
            text, conf = entry[0], float(entry[1])
        else:
            continue
        text = (text or "").strip()
        if text:
            fragments.append((text, conf))
    streets = filter_street_candidates(fragments, min_confidence=min_confidence)
    return OcrResult(fragments=fragments, street_candidates=streets)


def ocr_url(url: str, **kw) -> OcrResult:
    """Convenience: fetch + ocr one URL."""
    return ocr_image(fetch_image(url), **kw)
