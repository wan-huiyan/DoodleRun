"""Build NUMBERED Quick Draw template grids for user voting.

Each cell shows: template number, stroke count, point count.
Output is one PNG per animal at high resolution so you can see details.
A vote sheet (markdown) lists the templates with checkboxes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

from prototype.quickdraw_loader import load_top_templates


def build_grid(word: str, ndjson_path: Path, out_png: Path, out_meta: Path,
               n: int = 30, cols: int = 5):
    templates = load_top_templates(ndjson_path, n=n, max_strokes=4)
    rows = (len(templates) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.6, rows * 2.6))
    axes = axes.flatten() if rows * cols > 1 else [axes]

    meta = []
    for i, (ax, t) in enumerate(zip(axes, templates), start=1):
        xs = [p[0] for p in t.coords]
        ys = [p[1] for p in t.coords]
        ax.plot(xs, ys, 'k-', linewidth=1.4)
        ax.set_aspect('equal')
        ax.set_xlim(-0.6, 0.6)
        ax.set_ylim(-0.6, 0.6)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_color('#cccccc')
            spine.set_linewidth(0.5)
        ax.set_title(
            f'#{i:02d}  ({t.n_strokes} strokes, {len(t.coords)} pts)',
            fontsize=9,
            color='#222222',
        )
        meta.append({
            'number': i,
            'word': word,
            'key_id': t.key_id,
            'n_strokes': t.n_strokes,
            'n_points': len(t.coords),
        })
    for ax in axes[len(templates):]:
        ax.axis('off')

    fig.suptitle(
        f'"{word}" — vote: keep (k), reject (x), maybe (?)',
        fontsize=14,
        color='#222222',
    )
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=130, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    out_meta.write_text(json.dumps(meta, indent=2))
    return meta


def build_vote_sheet(all_meta: dict, out_md: Path):
    lines = ['# Quick Draw template vote sheet', '']
    lines.append('Mark each `keep`/`reject`/`?` next to the template number.')
    lines.append('Reference image is in `data/previews/voting/<animal>_grid.png`.')
    lines.append('')
    for word, items in all_meta.items():
        lines.append(f'## {word}')
        lines.append('')
        lines.append('![grid](voting/' + f'{word}_grid.png)')
        lines.append('')
        lines.append('| # | strokes | pts | key_id | vote |')
        lines.append('|---|---|---|---|---|')
        for it in items:
            lines.append(
                f'| {it["number"]:02d} | {it["n_strokes"]} | {it["n_points"]} | '
                f'`{it["key_id"]}` | _ |'
            )
        lines.append('')
    out_md.write_text('\n'.join(lines))


def main():
    base = Path('data/quickdraw')
    out_dir = Path('data/previews/voting')
    out_dir.mkdir(parents=True, exist_ok=True)

    all_meta = {}
    for word in ['pig', 'cat', 'dog', 'dragon', 'duck']:
        path = base / f'{word}.ndjson'
        if not path.exists():
            print(f'skip {word}: missing {path}')
            continue
        png = out_dir / f'{word}_grid.png'
        meta = out_dir / f'{word}_meta.json'
        all_meta[word] = build_grid(word, path, png, meta, n=30)
        print(f'wrote {png} ({len(all_meta[word])} templates)')

    sheet = Path('data/previews') / 'VOTE_SHEET.md'
    build_vote_sheet(all_meta, sheet)
    print(f'wrote {sheet}')


if __name__ == '__main__':
    main()
