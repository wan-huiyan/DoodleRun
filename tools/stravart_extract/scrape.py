"""Scrape gallery image URLs from strav.art category pages.

The site is a Squarespace gallery — image URLs are embedded directly in the
rendered HTML on the squarespace-cdn.com host. No JS execution needed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

import requests


def macos_keychain_bundle() -> str | None:
    """Export macOS keychain CA roots to a PEM (cf. prototype/osrm_client.py).

    On corporate networks doing TLS inspection the cert lives in keychain but
    not in certifi. Returns path to PEM, or None on non-darwin / failure.
    """
    if sys.platform != "darwin":
        return None
    cache = Path(tempfile.gettempdir()) / "doodlerun-ca.pem"
    if cache.exists() and cache.stat().st_size > 0:
        return str(cache)
    keychains = [
        "/Library/Keychains/System.keychain",
        "/System/Library/Keychains/SystemRootCertificates.keychain",
        os.path.expanduser("~/Library/Keychains/login.keychain-db"),
    ]
    with cache.open("wb") as out:
        for kc in keychains:
            if not os.path.exists(kc):
                continue
            res = subprocess.run(
                ["security", "find-certificate", "-a", "-p", kc],
                capture_output=True, check=False,
            )
            if res.returncode == 0 and res.stdout:
                out.write(res.stdout)
    return str(cache) if cache.stat().st_size > 0 else None

CDN_RE = re.compile(
    r"https://images\.squarespace-cdn\.com/content/v1/[A-Za-z0-9/_\-]+\.(?:jpg|jpeg|png|webp|JPG|JPEG|PNG|WEBP)"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}

CATEGORIES = {
    "cats-dogs": "https://www.strav.art/cats-dogs-copy",
    "elephants": "https://www.strav.art/elephants-copy",
    "dinosaurs": "https://www.strav.art/dinosaurs-copy",
    "birds": "https://www.strav.art/birds-copy",
    "mammals": "https://www.strav.art/mammals-copy",
    "reptiles": "https://www.strav.art/reptiles-copy",
    "sea-life": "https://www.strav.art/sea-life-copy",
    "misc": "https://www.strav.art/misc-copy",
}

# Drop favicon and obvious non-gallery assets.
FAVICON_RE = re.compile(r"favicon\.ico", re.I)


_CA_BUNDLE = macos_keychain_bundle()


def fetch_image_urls(page_url: str) -> list[str]:
    r = requests.get(page_url, headers=HEADERS, timeout=30, verify=_CA_BUNDLE or True)
    r.raise_for_status()
    raw = sorted(set(CDN_RE.findall(r.text)))
    return [u for u in raw if not FAVICON_RE.search(u)]


def filename_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    return Path(path).name


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("scratch/stravart_images"))
    ap.add_argument(
        "--category",
        action="append",
        choices=list(CATEGORIES.keys()),
        help="Limit to one or more categories (default: all).",
    )
    ap.add_argument("--manifest-only", action="store_true",
                    help="Only write the URL manifest, skip downloads.")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap downloads per category for testing.")
    args = ap.parse_args()

    cats = args.category or list(CATEGORIES.keys())
    args.out.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, list[dict]] = {}
    total_listed = 0
    for cat in cats:
        url = CATEGORIES[cat]
        try:
            urls = fetch_image_urls(url)
        except Exception as exc:
            print(f"[{cat}] FAILED to list: {exc}", file=sys.stderr)
            continue
        manifest[cat] = [{"url": u, "filename": filename_from_url(u)} for u in urls]
        total_listed += len(urls)
        print(f"[{cat}] listed {len(urls)} images")

    manifest_path = args.out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {manifest_path} ({total_listed} URLs across {len(manifest)} categories)")

    if args.manifest_only:
        return 0

    sess = requests.Session()
    sess.headers.update(HEADERS)
    if _CA_BUNDLE:
        sess.verify = _CA_BUNDLE
    for cat, items in manifest.items():
        cat_dir = args.out / cat
        cat_dir.mkdir(exist_ok=True)
        if args.limit:
            items = items[: args.limit]
        for i, item in enumerate(items):
            dest = cat_dir / item["filename"]
            if dest.exists() and dest.stat().st_size > 1000:
                continue
            try:
                resp = sess.get(item["url"], timeout=30)
                resp.raise_for_status()
                dest.write_bytes(resp.content)
            except Exception as exc:
                print(f"[{cat}] {item['filename']} FAILED: {exc}", file=sys.stderr)
                continue
            if i % 25 == 0:
                print(f"[{cat}] {i + 1}/{len(items)}")
            time.sleep(0.05)
        print(f"[{cat}] downloaded {len(items)} -> {cat_dir}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
