"""Stream-download Google Quick, Draw! simplified ndjson and keep recognized entries.

Source: https://storage.googleapis.com/quickdraw_dataset/full/simplified/{category}.ndjson
License: CC BY 4.0 (Google Creative Lab).

We don't need the entire file (often 300-500 MB). Stream line-by-line, parse JSON,
keep only entries with recognized=true, stop after we have N kept entries.

Output format per category:
  data/{category}.recognized.ndjson  -- raw kept entries (one JSON per line)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

CATEGORIES = ["pig", "cat", "dog", "dragon", "duck", "elephant"]
BASE_URL = "https://storage.googleapis.com/quickdraw_dataset/full/simplified"
TARGET_RECOGNIZED = 3000   # per category — plenty to filter from
HARD_LINE_CAP = 50_000     # bail-out so we never read whole 500MB file


def stream_recognized(category: str, out_path: Path, target: int = TARGET_RECOGNIZED) -> int:
    url = f"{BASE_URL}/{category}.ndjson"
    print(f"  GET {url}")
    sess = requests.Session()
    with sess.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        kept = 0
        seen = 0
        with out_path.open("w") as out:
            # iter_lines decodes bytes->str on the fly
            for raw in r.iter_lines():
                if not raw:
                    continue
                line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                seen += 1
                if seen > HARD_LINE_CAP:
                    break
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not rec.get("recognized"):
                    continue
                out.write(line + "\n")
                kept += 1
                if kept >= target:
                    break
        return kept


def main() -> int:
    out_dir = Path(__file__).resolve().parent.parent / "data"
    out_dir.mkdir(parents=True, exist_ok=True)

    for cat in CATEGORIES:
        out_path = out_dir / f"{cat}.recognized.ndjson"
        if out_path.exists() and out_path.stat().st_size > 100_000:
            existing = sum(1 for _ in out_path.open())
            print(f"[{cat}] already downloaded: {existing} entries -> {out_path}")
            continue
        print(f"[{cat}] streaming...")
        t0 = time.time()
        n = stream_recognized(cat, out_path)
        print(f"[{cat}] kept {n} recognized entries in {time.time()-t0:.1f}s -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
