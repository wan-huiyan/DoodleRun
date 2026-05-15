"""Render every approved elephant template as a single contact sheet so the
user can pick the most iconic / runnable shape by eye."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

from .templates_loader import load_animal_templates


def render(animal: str = "elephant", out: Path | None = None):
    tpls = load_animal_templates(animal)
    qd = sorted([t for t in tpls if t.source_kind == "quickdraw"], key=lambda t: t.vote_id)
    sa = sorted([t for t in tpls if t.source_kind == "stravart"], key=lambda t: t.vote_id)
    all_tpls = qd + sa
    n = len(all_tpls)
    cols = 6
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.4, rows * 2.2), dpi=120)
    axes = np.atleast_2d(axes).ravel()
    for ax, t in zip(axes, all_tpls):
        ax.plot(t.points[:, 0], t.points[:, 1], "-", color="#1f77b4", lw=1.4)
        ax.fill(t.points[:, 0], t.points[:, 1], color="#1f77b4", alpha=0.12)
        ax.set_aspect("equal")
        ax.set_xticks([]); ax.set_yticks([])
        # color-code title by source
        color = "#1f77b4" if t.source_kind == "quickdraw" else "#d6336c"
        ax.set_title(t.vote_id, fontsize=10, color=color)
    for ax in axes[n:]:
        ax.axis("off")
    fig.suptitle(
        f"All approved {animal} templates  "
        f"({len(qd)} QD in blue • {len(sa)} strav.art in pink) — "
        f"pick the elephant whose anatomy you want to trace",
        fontsize=13,
    )
    if out is None:
        out = Path("multi_template/previews") / f"_GALLERY_{animal}.png"
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out} ({n} templates)")


if __name__ == "__main__":
    render()
