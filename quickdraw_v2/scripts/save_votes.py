"""Save user's final template votes for all animals.

For each animal, builds approved/rejected lists keyed by stable source
identifiers (key_id for Quick Draw, source filename for strav.art) so the
votes survive re-extraction and re-ranking.

User votes are over the top-30 ranked candidates. For Quick Draw, the user
gives an explicit KEEP list; everything else in Q01..Q30 is rejected. For
strav.art, the user gives a REMOVE list; everything else in S01..S<min(30,N)>
is approved.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ANIMAL_PREFIX = {
    "elephant": "ELE",
    "cat": "CAT",
    "dog": "DOG",
    "dragon": "DRA",
    "duck": "DUC",
    "pig": "PIG",
}

VOTES = {
    "elephant": {
        "qd_keep": [1, 7, 8, 15, 18, 19, 20, 23, 24, 29],
        "sa_remove": [2, 6, 9, 20],
    },
    "cat": {
        "qd_keep": [3, 5, 11, 22, 25],
        "sa_remove": [3, 15, 29, 30],
    },
    "dog": {
        "qd_keep": [14, 26],
        "sa_remove": [13, 17, 22],
    },
    "dragon": {
        "qd_keep": [20, 21, 22, 30],
        "sa_remove": [2],
    },
    "duck": {
        "qd_keep": [1, 2, 3, 5, 6, 8, 11, 12, 13, 14, 15, 16, 18, 21, 22, 23, 24, 25, 26, 27, 30],
        "sa_remove": [2, 15, 30],
    },
    "pig": {
        "qd_keep": [1, 2, 3, 6, 11, 12, 15, 18, 19, 20, 22, 23, 27, 28, 29],
        "sa_remove": [9, 10],
    },
}

VOTE_RANGE = 30  # user voted over Q01..Q30 / S01..S30


def load_quickdraw_by_rank(animal: str) -> dict[int, dict]:
    d = ROOT / "sketches" / animal
    by_rank: dict[int, dict] = {}
    for jp in d.glob("*.json"):
        if jp.name == "extract_summary.json":
            continue
        data = json.loads(jp.read_text())
        by_rank[int(data["rank"])] = data
    return by_rank


def load_stravart_by_rank(animal: str) -> dict[int, dict]:
    d = ROOT / "templates_strav" / animal
    by_rank: dict[int, dict] = {}
    for jp in d.glob("*.json"):
        if jp.name == "extract_summary.json":
            continue
        data = json.loads(jp.read_text())
        by_rank[int(data["rank"])] = data
    return by_rank


def build_animal_votes(animal: str) -> dict:
    prefix = ANIMAL_PREFIX[animal]
    spec = VOTES[animal]
    qd_keep = set(spec["qd_keep"])
    sa_remove = set(spec["sa_remove"])

    qd_by_rank = load_quickdraw_by_rank(animal)
    sa_by_rank = load_stravart_by_rank(animal)

    qd_max = min(VOTE_RANGE, len(qd_by_rank))
    sa_max = min(VOTE_RANGE, len(sa_by_rank))

    approved_qd = []
    rejected_qd = []
    for n in range(1, qd_max + 1):
        rank = n - 1
        d = qd_by_rank.get(rank)
        if d is None:
            continue
        entry = {
            "vote_id": f"{prefix}-Q{n:02d}",
            "rank_when_voted": rank,
            "key_id": str(d["key_id"]),
        }
        (approved_qd if n in qd_keep else rejected_qd).append(entry)

    approved_sa = []
    rejected_sa = []
    for n in range(1, sa_max + 1):
        rank = n - 1
        d = sa_by_rank.get(rank)
        if d is None:
            continue
        entry = {
            "vote_id": f"{prefix}-S{n:02d}",
            "rank_when_voted": rank,
            "source": d["source"],
        }
        (rejected_sa if n in sa_remove else approved_sa).append(entry)

    return {
        "animal": animal,
        "vote_range": VOTE_RANGE,
        "n_quickdraw_voted": qd_max,
        "n_stravart_voted": sa_max,
        "approved_quickdraw": approved_qd,
        "rejected_quickdraw": rejected_qd,
        "approved_stravart": approved_sa,
        "rejected_stravart": rejected_sa,
    }


def main():
    out_dir = ROOT / "votes"
    out_dir.mkdir(parents=True, exist_ok=True)
    for animal in VOTES:
        votes = build_animal_votes(animal)
        out = out_dir / f"{animal}_approved.json"
        out.write_text(json.dumps(votes, indent=2) + "\n")
        print(
            f"{animal:9s}  QD approved={len(votes['approved_quickdraw']):2d} "
            f"rejected={len(votes['rejected_quickdraw']):2d}  "
            f"SA approved={len(votes['approved_stravart']):2d} "
            f"rejected={len(votes['rejected_stravart']):2d}  -> {out.name}"
        )


if __name__ == "__main__":
    main()
