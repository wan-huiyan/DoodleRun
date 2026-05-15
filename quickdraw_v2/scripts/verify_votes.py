"""Verify that approved/rejected vote IDs still resolve to existing templates
after re-extraction. Source identifiers (key_id for Quick Draw, source
filename for strav.art) are stable across re-extraction runs even when ranks
shift around."""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def index_quickdraw(cat: str) -> dict[str, dict]:
    out = {}
    d = ROOT / "sketches" / cat
    if not d.exists():
        return out
    for jp in d.glob("*.json"):
        try:
            data = json.loads(jp.read_text())
        except Exception:
            continue
        out[str(data.get("key_id"))] = data
    return out


def index_stravart(cat: str) -> dict[str, dict]:
    out = {}
    d = ROOT / "templates_strav" / cat
    if not d.exists():
        return out
    for jp in d.glob("*.json"):
        if jp.name == "extract_summary.json":
            continue
        try:
            data = json.loads(jp.read_text())
        except Exception:
            continue
        out[data.get("source", "?")] = data
    return out


def main():
    votes_path = ROOT / "votes" / "elephant_approved.json"
    if not votes_path.exists():
        print("no votes file"); return
    votes = json.loads(votes_path.read_text())
    qd = index_quickdraw("elephant")
    sa = index_stravart("elephant")
    print(f"sketches/elephant: {len(qd)} templates")
    print(f"templates_strav/elephant: {len(sa)} templates")
    print()
    print("Approved Quick Draw (key_id resolution):")
    for v in votes.get("approved_quickdraw", []):
        kid = v.get("key_id")
        d = qd.get(kid)
        if d is None:
            print(f"  MISSING {v['vote_id']}  key_id={kid}")
        else:
            print(f"  ok {v['vote_id']:8s}  key_id={kid}  new_rank={d.get('rank'):3d}")
    print()
    print("Approved strav.art (source resolution):")
    n_missing = 0
    for v in votes.get("approved_stravart", []):
        src = v.get("source")
        d = sa.get(src)
        if d is None:
            print(f"  MISSING {v['vote_id']}  source={src}")
            n_missing += 1
        else:
            print(f"  ok {v['vote_id']:8s}  new_rank={d.get('rank'):3d}  source={src[:32]}...")
    print()
    if n_missing:
        print(f"WARNING: {n_missing} approved strav.art vote(s) cannot be resolved")
    print("Rejected stravart (still findable?):")
    for v in votes.get("rejected_stravart", []) + votes.get("soft_rejected_stravart", []):
        src = v.get("source")
        d = sa.get(src)
        present = "present" if d else "GONE"
        print(f"  {v['vote_id']}  {present}  source={src[:32]}...")


if __name__ == "__main__":
    main()
