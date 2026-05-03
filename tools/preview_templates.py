"""Render a grid of Quick Draw templates as PNG so we can eyeball them."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt

from prototype.quickdraw_loader import load_top_templates


def render_grid(word: str, ndjson_path: Path, out_path: Path, n: int = 25):
    templates = load_top_templates(ndjson_path, n=n)
    cols = 5
    rows = (len(templates) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 2, rows * 2))
    axes = axes.flatten() if rows > 1 else [axes] if cols == 1 else list(axes)
    for ax, t in zip(axes, templates):
        xs = [p[0] for p in t.coords]
        ys = [p[1] for p in t.coords]
        ax.plot(xs, ys, 'k-', linewidth=1.2)
        ax.set_aspect('equal')
        ax.set_xlim(-0.6, 0.6)
        ax.set_ylim(-0.6, 0.6)
        ax.axis('off')
        ax.set_title(f'{t.n_strokes}s/{len(t.coords)}p', fontsize=7)
    for ax in axes[len(templates):]:
        ax.axis('off')
    fig.suptitle(f'Top {len(templates)} Quick Draw "{word}" templates', fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110, bbox_inches='tight')
    plt.close(fig)
    print(f'wrote {out_path}')


def main():
    base = Path('data/quickdraw')
    out_dir = Path('data/previews/templates')
    out_dir.mkdir(parents=True, exist_ok=True)
    for word in ['pig', 'cat', 'dog', 'dragon', 'duck']:
        path = base / f'{word}.ndjson'
        render_grid(word, path, out_dir / f'{word}_top25.png', n=25)


if __name__ == '__main__':
    main()
