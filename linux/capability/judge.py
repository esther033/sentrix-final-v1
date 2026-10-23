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


def http_stats(path):
    """curl lines 'time_connect time_total http_code' -> n, failed, median ms, affected %.

    affected = failed (non-200 / timeout) or total >= 200 ms: on a sub-ms path
    only a retransmission (min RTO 200 ms, SYN RTO 1 s) or an injected delay
    reaches that.
    """
    rows = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) == 3 and re.fullmatch(r"\d+", parts[2]):
            rows.append((float(parts[1]) * 1000, parts[2] == "200"))
    ok = sorted(t for t, good in rows if good)
    affected = sum(1 for t, good in rows if not good or t >= 200)
    return {"n": len(rows), "failed": sum(1 for _, good in rows if not good),
            "median_ms": round(ok[len(ok) // 2], 2) if ok else None,
            "affected_pct": round(100 * affected / len(rows), 1) if rows else None}


def connect_ms(path):
    """time_connect (ms) of the successful curl lines: SYN out, SYN-ACK back, so
    the delayed hop is crossed exactly once (one latency + jitter sample)."""
    out = []
    for line in path.read_text().splitlines() if path.exists() else []:
        parts = line.split()
        if len(parts) == 3 and parts[2] == "200":
            out.append(float(parts[0]) * 1000)
    return out


def delay_spec(d):
    """(latency_ms, jitter_ms) from the delay_from_template line of svc-addresses.txt."""
    m = re.search(r"delay_from_template=(\d+)ms/(\d+)ms/", (d / "svc-addresses.txt").read_text()) \
        if (d / "svc-addresses.txt").exists() else None
    return (float(m.group(1)), float(m.group(2))) if m else (100.0, 0.0)


def delay_shape(before, during):
    """Added connect delay: median, sample stdev and p5..p95 of during - median(before)."""
    if len(before) < 5 or len(during) < 5:
        return None
    base = sorted(before)[len(before) // 2]
    xs = sorted(x - base for x in during)
    mean = sum(xs) / len(xs)
    q = lambda f: xs[min(len(xs) - 1, int(len(xs) * f))]
    return {"n": len(xs), "median_ms": round(q(.5), 2), "stdev_ms": round((sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)) ** .5, 2),
            "p05_ms": round(q(.05), 2), "p95_ms": round(q(.95), 2)}


def netem_drop_pct(path, pod_prefix="probe-src"):
    """netem drop % on one probe pod from a `tc -s qdisc` dump (svc-tc-*.txt)."""
    if not path.exists():
        return None
    blocks = re.split(r"^== ", path.read_text(), flags=re.M)
    for b in blocks:
        if b.startswith(pod_prefix):
            m = re.search(r"qdisc netem .*\n\s*Sent \d+ bytes (\d+) pkt \(dropped (\d+)", b)
            if m:
                sent, dropped = int(m.group(1)), int(m.group(2))
                return round(100 * dropped / (sent + dropped), 2) if sent + dropped else None
    return None


def service(d, gate_method, *methods):
    """Service-path (ClusterIP) delay/loss per injection method; ping checks stay in network()."""
    r = {"gate_method": gate_method, "methods": {}}
    for m in methods:
        st = {ph: {t: http_stats(d / f"svc-{m}-{ph}-{t}.txt")
                   for t in ("dst_pod", "dst_svc", "other_svc", "other_pod")
                   if (d / f"svc-{m}-{ph}-{t}.txt").exists()}
              for ph in ("before", "delay", "delay-after", "loss", "loss-after")}
        med = lambda ph, t: (st[ph].get(t) or {}).get("median_ms")
        aff = lambda ph, t: (st[ph].get(t) or {}).get("affected_pct")
        ge = lambda a, b: a is not None and b is not None and a >= b
        le = lambda a, b: a is not None and b is not None and a <= b
        b_svc, b_osvc = med("before", "dst_svc"), med("before", "other_svc")
        lat, jit = delay_spec(d)
        shape = delay_shape(connect_ms(d / f"svc-{m}-before-dst_svc.txt"), connect_ms(d / f"svc-{m}-delay-dst_svc.txt"))
        checks = {
            # fresh connection: handshake + request both cross the delayed hop -> >= +80 ms is loose
            "svc_delay_applied": ge(med("delay", "dst_svc"), (b_svc or 0) + 80),
            "svc_delay_scoped": le(med("delay", "other_svc"), (b_osvc or 0) + 20),
            "svc_delay_removed": le(med("delay-after", "dst_svc"), (b_svc or 0) + 10),
            # one crossing of the delayed hop: latency within 15 ms, and a spread that
            # matches the jitter (netem's jitter: stdev ~0.58 x jitter uniform,
            # ~1 x jitter normal table). Catches a jitter that is lost or blown up (7.18).
            "svc_delay_latency_matches": shape is not None and abs(shape["median_ms"] - lat) <= 15,
            "svc_delay_jitter_matches": shape is not None and (
                0.25 * jit <= shape["stdev_ms"] <= 1.5 * jit if jit else shape["stdev_ms"] <= 3),
            "svc_loss_applied": ge(aff("loss", "dst_svc"), 10),
            "svc_loss_scoped": le(aff("loss", "other_svc"), 2),
            "svc_loss_removed": le(aff("loss-after", "dst_svc"), 2),
            # the kernel really dropped packets (loss 10 % asked; half is the floor).
            # Catches netem correlated loss that drops far less than asked (7.17).
            "svc_loss_netem_drops": ge(netem_drop_pct(d / f"svc-tc-{m}-loss-end.txt"), 5),
        }
        pod_path = {"pod_delay_applied": ge(med("delay", "dst_pod"), (med("before", "dst_pod") or 0) + 80),
                    "pod_loss_applied": ge(aff("loss", "dst_pod"), 10)}
        r["methods"][m] = {"stats": st, "checks": checks, "pod_path_info": pod_path,
                           "delay_spec_ms": {"latency": lat, "jitter": jit}, "delay_connect_added": shape,
                           "netem_drop_pct_src": netem_drop_pct(d / f"svc-tc-{m}-loss-end.txt"),
                           "service_path_pass": all(checks.values())}
    r["checks"] = r["methods"].get(gate_method, {}).get("checks") or {"gate_method_measured": False}
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
    result = {"network": network, "cpu": cpu, "pod": pod, "service": service}[kind](d, *rest)
    result["pass"] = all(result["checks"].values())
    (d / ("service-summary.json" if kind == "service" else "summary.json")).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["pass"] else 1)
