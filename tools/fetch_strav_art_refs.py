"""Download strav.art elephant reference images and build a study grid.

The user gave 19 elephant URLs from strav.art's gallery. These are
gold-standard examples of GPS art that uses real street networks.
We mirror them locally and assemble a contact-sheet PNG so the
agent (and user) can study them side-by-side.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

import matplotlib

matplotlib.use('Agg')
import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import requests

ELEPHANT_URLS = [
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1594135339655-B5TZTG61UGZ7POPHFCLW/olifant.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1591617196109-9XR4NVV99S6OG8KGVME3/SAele.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1591538790513-CASZD6TQNVRAQP9E6CCL/BrisEle.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1589115045749-GE5AJQFIX5OEH6QZ0IC5/ElephantCastle.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1733744157130-DYC8PJO6JV5WPO2FR6KA/ele-2024-12-09-at-11.34.47.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1730110485586-2ACAUFGPWC8Q1QQDGP1J/ele-2024-10-28-at-10.12.19.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1715161877832-PUC6EUA3KO6R7IX1RBVP/ele-2024-05-08-at-10.40.10.png',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1640624254808-QZR3GF4WJ88LM0EU5OUQ/ELE-2021-12-27-at-16.56.36.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1638985208764-S2U8W6UBGYDN8X3HF0ZN/Ele-2021-12-08-at-17.38.59.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1638015354377-UJFPQ6U2V7Z772FYY2V7/Ele-2021-11-27-at-12.11.08.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1632765089097-B374DE2HSZDMG2TVGI1V/ELE-2021-09-27-at-18.50.46.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1626706474411-NO8GOWX4X9AEG4IRYBB7/ELEDUTCH-2021-07-19-at-15.52.40.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1620990680486-QZVZASMUB5JLD8WDYRXH/EleFamily.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1624875682677-UVDBVU40WYP97P50QM70/Elephant-2021-06-28-at-11.20.24.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1611249383790-RGW2OFGZTZZWYE20ITJV/SingapoerEle.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1609766284622-TLB2HZ2K179YD0AZ1P9S/HollySpringsEle.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1605624651991-Z6U3EHR3I5KNB9EJOZ6S/CopenhagenElephant.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1605623984433-8HXST2QI08TO59NCLOD6/VilniusElephant.jpg',
    'https://images.squarespace-cdn.com/content/v1/5b4dbfd8da02bcfcf39bce03/1597248432427-UNTC5KD05YQIEUQ19QMS/SandygateEle.jpg',
]


def download(urls, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for url in urls:
        name = Path(urlparse(url).path).name
        # collapse hex-ish prefix that squarespace adds (e.g., "1594...-XYZ/olifant.jpg")
        safe = name.replace(' ', '_')
        path = out_dir / safe
        if path.exists() and path.stat().st_size > 5_000:
            paths.append(path)
            continue
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            path.write_bytes(r.content)
            paths.append(path)
            print(f'downloaded {path.name} ({len(r.content)//1024} KB)')
        except Exception as e:
            print(f'FAILED {url}: {e}')
    return paths


def make_grid(paths, out_png: Path, cols: int = 4, title: str | None = None):
    rows = (len(paths) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 4, rows * 3.6))
    axes = axes.flatten() if rows * cols > 1 else [axes]
    for i, (ax, path) in enumerate(zip(axes, paths), start=1):
        try:
            img = mpimg.imread(path)
            ax.imshow(img)
        except Exception as e:
            ax.text(0.5, 0.5, f'load failed:\n{e}', ha='center', va='center')
        ax.set_title(f'#{i:02d}  {path.stem[:40]}', fontsize=9)
        ax.axis('off')
    for ax in axes[len(paths):]:
        ax.axis('off')
    if title:
        fig.suptitle(title, fontsize=14)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=110, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    print(f'wrote {out_png}')


def main():
    out_dir = Path('data/previews/strav_art_refs')
    paths = download(ELEPHANT_URLS, out_dir / 'elephants')
    make_grid(
        paths,
        out_dir / 'elephant_reference_grid.png',
        cols=4,
        title='strav.art ELEPHANT gold standard — what good GPS art looks like',
    )


if __name__ == '__main__':
    main()
