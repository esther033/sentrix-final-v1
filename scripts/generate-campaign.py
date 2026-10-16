"""Generate the linux-v1 matched-pair profiles and a reproducible schedule.

Inputs:  campaigns/linux-v1/campaign-plan.yaml (matrix, protocol, targets)
         campaigns/linux-v1/fault-params.yaml  (frozen or draft parameters, C)
Outputs: <profile-root>/<run-id>.json for every fault and control run
         campaigns/linux-v1/schedule.json and schedule.csv

Every random choice comes from one seeded random.Random, so the same seed and
inputs reproduce byte-identical outputs. Balancing rules (execution-plan.yaml):
  * pair order: each (fault_type, target) cell has 3 repetitions, so its
    control_then_fault / fault_then_control split is 2/1 or 1/2 (difference 1);
    over 23 cells the campaign total is 34/35. Cells with the 2-majority are
    spread across fault types round-robin.
  * onset: the 3 repetitions of a cell get 3 distinct candidates, choosing the
    least-used candidates campaign-wide (ties broken by the seed).
  * execution order: shuffled; rejected unless every third of the schedule
    contains each repetition at least 5 times and no two consecutive pairs share
    a cell, so repetition (fold) does not coincide with collection day.
The workload seed is shared by the fault and control of a pair and differs
between pairs. Outcomes are never used.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import random

import yaml

ROOT = Path(__file__).resolve().parents[1]
GENERATOR_VERSION = 1
SHORT = {"cpu_saturation": "cpu", "pod_failure": "pod", "network_delay": "delay",
         "packet_loss": "loss", "traffic_surge": "surge"}
ORDERS = ("control_then_fault", "fault_then_control")
MATCH_KEYS = ("target_rps", "time_unit", "duration", "warmup_seconds", "baseline_seconds", "fault_seconds",
              "recovery_seconds", "cooldown_seconds", "pre_allocated_vus", "max_vus", "stage_timeout")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tps(value):
    """k6 needs an integer rate per 1s or per 1m; snap to 1/60 tx/s."""
    snapped = round(value * 60) / 60
    if snapped <= 0:
        raise ValueError("rate must be positive")
    return int(snapped) if float(snapped).is_integer() else round(snapped, 6)


def cells(plan):
    out = []
    edges = {e["id"]: e for e in plan["edge_targets"]}
    for row in plan["matrix"]:
        if row["target_axis"] == "service_targets":
            targets = [{"target_id": s, "target_kind": "service_node", "service": s} for s in plan["service_targets"]]
        elif row["target_axis"] == "edge_targets":
            targets = [{"target_id": e, "target_kind": "dependency_edge", "edge": edges[e]} for e in edges]
        elif row["target_axis"] == "calibrated_load_levels":
            targets = [{"target_id": lv["id"], "target_kind": "workload_entrypoint", "level": lv["id"]} for lv in row["levels"]]
        else:
            raise ValueError("unknown target axis " + row["target_axis"])
        if len(targets) != row["targets"]:
            raise ValueError(f"{row['fault_type']}: plan says {row['targets']} targets, found {len(targets)}")
        for t in targets:
            out.append({"fault_type": row["fault_type"], **t})
    return out


def assign_pair_orders(rng, cell_list, reps):
    by_type = {}
    for c in cell_list:
        by_type.setdefault(c["fault_type"], []).append(c)
    for group in by_type.values():
        rng.shuffle(group)
    round_robin, types = [], sorted(by_type)
    while any(by_type.values()):
        for t in types:
            if by_type[t]:
                round_robin.append(by_type[t].pop(0))
    total_pairs = len(cell_list) * reps
    low = total_pairs // 2  # 34 of 69
    # cells with two control-first runs: base 1 per cell, so need low or low+1 total
    k = rng.choice([low - len(cell_list), low + 1 - len(cell_list)])
    majority_cf = {id(c) for c in round_robin[:k]}
    orders = {}
    for c in cell_list:
        cf = 2 if id(c) in majority_cf else 1
        seq = ["control_then_fault"] * cf + ["fault_then_control"] * (reps - cf)
        rng.shuffle(seq)
        orders[(c["fault_type"], c["target_id"])] = seq
    return orders


def assign_onsets(rng, cell_list, reps, candidates):
    used = {c: 0 for c in candidates}
    onsets = {}
    order = list(cell_list)
    rng.shuffle(order)
    for c in order:
        pool = list(candidates)
        rng.shuffle(pool)
        pool.sort(key=lambda x: used[x])
        chosen = pool[:reps]
        rng.shuffle(chosen)
        for x in chosen:
            used[x] += 1
        onsets[(c["fault_type"], c["target_id"])] = chosen
    return onsets


def acceptable_order(pairs, reps):
    n = len(pairs)
    thirds = [pairs[i * n // 3:(i + 1) * n // 3] for i in range(3)]
    for part in thirds:
        for r in range(1, reps + 1):
            if sum(p["repetition"] == r for p in part) < 5:
                return False
    return all(a["cell"] != b["cell"] for a, b in zip(pairs, pairs[1:]))


def build(plan, params, seed, capacity_override=None, campaign_id=None):
    if campaign_id:
        plan = {**plan, "campaign_id": campaign_id}
    proto = plan["protocol"]
    reps = {row["repetitions"] for row in plan["matrix"]}
    if len(reps) != 1:
        raise ValueError("generator assumes one repetition count for all cells")
    reps = reps.pop()
    capacity = capacity_override if capacity_override is not None else params.get("capacity_tps")
    if capacity is None:
        raise ValueError("capacity_tps is not measured; pass --capacity-tps for a draft dry-run")
    draft = params.get("status") != "frozen" or capacity_override is not None
    fr = params["load_fractions"]
    base_rate = tps(fr["baseline"] * capacity)
    rng = random.Random(seed)
    cell_list = cells(plan)
    orders = assign_pair_orders(rng, cell_list, reps)
    onsets = assign_onsets(rng, cell_list, reps, proto["intervention_onset_candidates_seconds"])
    pairs = []
    for c in cell_list:
        key = (c["fault_type"], c["target_id"])
        for r in range(1, reps + 1):
            pair_id = f"{plan['campaign_id']}-{SHORT[c['fault_type']]}-{c['target_id']}-r{r:02d}"
            pairs.append({"cell": key, "cell_info": c, "repetition": r, "pair_id": pair_id,
                          "pair_order": orders[key][r - 1], "onset": onsets[key][r - 1]})
    for attempt in range(10000):
        rng.shuffle(pairs)
        if acceptable_order(pairs, reps):
            break
    else:
        raise RuntimeError("could not find an acceptable execution order")
    w = params["workload"]
    profiles, schedule = {}, []
    for index, p in enumerate(pairs, 1):
        c = p["cell_info"]
        onset = p["onset"]
        baseline = onset - proto["warmup_seconds"]
        recovery = proto["duration_seconds"] - onset - proto["intervention_seconds"] - proto["cooldown_seconds"]
        if baseline < proto["minimum_baseline_seconds"] or recovery < proto["minimum_recovery_seconds"]:
            raise ValueError(f"onset {onset} violates minimum baseline/recovery")
        workload_seed = rng.randrange(1, 2**31 - 1)
        fault_id = p["pair_id"]
        control_id = p["pair_id"].replace(plan["campaign_id"] + "-", plan["campaign_id"] + "-control-", 1)
        common = {
            "campaign_id": plan["campaign_id"], "pair_id": p["pair_id"], "repetition": p["repetition"],
            "cv_group": f"repetition-{p['repetition']}", "schedule_index": index,
            "onset_offset_seconds": onset, "pair_order": p["pair_order"], "workload_seed": workload_seed,
            "calibration_status": "draft" if draft else "frozen",
            "target_rps": base_rate, "time_unit": w["time_unit"], "duration": f"{proto['duration_seconds'] // 60}m",
            "warmup_seconds": proto["warmup_seconds"], "baseline_seconds": baseline,
            "fault_seconds": proto["intervention_seconds"], "recovery_seconds": recovery,
            "cooldown_seconds": proto["cooldown_seconds"],
            "traffic_phase_rps": {ph: base_rate for ph in ("warmup", "baseline", "fault", "recovery", "cooldown")},
            "pre_allocated_vus": w["pre_allocated_vus"], "max_vus": w["max_vus"],
            "stage_timeout": w["stage_timeout"], "trace_workers": w["trace_workers"],
        }
        if proto["duration_seconds"] % 60:
            raise ValueError("duration must be whole minutes")
        fp = params["faults"][c["fault_type"]]
        fault = {"type": c["fault_type"], "target_kind": c["target_kind"], "template": fp["template"],
                 "params": dict(fp["params"])}
        fault_profile = {"profile_name": fault_id, "run_role": "fault", **common}
        if c["target_kind"] == "service_node":
            fault.update(root_cause_service=c["service"], scope_kind="service_instance")
        elif c["target_kind"] == "dependency_edge":
            e = c["edge"]
            fault.update(root_cause_service=e["source"], edge_id=e["id"], source_service=e["source"],
                         destination_service=e["destination"], scope_kind="dependency_edge")
        else:
            level_rate = tps(fr["surge_levels"][c["level"]] * capacity)
            fault.update(root_cause_service="frontend", load_level=c["level"], scope_kind="workload_entrypoint")
            fault_profile["control_phase_rps"] = dict(common["traffic_phase_rps"])
            fault_profile["traffic_phase_rps"] = {**common["traffic_phase_rps"], "fault": level_rate}
            fault_profile["max_vus"] = max(w["max_vus"], int(level_rate * 40) + 10)
        fault_profile["fault"] = fault
        control_profile = {"profile_name": control_id, "run_role": "control", **common,
                           "max_vus": fault_profile["max_vus"],
                           "sham": {"fault_type": c["fault_type"], "target_id": c["target_id"]}}
        profiles[fault_id] = fault_profile
        profiles[control_id] = control_profile
        schedule.append({"schedule_index": index, "pair_id": p["pair_id"], "fault_type": c["fault_type"],
                         "target_kind": c["target_kind"], "target_id": c["target_id"],
                         "repetition": p["repetition"], "pair_order": p["pair_order"],
                         "onset_offset_seconds": onset, "workload_seed": workload_seed,
                         "fault_run_id": fault_id, "control_run_id": control_id})
    return profiles, schedule, {"draft": draft, "capacity_tps": capacity, "baseline_tps": base_rate}


def render(plan_path, params_path, seed, profile_root, capacity_override=None, campaign_id=None):
    plan = yaml.safe_load(Path(plan_path).read_text(encoding="utf-8"))
    params = yaml.safe_load(Path(params_path).read_text(encoding="utf-8"))
    profiles, schedule, meta = build(plan, params, seed, capacity_override, campaign_id)
    if campaign_id:
        plan = {**plan, "campaign_id": campaign_id}
    files = {}
    for run_id, prof in profiles.items():
        files[f"{profile_root}/{run_id}.json"] = json.dumps(prof, indent=2, sort_keys=False) + "\n"
    for row in schedule:
        row["fault_profile"] = f"{profile_root}/{row['fault_run_id']}.json"
        row["control_profile"] = f"{profile_root}/{row['control_run_id']}.json"
    doc = {"schema_version": 1, "campaign_id": plan["campaign_id"], "generator_version": GENERATOR_VERSION,
           "seed": seed, **meta,
           "inputs_sha256": {"campaign_plan": sha256(plan_path), "fault_params": sha256(params_path)},
           "pairs": schedule}
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(schedule[0]), lineterminator="\n")
    writer.writeheader(); writer.writerows(schedule)
    return files, json.dumps(doc, indent=2) + "\n", buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--plan", default=str(ROOT / "campaigns/linux-v1/campaign-plan.yaml"))
    ap.add_argument("--params", default=str(ROOT / "campaigns/linux-v1/fault-params.yaml"))
    ap.add_argument("--profile-root", default="workload/profiles/linux-v1")
    ap.add_argument("--schedule-dir", default=str(ROOT / "campaigns/linux-v1"))
    ap.add_argument("--capacity-tps", type=float, help="draft-only override while C is not yet measured")
    ap.add_argument("--campaign-id", help="override, e.g. calib-linux-v1 for calibration/trial pairs so their IDs never collide with the formal campaign")
    ap.add_argument("--dry-run", action="store_true", help="validate and print a summary; write nothing")
    args = ap.parse_args()
    if args.campaign_id:
        if args.profile_root == "workload/profiles/linux-v1":
            args.profile_root = "workload/profiles/" + args.campaign_id
        if args.schedule_dir == str(ROOT / "campaigns/linux-v1"):
            args.schedule_dir = str(ROOT / "campaigns" / args.campaign_id)
    files, schedule_json, schedule_csv = render(args.plan, args.params, args.seed, args.profile_root, args.capacity_tps,
                                                args.campaign_id)
    doc = json.loads(schedule_json)
    summary = {"pairs": len(doc["pairs"]), "runs": len(files), "draft": doc["draft"],
               "baseline_tps": doc["baseline_tps"],
               "pair_order": {o: sum(p["pair_order"] == o for p in doc["pairs"]) for o in ORDERS}}
    if args.dry_run:
        print(json.dumps(summary, indent=2)); return 0
    targets = {ROOT / k: v for k, v in files.items()}
    sched_dir = Path(args.schedule_dir)
    targets[sched_dir / "schedule.json"] = schedule_json
    targets[sched_dir / "schedule.csv"] = schedule_csv
    conflicts = [str(p) for p, text in targets.items() if p.exists() and p.read_text(encoding="utf-8") != text]
    if conflicts:
        raise SystemExit("Refusing to overwrite differing generated files (new seed/params need a new campaign "
                         "ID or a deliberate cleanup):\n  " + "\n  ".join(conflicts[:10]))
    for p, text in targets.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
