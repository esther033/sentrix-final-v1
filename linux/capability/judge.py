"""PASS/FAIL judgement for capability probes; writes <dir>/summary.json.

Thresholds are fixed here, before any probe runs, and are deliberately loose
proofs of mechanism (delay visible, scoped, removed). They are not the
campaign fault intensities, which are calibrated separately.
"""
import json
from pathlib import Path
import re
import sys


def network(d, b_rtt, b_ortt, dl_rtt, dl_ortt, da_rtt, l_loss, l_oloss, la_loss):
    f = float
    qdisc_before = (d / "tc-before.txt").read_text()
    r = {"before": {"rtt_ms": f(b_rtt), "other_rtt_ms": f(b_ortt)},
         "delay": {"rtt_ms": f(dl_rtt), "other_rtt_ms": f(dl_ortt), "after_rtt_ms": f(da_rtt)},
         "loss": {"loss_pct": f(l_loss), "other_loss_pct": f(l_oloss), "after_loss_pct": f(la_loss)}}
    r["checks"] = {
        "delay_applied": r["delay"]["rtt_ms"] >= r["before"]["rtt_ms"] + 80,
        "delay_scoped": r["delay"]["other_rtt_ms"] < r["before"]["other_rtt_ms"] + 20,
        "delay_removed": r["delay"]["after_rtt_ms"] <= r["before"]["rtt_ms"] + 10,
        "delay_qdisc_restored": (d / "tc-delay-after.txt").read_text() == qdisc_before,
        "loss_applied": r["loss"]["loss_pct"] >= 4,
        "loss_scoped": r["loss"]["other_loss_pct"] <= 1,
        "loss_removed": r["loss"]["after_loss_pct"] <= 1,
        "loss_qdisc_restored": (d / "tc-loss-after.txt").read_text() == qdisc_before,
    }
    return r


def cpu_stat(path):
    text = path.read_text()
    first, second = text.split("---")
    g = lambda s, k: int(re.search(rf"^{k} (\d+)", s, re.M).group(1))
    return {"cpu_max": text.splitlines()[0],
            "cores": (g(second, "usage_usec") - g(first, "usage_usec")) / 30e6,
            "nr_throttled_delta": g(second, "nr_throttled") - g(first, "nr_throttled")}


def cpu(d):
    r = {k: cpu_stat(d / f"cpu-{k}.txt") for k in ("before", "during", "after")}
    r["checks"] = {"stress_saturates": r["during"]["cores"] >= 0.40,
                   "throttling_observed": r["during"]["nr_throttled_delta"] > 0,
                   "removed": r["after"]["cores"] <= 0.10,
                   "limit_unchanged": r["before"]["cpu_max"] == r["after"]["cpu_max"]}
    return r


def pod(d, uid0, ready0, seen_false, uid1, ready1):
    return {"uid_before": uid0, "uid_after": uid1,
            "checks": {"ready_before": ready0 == "true", "unready_during": seen_false == "true",
                       "ready_after": ready1 == "true", "same_uid": uid0 == uid1}}


if __name__ == "__main__":
    kind, d, *rest = sys.argv[1:]
    d = Path(d)
    result = {"network": network, "cpu": cpu, "pod": pod}[kind](d, *rest)
    result["pass"] = all(result["checks"].values())
    (d / "summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["pass"] else 1)
