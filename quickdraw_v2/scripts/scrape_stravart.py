"""Scrape gallery image URLs from strav.art category pages and download.

We do NOT redistribute strav.art's images. We use them transiently for
shape-template extraction (transformative analysis) and store only the
extracted normalized-coordinate polylines. Raw images are kept in `data/strav_raw/`
which is gitignored.

Per-category mapping (strav.art has 22 categories; we focus on these 6):
  pig       -> /mammals-copy        (filter by filename containing 'pig'/'PIG')
  cat       -> /cats-dogs-copy      (filter by filename or just keep all and tag mixed)
  dog       -> /cats-dogs-copy
  dragon    -> /dinosaurs-copy      (dinosaur stand-in for "dino" in DoodleRun)
  duck      -> /birds-copy          (chicken stand-in)
  elephant  -> /elephants-copy
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import requests

GALLERY_FOR = {
    "pig":      "https://www.strav.art/mammals-copy",
    "cat":      "https://www.strav.art/cats-dogs-copy",
    "dog":      "https://www.strav.art/cats-dogs-copy",
    "dragon":   "https://www.strav.art/dinosaurs-copy",
    "duck":     "https://www.strav.art/birds-copy",
    "elephant": "https://www.strav.art/elephants-copy",
}

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 DoodleRun-research/1.0"
IMG_RE = re.compile(
    r'data-image="(https://images\.squarespace-cdn\.com/content/v1/[^"]+\.(?:jpg|jpeg|png))"',
    re.IGNORECASE,
)
FILENAME_HINTS = {
    "pig":      ("pig", "piglet", "porc"),
    "cat":      ("cat", "kit", "lion", "tiger", "wildcat"),
    "dog":      ("dog", "pup", "yorkie", "poodle", "sausage", "shep", "bulldog", "spaniel", "dachs"),
    "dragon":   ("dragon", "rex", "saur", "dino"),
    "duck":     ("duck", "swan", "goose", "chicken", "cock", "rooster", "hen", "bird"),
    "elephant": ("ele", "olifant", "dumbo", "trunk"),
}


def scrape_category(url: str) -> list[str]:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    html = r.text
    seen, out = set(), []
    for m in IMG_RE.finditer(html):
        u = m.group(1)
        if u in seen:
            continue
        # Skip site UI assets (logo, favicon, etc.)
        low = u.lower()
        if any(x in low for x in ("favicon", "logo", "stravartlogo")):
            continue
        seen.add(u)
        out.append(u)
    return out


def filter_by_animal(urls: list[str], animal: str) -> list[str]:
    """For galleries that bundle multiple animals (cats-dogs, mammals, birds),
    use the source filename to bias toward the right animal."""
    hints = FILENAME_HINTS.get(animal, ())
    if not hints:
        return urls
    keep = []
    for u in urls:
        fname = u.rsplit("/", 1)[-1].lower()
        if any(h in fname for h in hints):
            keep.append(u)
    # If the filter is too aggressive, fall back to all.
    if len(keep) < 8:
        return urls
    return keep


def download(url: str, out_path: Path, max_bytes: int = 2_000_000) -> bool:
    if out_path.exists() and out_path.stat().st_size > 1024:
        return True
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, stream=True) as r:
            r.raise_for_status()
            written = 0
            with out_path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
                    written += len(chunk)
                    if written > max_bytes:
                        break
        return True
    except Exception as e:
        print(f"   ! {url} -> {e}")
        try:
            out_path.unlink()
        except FileNotFoundError:
            pass
        return False


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    raw_dir = root / "data" / "strav_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for animal, url in GALLERY_FOR.items():
        print(f"[{animal}] scraping {url}")
        try:
            urls = scrape_category(url)
        except Exception as e:
            print(f"  ! scrape failed: {e}")
            continue
        print(f"  found {len(urls)} unique image URLs in gallery")
        urls = filter_by_animal(urls, animal)
        print(f"  after animal filter: {len(urls)}")
        # Cap downloads per animal to keep things reasonable.
        urls = urls[:80]
        cat_dir = raw_dir / animal
        cat_dir.mkdir(parents=True, exist_ok=True)
        ok = 0
        for i, u in enumerate(urls):
            # Build a cache filename from CDN path.
            tail = u.rsplit("/", 2)
            stamp = tail[-2] if len(tail) >= 2 else f"img{i}"
            fname = f"{i:03d}_{stamp}.jpg"
            if download(u, cat_dir / fname):
                ok += 1
            time.sleep(0.05)   # polite
        summary[animal] = {"requested": len(urls), "downloaded": ok}
        print(f"  downloaded {ok}/{len(urls)} -> {cat_dir}")
    out = root / "data" / "strav_scrape_summary.json"
    out.write_text(__import__("json").dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
