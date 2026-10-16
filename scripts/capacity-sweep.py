"""Measure the sustainable transaction capacity C (no faults injected).

For each candidate rate, one control-style run (calibration ID prefix
`calib-<campaign>-capacity-`, never a campaign ID) goes through run-attended.py,
so it gets the same health gates, export and quality checks as a real run.
A rate PASSES only if, over the steady part (after warmup):
  * success rate          >= --min-success   (default 99.5 %)
  * transaction p99       <= --max-p99-ms    (default 3x the p99 at the lowest rate, >= 500 ms)
  * achieved/offered rate within 90-110 %, k6 dropped iterations <= 1 %
  * run-assessment-v2.json valid (telemetry export complete, quality gates PASS)
C = the highest passing rate below the first failing rate. The criterion is
fixed here before measuring and is written into capacity-result.json together
with every per-rate number, so the frozen value can be audited.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluation_v2 import stamp  # noqa: E402


def profile(name, rate, minutes):
    total = minutes * 60
    warm, cool = 120, 60
    rest = total - warm - cool
    phases = {"warmup_seconds": warm, "baseline_seconds": rest // 3, "fault_seconds": rest // 3,
              "recovery_seconds": rest - 2 * (rest // 3), "cooldown_seconds": cool}
    return {"profile_name": name, "campaign_id": None, "run_role": "calibration",
            "target_rps": rate, "time_unit": "1s", "duration": f"{minutes}m", **phases,
            "traffic_phase_rps": {p: rate for p in ("warmup", "baseline", "fault", "recovery", "cooldown")},
            "pre_allocated_vus": max(15, int(rate * 10)), "max_vus": max(80, int(rate * 40) + 10),
            "stage_timeout": "5s", "trace_workers": 2, "workload_seed": 1}


def steady_stats(run_dir, warmup):
    rows = [json.loads(l) for l in (run_dir / "transaction-results.jsonl").read_text(encoding="utf-8").splitlines() if l]
    rows = sorted((r for r in rows if r["stage"] == "TRANSACTION_SUMMARY"), key=stamp)
    t0 = stamp(rows[0])
    steady = [r for r in rows if (stamp(r) - t0).total_seconds() >= warmup]
    d = sorted(r["duration_ms"] for r in steady)
    dropped = sum(x["dropped_iterations"] for x in json.loads((run_dir / "workload-timeseries.json").read_text()))
    return {"transactions": len(steady), "success_pct": 100 * sum(r["success"] for r in steady) / len(steady),
            "p50_ms": d[len(d) // 2], "p99_ms": d[int(len(d) * .99)], "dropped_iterations": dropped,
            "all_transactions": len(rows)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rates", required=True, help="comma list of transactions/s, ascending, e.g. 1,2,3,4,6,8")
    ap.add_argument("--minutes", type=int, default=10)
    ap.add_argument("--campaign", default="linux-v1")
    ap.add_argument("--min-success", type=float, default=99.5)
    ap.add_argument("--max-p99-ms", type=float)
    ap.add_argument("--k6-bin", default="k6")
    args = ap.parse_args()
    rates = [float(x) for x in args.rates.split(",")]
    if rates != sorted(rates):
        ap.error("rates must be ascending")
    stamp_id = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S")
    out = ROOT / "runs" / "_calibration" / f"capacity-{stamp_id}"
    out.mkdir(parents=True, exist_ok=False)
    results, p99_limit, capacity = [], args.max_p99_ms, None
    for rate in rates:
        rid = f"calib-{args.campaign}-capacity-{str(rate).replace('.', 'p')}-{stamp_id}"
        prof = profile(rid, int(rate) if rate.is_integer() else rate, args.minutes)
        ppath = out / (rid + ".json")
        ppath.write_text(json.dumps(prof, indent=2), encoding="utf-8")
        rc = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/run-attended.py"), "--run-id", rid,
                             "--profile", str(ppath), "--k6-bin", args.k6_bin], cwd=ROOT).returncode
        run_dir = ROOT / "runs" / rid
        entry = {"rate_tps": rate, "run_id": rid, "run_attended_rc": rc}
        try:
            entry.update(steady_stats(run_dir, prof["warmup_seconds"]))
            assessment = json.loads((run_dir / "run-assessment-v2.json").read_text())
            entry["assessment_valid"] = assessment["valid"]; entry["assessment_errors"] = assessment["errors"]
        except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError) as exc:
            entry["error"] = str(exc)
        if p99_limit is None and "p99_ms" in entry:
            p99_limit = max(500.0, 3 * entry["p99_ms"])
        expected = rate * (args.minutes * 60)
        entry["checks"] = {
            "success": entry.get("success_pct", 0) >= args.min_success,
            "p99": "p99_ms" in entry and entry["p99_ms"] <= p99_limit,
            "achieved_rate": "all_transactions" in entry and .9 * expected <= entry["all_transactions"] <= 1.1 * expected,
            "dropped": entry.get("dropped_iterations", 1e9) <= .01 * expected,
            "telemetry_and_quality": entry.get("assessment_valid") is True,
        }
        entry["pass"] = all(entry["checks"].values())
        results.append(entry)
        print(json.dumps(entry), flush=True)
        if not entry["pass"]:
            break
        capacity = rate
    doc = {"measured_at": datetime.now(timezone.utc).isoformat(), "minutes_per_rate": args.minutes,
           "criteria": {"min_success_pct": args.min_success, "max_p99_ms": p99_limit,
                        "achieved_rate_band": [0.9, 1.1], "max_dropped_fraction": 0.01,
                        "assessment_valid_required": True},
           "results": results, "capacity_tps": capacity,
           "note": "Copy capacity_tps into campaigns/<id>/fault-params.yaml only together with this file's path."}
    (out / "capacity-result.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(f"capacity C = {capacity} tx/s  ->  {out / 'capacity-result.json'}")
    return 0 if capacity is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
