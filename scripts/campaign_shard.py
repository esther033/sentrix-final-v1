"""Split one campaign schedule into per-PC shards for parallel collection.

The schedule (and its seed) stays the single source: a shard only lists pair
IDs of campaigns/<id>/schedule.json and pins that file by SHA-256, so every
PC runs pairs generated from the same seed and parameters.

* A pair (its fault and control run) belongs to exactly one shard.
* Assignment walks the schedule in order and deals pairs round-robin across
  the PCs, balancing cell (fault type, target), fault type, total and
  repetition (assign()). With 3 PCs and 3 repetitions every PC gets one
  repetition of every cell (23 pairs), with repetitions mixed.
* The shard name is the PC's hostname (the run records' environment_id);
  run-campaign.py --shard refuses a shard written for another host.

Output: <schedule dir>/shards/<name>.json (refuses to overwrite a differing file).
CLI: scripts/shard-campaign.py; run-campaign.py uses load_shard().
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def assign(pairs, names):
    """-> {name: [pair, ...]} in schedule order.

    Walks the schedule and deals pairs round-robin: from the PC after the last
    one used, take the first PC that (in this priority) has fewest pairs of the
    same cell (fault type, target), of the same fault type, in total, and of the
    same repetition. So a cell's repetitions land on different PCs while there
    are enough PCs, and PC never coincides with a cell or a repetition fold."""
    if len(names) != len(set(names)) or not names:
        raise ValueError("shard names must be non-empty and distinct")
    for n in names:
        if not NAME.match(n):
            raise ValueError(f"invalid shard name {n!r}")
    out = {n: [] for n in names}
    count = Counter()
    turn = 0
    for p in sorted(pairs, key=lambda p: p["schedule_index"]):
        keys = (("cell", p["fault_type"], p["target_id"]), ("type", p["fault_type"]), ("rep", p["repetition"]))
        order = [names[(turn + i) % len(names)] for i in range(len(names))]
        i = min(range(len(order)), key=lambda i: (count[order[i], keys[0]], count[order[i], keys[1]],
                                                   len(out[order[i]]), count[order[i], keys[2]], i))
        name = order[i]
        out[name].append(p)
        for k in keys:
            count[name, k] += 1
        turn = (turn + i + 1) % len(names)
    return out


def shard_doc(schedule, schedule_rel, schedule_sha, names, name, pairs):
    return {"schema_version": SCHEMA_VERSION, "campaign_id": schedule["campaign_id"], "seed": schedule["seed"],
            "draft": schedule.get("draft"), "schedule": schedule_rel, "schedule_sha256": schedule_sha,
            "shard": name, "shards": list(names),
            "method": "round-robin in schedule order, balancing cell, fault type, total, repetition",
            "summary": {"pairs": len(pairs),
                        "fault_type": dict(sorted(Counter(p["fault_type"] for p in pairs).items())),
                        "repetition": {str(k): v for k, v in sorted(Counter(p["repetition"] for p in pairs).items())},
                        "pair_order": dict(sorted(Counter(p["pair_order"] for p in pairs).items())),
                        "targets": len({(p["fault_type"], p["target_id"]) for p in pairs})},
            "pairs": [{"schedule_index": p["schedule_index"], "pair_id": p["pair_id"], "fault_type": p["fault_type"],
                       "target_id": p["target_id"], "repetition": p["repetition"],
                       "fault_run_id": p["fault_run_id"], "control_run_id": p["control_run_id"]} for p in pairs]}


def render(schedule_path, names):
    schedule_path = Path(schedule_path).resolve()
    raw = schedule_path.read_bytes()
    schedule = json.loads(raw)
    try:
        rel = str(schedule_path.relative_to(ROOT))
    except ValueError:
        rel = str(schedule_path)
    sha = hashlib.sha256(raw).hexdigest()
    shards = assign(schedule["pairs"], names)
    return {schedule_path.parent / "shards" / f"{n}.json":
            json.dumps(shard_doc(schedule, rel, sha, names, n, ps), indent=2) + "\n" for n, ps in shards.items()}


def load_shard(path, schedule_path, schedule):
    """Pair IDs of a shard after checking it belongs to this exact schedule."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    sha = hashlib.sha256(Path(schedule_path).read_bytes()).hexdigest()
    if doc.get("campaign_id") != schedule["campaign_id"]:
        raise ValueError(f"shard is for campaign {doc.get('campaign_id')}, schedule is {schedule['campaign_id']}")
    if doc.get("schedule_sha256") != sha:
        raise ValueError("shard was made from a different schedule.json (sha256 mismatch); regenerate the shards")
    known = {p["pair_id"] for p in schedule["pairs"]}
    ids = [p["pair_id"] for p in doc["pairs"]]
    missing = [i for i in ids if i not in known]
    if missing:
        raise ValueError(f"shard lists pairs not in the schedule: {missing[:5]}")
    return doc["shard"], set(ids)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schedule", default=str(ROOT / "campaigns/linux-v1/schedule.json"))
    ap.add_argument("--pc", action="append", dest="names", required=True,
                    help="PC hostname, repeatable, in a fixed order (e.g. --pc 206-40 --pc 206-41 --pc 206-42)")
    ap.add_argument("--dry-run", action="store_true", help="print the per-PC summary; write nothing")
    args = ap.parse_args(argv)
    files = render(args.schedule, args.names)
    for p, text in files.items():
        print(p.name, json.dumps(json.loads(text)["summary"]))
    if args.dry_run:
        return 0
    conflicts = [str(p) for p, text in files.items() if p.exists() and p.read_text(encoding="utf-8") != text]
    if conflicts:
        raise SystemExit("Refusing to overwrite differing shard files:\n  " + "\n  ".join(conflicts))
    for p, text in files.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    return 0
