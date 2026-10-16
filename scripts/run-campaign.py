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
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schedule", default=str(ROOT / "campaigns/linux-v1/schedule.json"))
    ap.add_argument("--k6-bin", default="k6")
    ap.add_argument("--settle-seconds", type=int, default=300)
    ap.add_argument("--max-pairs", type=int, help="stop after this many newly executed pairs")
    ap.add_argument("--only", action="append", help="run only these pair IDs (repeatable)")
    ap.add_argument("--allow-draft", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    schedule = json.loads(Path(args.schedule).read_text(encoding="utf-8"))
    campaign = schedule["campaign_id"]
    if schedule.get("draft") and not args.allow_draft and not args.dry_run:
        raise SystemExit("Schedule was generated from draft parameters; freeze fault-params.yaml and regenerate "
                         "(or pass --allow-draft for a rehearsal that is NOT part of the formal corpus).")
    state_dir = ROOT / "runs" / "_campaign" / campaign
    state_dir.mkdir(parents=True, exist_ok=True)
    decisions_path = state_dir / "decisions.yaml"
    decisions = yaml.safe_load(decisions_path.read_text(encoding="utf-8")) if decisions_path.exists() else {}
    excluded = set((decisions or {}).get("excluded_pairs", []))
    pairs = [p for p in schedule["pairs"] if not args.only or p["pair_id"] in args.only]
    executed = 0
    log = (state_dir / "queue.log").open("a", encoding="utf-8")

    def note(msg):
        line = f"{now()} {msg}"
        print(line, flush=True); log.write(line + "\n"); log.flush()

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
