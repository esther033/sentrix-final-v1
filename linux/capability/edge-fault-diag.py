"""Diagnose whether an edge NetworkChaos really applies to app traffic (SETUP-REVIEW 7.17).

Renders the formal template from a campaign profile (scripts/fault_manifest.py,
the same path as run-attended.py) with a short duration, injects it while a
light HTTP load hits frontend pages that call productcatalog, and saves from
the source pod's netns (via chaos-daemon nsexec): tc qdisc/class/filter with
counters, ipset, iptables mangle, nstat TCP counters, plus the chaos-daemon
log right after injection and after recovery. Page latencies come from the
load loop. Read-only for the app except the injected fault itself; the
NetworkChaos object is saved and deleted afterwards.

  .venv/bin/python -B linux/capability/edge-fault-diag.py <profile.json> [--seconds 60] [--tag loss]
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import fault_manifest  # noqa: E402

FRONTEND = "http://127.0.0.1:30080"
PRODUCTS = ["OLJCESPC7Z", "66VCHSJNUP", "1YMWWN1N4O", "L9ECAV7KIM", "2ZYFJ3GM2N", "0PUK6V6EV0",
            "LS4PSXUNUM", "9SIQT8TOJO", "6E92ZMYYFZ"]


def now():
    return datetime.now(timezone.utc).isoformat()


def kube(*args, check=True, stdin=None):
    p = subprocess.run(["kubectl", *args], capture_output=True, text=True, input=stdin, timeout=60)
    if check and p.returncode:
        raise RuntimeError(f"kubectl {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def daemon_pod():
    return kube("get", "pods", "-n", "chaos-mesh", "-l", "app.kubernetes.io/component=chaos-daemon",
                "-o", "jsonpath={.items[0].metadata.name}").strip()


def pod_pid(daemon, pod_uid):
    """A non-pause process of the pod, found from the host PID namespace."""
    pat = pod_uid.replace("-", ".")
    out = kube("exec", "-n", "chaos-mesh", daemon, "--", "sh", "-c",
               f'for p in /proc/[0-9]*; do grep -q "{pat}" $p/cgroup 2>/dev/null && '
               f'echo ${{p#/proc/}} $(cat $p/comm); done', check=False)
    pids = [l.split()[0] for l in out.splitlines() if l.strip() and not l.endswith(" pause")]
    if not pids:
        raise RuntimeError("no process found for pod uid " + pod_uid)
    return pids[0]


def netns_dump(daemon, pid):
    ns = f"nsexec -n /proc/{pid}/ns/net --"
    script = "; ".join(f'echo "### {c}"; {ns} {c} 2>&1' for c in (
        "tc -s qdisc show", "tc -s class show dev eth0", "tc -s filter show dev eth0",
        "ipset list", "iptables-save -c -t mangle", "nstat -az TcpRetransSegs TcpExtTCPLossProbes "
        "TcpExtTCPLostRetransmit TcpExtTCPTimeouts TcpOutSegs TcpExtTCPSackRecovery TcpExtTCPFastRetrans"))
    return kube("exec", "-n", "chaos-mesh", daemon, "--", "sh", "-c", script, check=False)


def counters(dump):
    out = {}
    for line in dump.split("### nstat", 1)[-1].splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("Tcp") and parts[1].isdigit():
            out[parts[0]] = int(parts[1])
    return out


def load(stop, rows, rps=6):
    i = 0
    while not stop.is_set():
        path = "/" if i % 3 == 0 else "/product/" + PRODUCTS[i % len(PRODUCTS)]
        t0 = time.time()
        try:
            with urllib.request.urlopen(FRONTEND + path, timeout=10) as r:
                r.read(); code = r.status
        except Exception as e:  # noqa: BLE001 -- record any failure
            code = type(e).__name__
        rows.append({"t": t0, "path": path, "ms": round((time.time() - t0) * 1000, 1), "code": code})
        i += 1
        time.sleep(max(0, 1 / rps - (time.time() - t0)))


def page_stats(rows, a, b):
    xs = sorted(r["ms"] for r in rows if a <= r["t"] < b)
    bad = sum(1 for r in rows if a <= r["t"] < b and r["code"] != 200)
    if not xs:
        return None
    q = lambda f: xs[min(len(xs) - 1, int(len(xs) * f))]
    return {"n": len(xs), "errors": bad, "p50_ms": q(.5), "p90_ms": q(.9), "p99_ms": q(.99), "max_ms": xs[-1],
            "ge200_pct": round(100 * sum(x >= 200 for x in xs) / len(xs), 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("profile")
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--tag", default="")
    ap.add_argument("--out", default=str(ROOT / "linux/out"))
    args = ap.parse_args()
    fault = json.loads(Path(args.profile).read_text(encoding="utf-8"))["fault"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%S")
    name = f"diag-{ts}-{args.tag or fault['type'].replace('_', '-')}"
    out = Path(args.out) / f"diag-edge-{ts}-{args.tag or fault['type']}"
    out.mkdir(parents=True)
    manifest, subs = fault_manifest.render((ROOT / fault["template"]).read_text(encoding="utf-8"), fault, name,
                                           args.seconds, cluster_ip_of=lambda s: kube(
                                               "get", "svc", s, "-n", "sentrix", "-o", "jsonpath={.spec.clusterIP}").strip())
    (out / "manifest.yaml").write_text(manifest, encoding="utf-8")
    daemon = daemon_pod()
    src = json.loads(kube("get", "pods", "-n", "sentrix", "-l", "app=" + subs["SOURCE_SERVICE"], "-o", "json"))["items"][0]
    pid = pod_pid(daemon, src["metadata"]["uid"])
    meta = {"name": name, "profile": args.profile, "substitutions": subs, "source_pod": src["metadata"]["name"],
            "source_pod_ip": src["status"].get("podIP"), "pid": pid, "daemon": daemon, "events": []}
    ev = lambda what: meta["events"].append({"at": now(), "t": time.time(), "what": what})

    rows, stop = [], threading.Event()
    th = threading.Thread(target=load, args=(stop, rows), daemon=True)
    th.start(); ev("load started")
    time.sleep(30)
    (out / "netns-before.txt").write_text(netns_dump(daemon, pid)); ev("before dump")
    t_apply = time.time()
    kube("apply", "-f", "-", stdin=manifest); ev("applied")
    injected = None
    for _ in range(120):
        obj = json.loads(kube("get", "networkchaos", name, "-n", "sentrix", "-o", "json"))
        conds = {c["type"]: c["status"] for c in obj.get("status", {}).get("conditions", [])}
        if conds.get("AllInjected") == "True":
            injected = time.time(); ev("AllInjected"); break
        time.sleep(0.5)
    (out / "chaos-daemon-after-inject.log").write_text(
        kube("logs", "-n", "chaos-mesh", daemon, "--since=5m", check=False)); ev("daemon log saved")
    dumps = []
    for k, at in enumerate((5, args.seconds // 2, args.seconds - 8)):
        time.sleep(max(0, (injected or t_apply) + at - time.time()))
        d = netns_dump(daemon, pid); (out / f"netns-during-{k}.txt").write_text(d); dumps.append(d)
        ev(f"during dump {k} (+{at}s)")
    for _ in range(120):
        obj = json.loads(kube("get", "networkchaos", name, "-n", "sentrix", "-o", "json"))
        conds = {c["type"]: c["status"] for c in obj.get("status", {}).get("conditions", [])}
        if conds.get("AllRecovered") == "True":
            ev("AllRecovered"); break
        time.sleep(1)
    rec = time.time()
    (out / "chaos-object.json").write_text(json.dumps(obj, indent=1))
    time.sleep(30)
    after = netns_dump(daemon, pid)
    (out / "netns-after.txt").write_text(after); ev("after dump")
    stop.set(); th.join(timeout=15); ev("load stopped")
    (out / "chaos-daemon-after-recover.log").write_text(
        kube("logs", "-n", "chaos-mesh", daemon, "--since=10m", check=False))
    kube("delete", "networkchaos", name, "-n", "sentrix", check=False); ev("object deleted")
    (out / "pages.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    c0, c1, c2 = counters((out / "netns-before.txt").read_text()), counters(dumps[-1]), counters(after)
    summary = {**meta,
               "pages": {"before": page_stats(rows, t_apply - 30, t_apply),
                         "during": page_stats(rows, (injected or t_apply) + 2, rec),
                         "after": page_stats(rows, rec + 2, rec + 30)},
               "nstat_delta_during": {k: c1.get(k, 0) - c0.get(k, 0) for k in c0},
               "nstat_delta_total": {k: c2.get(k, 0) - c0.get(k, 0) for k in c0},
               "netem_in_tc_during": "netem" in dumps[0], "evidence_dir": str(out)}
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in ("name", "pages", "nstat_delta_during", "netem_in_tc_during",
                                               "evidence_dir")}, indent=1))


if __name__ == "__main__":
    main()
