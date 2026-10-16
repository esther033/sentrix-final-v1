"""Final matched-pair evaluation, for either pair order.

control_then_fault already matches the control before injecting (run-attended).
fault_then_control cannot, because the control does not exist yet, so the
fault run is executed with --defer-control-match and this script applies the
same match_control rules once the control has finished. Nothing is relaxed:
workload keys, phase rates, environment fingerprint, control validity and a
2h freshness bound are all checked, only the time direction differs.

Writes runs/<fault-id>/pair-assessment.json (preserving earlier versions).
Exit code 0 only when the pair is valid.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path

import yaml

from evaluation_v2 import match_control
from telemetry_export import save_json, utc_now
from view_integrity import safe_name

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate(runs_dir, fault_id, control_id, pair_order):
    for name in (fault_id, control_id):
        safe_name(name)
    runs_dir = Path(runs_dir)
    fault_dir, control_dir = runs_dir / fault_id, runs_dir / control_id
    errors = []
    try:
        manifest = yaml.safe_load((fault_dir / "run-manifest.yaml").read_text(encoding="utf-8"))
        fault_profile = manifest["workload"]["profile"]
        before = read_json(fault_dir / "environment-before.json")
        runtime = read_json(fault_dir / "runtime.json")
        if pair_order == "fault_then_control":
            anchor = runtime.get("finished_at") or runtime.get("started_at")
        else:
            anchor = runtime.get("started_at")
        at = datetime.fromisoformat(anchor.replace("Z", "+00:00"))
        if fault_profile.get("pair_order") not in (None, pair_order):
            errors.append("fault profile pair_order differs from requested pair_order")
        control_manifest = yaml.safe_load((control_dir / "run-manifest.yaml").read_text(encoding="utf-8"))
        if control_manifest["workload"]["profile"].get("pair_id") != fault_profile.get("pair_id"):
            errors.append("pair_id mismatch between control and fault profiles")
        match = match_control(control_dir, fault_profile, before["fingerprint"], at, pair_order=pair_order)
        errors.extend(match["errors"])
        if runtime.get("errors"):
            errors.append("fault run supervisor errors: " + "; ".join(map(str, runtime["errors"])))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    result = {"fault_run_id": fault_id, "control_run_id": control_id, "pair_order": pair_order,
              "evaluated_at": utc_now(), "valid": not errors, "errors": errors}
    save_json(fault_dir / "pair-assessment.json", result, preserve=True)
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fault-id", required=True)
    ap.add_argument("--control-id", required=True)
    ap.add_argument("--pair-order", required=True, choices=["control_then_fault", "fault_then_control"])
    ap.add_argument("--runs-dir", default=str(ROOT / "runs"))
    args = ap.parse_args()
    result = evaluate(args.runs_dir, args.fault_id, args.control_id, args.pair_order)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
