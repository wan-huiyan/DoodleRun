"""Playwright-based scraper for strav.art galleries.

Usage:
    asyncio.run(scrape_all(out_jsonl=Path("data/raw.jsonl")))

We hit each /home/{slug} page, auto-scroll to force lazy-load, then collect every
`<a><img></a>` tile. The image's `alt` attribute is the title; the anchor's
`href` is a CDN image URL (strav.art doesn't host per-item subpages).

Output is JSON-lines so the geocode/index steps can stream the file rather than
loading everything in memory — keeps the pipeline restartable.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from playwright.async_api import async_playwright, Page

from .synonyms import CATEGORIES


log = logging.getLogger("stravart.scrape")

BASE = "https://www.strav.art"
CATEGORY_URL = BASE + "/home/{slug}"

# JS that scrolls the page to the bottom and lets lazy images load.
_SCROLL_JS = """
async () => {
  const wait = (ms) => new Promise(r => setTimeout(r, ms));
  let last = -1;
  for (let i = 0; i < 60; i++) {
    window.scrollTo(0, document.body.scrollHeight);
    await wait(400);
    const h = document.body.scrollHeight;
    if (h === last) break;
    last = h;
  }
  await wait(800);
}
"""

# JS that pulls every gallery tile out of the DOM. We filter to anchors that
# wrap an img and point at the squarespace CDN — that's strav.art's tile pattern.
_EXTRACT_JS = """
() => {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a')) {
    const img = a.querySelector('img');
    if (!img) continue;
    const href = String(a.href || '');
    if (!href.includes('squarespace-cdn.com')) continue;
    if (seen.has(href)) continue;
    seen.add(href);
    const alt = (img.alt || '').trim();
    if (!alt || alt.toLowerCase() === 'strav.art') continue;
    out.push({
      title: alt,
      image_url: href,
      thumbnail_url: img.src || img.getAttribute('data-src') || ''
    });
  }
  return out;
}
"""


async def _scrape_category(page: Page, slug: str) -> list[dict]:
    url = CATEGORY_URL.format(slug=slug)
    log.info("scraping %s", url)
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    # Squarespace lazy-loads on scroll. Bumping past the fold once isn't enough.
    await page.evaluate(_SCROLL_JS)
    items = await page.evaluate(_EXTRACT_JS)
    log.info("  %d items on %s", len(items), slug)
    for it in items:
        it["category"] = slug
        it["stravart_url"] = url
        it["scraped_at"] = datetime.now(timezone.utc).isoformat()
    return items


async def scrape_all(
    out_jsonl: Path,
    categories: Sequence[str] = CATEGORIES,
    headless: bool = True,
    limit_per_category: int | None = None,
) -> int:
    """Scrape every category, append to `out_jsonl`. Returns total items."""
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        with out_jsonl.open("w", encoding="utf-8") as fh:
            for slug in categories:
                try:
                    items = await _scrape_category(page, slug)
                except Exception as e:  # noqa: BLE001
                    log.warning("category %s failed: %s", slug, e)
                    continue
                if limit_per_category:
                    items = items[:limit_per_category]
                for it in items:
                    fh.write(json.dumps(it, ensure_ascii=False) + "\n")
                total += len(items)
        await browser.close()
    log.info("scrape complete: %d items -> %s", total, out_jsonl)
    return total


def iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
