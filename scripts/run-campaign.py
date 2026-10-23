"""Resumable sequential campaign queue over campaigns/<id>/schedule.json.

* Pairs run strictly in schedule order, one at a time.
* A pair whose audits/pair-<fault-id>/status.json says complete is skipped, so
  the queue can be restarted after a reboot or logout.
* A pair whose audit exists but did not complete stops the queue. The run IDs
  are never reused or overwritten; decide manually (retry under a new attempt
  ID, or mark it excluded in runs/_campaign/<id>/decisions.yaml).
* Between pairs: no unrecovered Chaos object, all pods Ready, then a settle
  period of normal observation (default 300 s).
* Create runs/_campaign/<id>/STOP to stop gracefully after the current pair.
* Draft profiles (fault-params.yaml status != frozen) are refused unless
  --allow-draft is given, which is only for calibration rehearsals.

Daily blocks on a shared, often rebooted machine (206-40):
* --fault-type limits the queue to some fault types (repeatable; schedule
  order is kept), e.g. tier 1 = cpu_saturation, network_delay, packet_loss.
* --stop-before HH:MM (local time) does not start a pair that would not end
  before the next HH:MM (settle + --pair-minutes, default 95).
* --min-free-gib (default 20) stops before a pair when runs/ or the k3s data
  directory has less free space.
* The between-pair gate also requires NTP synchronization (dual-boot RTC
  offset right after a boot).

Parallel collection on several PCs (linux/README.md "병렬 수집"):
* --shard campaigns/<id>/shards/<environment id>.json runs only that PC's pairs
  (scripts/shard-campaign.py). The shard must pin this exact schedule.json
  (SHA-256) and be named after this PC's environment ID (host_state.environment_id:
  SENTRIX_ENVIRONMENT_ID > linux/config/local.env > hostname), so a PC
  cannot run another PC's pairs by mistake.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import yaml

from campaign_shard import load_shard
from host_state import environment_id, ntp_synchronized

ROOT = Path(__file__).resolve().parents[1]
K3S_DATA = Path("/var/lib/rancher")
# k3s kubectl reads root-only /etc/rancher/k3s/k3s.yaml when KUBECONFIG is
# unset; children (kubectl, helper scripts) inherit this default.
os.environ.setdefault("KUBECONFIG", os.path.expanduser("~/.kube/config"))


def now():
    return datetime.now(timezone.utc).isoformat()


def kubectl_json(*args):
    p = subprocess.run(["kubectl", "--request-timeout=10s", *args, "-o", "json"], capture_output=True, text=True, timeout=20)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return json.loads(p.stdout)


def gate():
    """Return a list of problems that must block the next pair."""
    problems = []
    ntp = ntp_synchronized()
    if ntp != "yes":
        problems.append(f"NTP not synchronized ({ntp})")
    chaos = kubectl_json("get", "stresschaos,networkchaos,podchaos", "-n", "sentrix")
    for item in chaos["items"]:
        conds = item.get("status", {}).get("conditions", [])
        if not any(c.get("type") == "AllRecovered" and c.get("status") == "True" for c in conds):
            problems.append("unrecovered chaos object " + item["metadata"]["name"])
    for ns in ("sentrix",):
        pods = kubectl_json("get", "pods", "-n", ns)
        for p in pods["items"]:
            if p["status"].get("phase") == "Succeeded":
                continue
            ready = all(c.get("ready") for c in p["status"].get("containerStatuses", []))
            if p["status"].get("phase") != "Running" or not ready:
                problems.append(f"pod not ready {ns}/{p['metadata']['name']}")
    return problems


def pair_status(fault_id):
    path = ROOT / "audits" / ("pair-" + fault_id) / "status.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def select_pairs(pairs, only=None, fault_types=None, shard=None):
    """Filter by pair ID, fault type and shard pair IDs, keeping schedule order."""
    return [p for p in pairs
            if (not only or p["pair_id"] in only) and (not fault_types or p["fault_type"] in fault_types)
            and (shard is None or p["pair_id"] in shard)]


def parse_hhmm(value):
    try:
        hour, minute = (int(x) for x in value.split(":"))
        if not (0 <= hour < 24 and 0 <= minute < 60):
            raise ValueError
    except ValueError:
        raise argparse.ArgumentTypeError("expected HH:MM, got " + repr(value))
    return hour, minute


def next_deadline(hhmm, start):
    """First local HH:MM after `start` (a block started at 20:00 with 07:00 ends tomorrow)."""
    deadline = start.replace(hour=hhmm[0], minute=hhmm[1], second=0, microsecond=0)
    return deadline if deadline > start else deadline + timedelta(days=1)


def fits_before(current, deadline, settle_seconds, pair_minutes):
    return deadline is None or current + timedelta(seconds=settle_seconds, minutes=pair_minutes) <= deadline


def low_disk(paths, min_free_gib, usage=shutil.disk_usage):
    """Return 'path: N GiB free' for every existing path below the threshold."""
    low = []
    for path in paths:
        if Path(path).exists():
            free = usage(path).free / 2**30
            if free < min_free_gib:
                low.append(f"{path}: {free:.1f} GiB free < {min_free_gib} GiB")
    return low


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schedule", default=str(ROOT / "campaigns/linux-v1/schedule.json"))
    ap.add_argument("--k6-bin", default="k6")
    ap.add_argument("--settle-seconds", type=int, default=300)
    ap.add_argument("--max-pairs", type=int, help="stop after this many newly executed pairs")
    ap.add_argument("--only", action="append", help="run only these pair IDs (repeatable)")
    ap.add_argument("--fault-type", action="append", dest="fault_types",
                    help="run only pairs of this fault type (repeatable, schedule order kept)")
    ap.add_argument("--stop-before", type=parse_hhmm, metavar="HH:MM",
                    help="local time; do not start a pair that would not finish before it")
    ap.add_argument("--pair-minutes", type=int, default=95, help="expected pair duration for --stop-before")
    ap.add_argument("--min-free-gib", type=float, default=20,
                    help="stop before a pair when runs/ or the k3s data dir has less free space")
    ap.add_argument("--shard", help="campaigns/<id>/shards/<environment id>.json: run only this PC's pairs")
    ap.add_argument("--allow-draft", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    schedule = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    campaign = schedule["campaign_id"]
    if schedule.get("draft") and not args.allow_draft and not args.dry_run:
        raise SystemExit("Schedule was generated from draft parameters; freeze fault-params.yaml and regenerate "
                         "(or pass --allow-draft for a rehearsal that is NOT part of the formal corpus).")
    try:
        env_id = environment_id()
    except ValueError as e:
        raise SystemExit(f"run-campaign: {e}")
    shard_name, shard_ids = None, None
    if args.shard:
        try:
            shard_name, shard_ids = load_shard(args.shard, args.schedule, schedule)
        except ValueError as e:
            raise SystemExit(f"--shard {args.shard}: {e}")
        if shard_name != env_id and not args.dry_run:
            raise SystemExit(f"--shard {args.shard} is for PC {shard_name!r}, this PC's environment id is {env_id!r} "
                             "(SENTRIX_ENVIRONMENT_ID / linux/config/local.env / hostname)")
    state_dir = ROOT / "runs" / "_campaign" / campaign
    state_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = state_dir / "decisions.yaml"
    decisions = yaml.safe_load(decisions_path.read_text(encoding="utf-8")) if decisions_path.exists() else {}
    excluded = set((decisions or {}).get("excluded_pairs", []))
    known_types = {p["fault_type"] for p in schedule["pairs"]}
    unknown = sorted(set(args.fault_types or []) - known_types)
    if unknown:
        raise SystemExit(f"unknown --fault-type {unknown}; schedule has {sorted(known_types)}")
    pairs = select_pairs(schedule["pairs"], args.only, args.fault_types, shard_ids)
    deadline = next_deadline(args.stop_before, datetime.now().astimezone()) if args.stop_before else None
    with (state_dir / "queue.log").open("a", encoding="utf-8") as log:
        def note(msg):
            line = f"{now()} {msg}"
            print(line, flush=True); log.write(line + "\n"); log.flush()

        if args.fault_types or deadline or shard_name:
            note(f"block: fault types={args.fault_types or 'all'} stop-before={deadline.isoformat() if deadline else None} "
                 f"shard={shard_name} host={env_id} pairs selected={len(pairs)}")
        return run_queue(args, pairs, excluded, state_dir, deadline, note)


def run_queue(args, pairs, excluded, state_dir, deadline, note):
    executed = 0
    for p in pairs:
        status = pair_status(p["fault_run_id"])
        if p["pair_id"] in excluded:
            note(f"skip excluded {p['pair_id']}"); continue
        if status and status.get("complete"):
            continue
        if status:
            note(f"STOP: {p['pair_id']} has an incomplete audit (phase={status.get('phase')}); decide manually")
            return 2
        if args.max_pairs is not None and executed >= args.max_pairs:
            note("max-pairs reached"); return 0
        if (state_dir / "STOP").exists():
            note("STOP file present; exiting before " + p["pair_id"]); return 0
        cmd = [sys.executable, "-B", str(ROOT / "scripts/run-matched-pair.py"),
               "--control-id", p["control_run_id"], "--fault-id", p["fault_run_id"],
               "--control-profile", p["control_profile"], "--fault-profile", p["fault_profile"],
               "--pair-order", p["pair_order"], "--k6-bin", args.k6_bin]
        if args.dry_run:
            print(json.dumps({"schedule_index": p["schedule_index"], "pair_id": p["pair_id"], "argv": cmd}))
            executed += 1
            continue
        if not fits_before(datetime.now().astimezone(), deadline, args.settle_seconds, args.pair_minutes):
            note(f"stop-before {deadline.isoformat()}: {p['pair_id']} (settle {args.settle_seconds}s + "
                 f"{args.pair_minutes} min) would not finish in time; exiting"); return 0
        low = low_disk([ROOT / "runs", K3S_DATA], args.min_free_gib)
        if low:
            note("STOP: low disk: " + "; ".join(low)); return 4
        problems = gate()
        if problems:
            note("STOP: pre-pair gate failed: " + "; ".join(problems)); return 3
        note(f"settle {args.settle_seconds}s before {p['pair_id']}")
        time.sleep(args.settle_seconds)
        problems = gate()
        if problems:
            note("STOP: post-settle gate failed: " + "; ".join(problems)); return 3
        note(f"start #{p['schedule_index']} {p['pair_id']} order={p['pair_order']} onset={p['onset_offset_seconds']}")
        rc = subprocess.run(cmd, cwd=ROOT).returncode
        executed += 1
        note(f"end {p['pair_id']} rc={rc}")
        if rc:
            note("STOP: pair failed; inspect audits/pair-" + p["fault_run_id"]); return 1
    note("queue finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
