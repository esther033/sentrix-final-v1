"""Injection evidence from the source pod's network namespace (SETUP-REVIEW 7.17).

The NetworkChaos status only says the injector succeeded. On 206-40 a loss
fault reported AllInjected while netem dropped nothing (kernel 7.0 correlated
loss), so run-attended.py saves what the kernel actually has: tc qdisc and
filter with counters and ipset, read through chaos-daemon (hostPID, nsexec),
at AllInjected and again shortly before removal. The counters of the second
snapshot show whether netem really delayed or dropped packets.

Capturing never fails a run: errors are recorded in the evidence instead.
"""
from datetime import datetime, timezone
import re

COMMANDS = {"tc_qdisc": "tc -s qdisc show", "tc_class": "tc -s class show dev eth0",
            "tc_filter": "tc -s filter show dev eth0", "ipset": "ipset list",
            # netns-wide TCP counters (absolute): retransmits between snapshots
            "nstat": "nstat -az TcpOutSegs TcpRetransSegs TcpExtTCPLossProbes TcpExtTCPTimeouts TcpExtTCPFastRetrans"}
NETEM = re.compile(r"^qdisc netem (\S+) .*?parent (\S+) limit \d+ (?P<params>.*?)\s*\n"
                   r"\s*Sent (?P<bytes>\d+) bytes (?P<pkts>\d+) pkt \(dropped (?P<dropped>\d+)", re.M)


def parse_netem(tc_qdisc):
    """netem qdiscs in `tc -s qdisc show` output with their counters."""
    out = []
    for m in NETEM.finditer(tc_qdisc or ""):
        sent, dropped = int(m["pkts"]), int(m["dropped"])
        out.append({"handle": m.group(1), "parent": m.group(2), "params": m["params"],
                    "sent_pkts": sent, "dropped_pkts": dropped,
                    "drop_pct": round(100 * dropped / (sent + dropped), 2) if sent + dropped else None})
    return out


def parse_nstat(text):
    """{counter: value} from `nstat -az` output."""
    out = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("Tcp") and parts[1].isdigit():
            out[parts[0]] = int(parts[1])
    return out


def pod_pid(kube, daemon, pod_uid):
    """A non-pause process of the pod, seen from chaos-daemon's host PID namespace."""
    pat = pod_uid.replace("-", ".")
    out = kube("exec", "-n", "chaos-mesh", daemon, "--", "sh", "-c",
               f'for p in /proc/[0-9]*; do grep -q "{pat}" $p/cgroup 2>/dev/null && '
               f'echo ${{p#/proc/}} $(cat $p/comm); done; true')
    pids = [l.split()[0] for l in out.splitlines() if l.strip() and not l.rstrip().endswith(" pause")]
    if not pids:
        raise RuntimeError("no process found for pod uid " + pod_uid)
    return pids[0]


def capture(kube, pod_name, pod_uid):
    """-> {captured_at, pod, pod_uid, pid, tc_qdisc, ..., netem} or {..., error}."""
    ev = {"captured_at": datetime.now(timezone.utc).isoformat(), "pod": pod_name, "pod_uid": pod_uid}
    try:
        daemon = kube("get", "pods", "-n", "chaos-mesh", "-l", "app.kubernetes.io/component=chaos-daemon",
                      "-o", "jsonpath={.items[0].metadata.name}").strip()
        pid = pod_pid(kube, daemon, pod_uid)
        ev.update(daemon=daemon, pid=pid)
        sep = "@@@SENTRIX@@@"
        script = "; ".join(f'echo "{sep}{k}"; nsexec -n /proc/{pid}/ns/net -- {c} 2>&1'
                           for k, c in COMMANDS.items()) + "; true"
        text = kube("exec", "-n", "chaos-mesh", daemon, "--", "sh", "-c", script)
        for chunk in text.split(sep)[1:]:
            key, _, body = chunk.partition("\n")
            ev[key.strip()] = body
        ev["netem"] = parse_netem(ev.get("tc_qdisc"))
        ev["tcp"] = parse_nstat(ev.get("nstat"))
    except Exception as e:  # noqa: BLE001 -- evidence capture must not abort a run
        ev["error"] = f"{type(e).__name__}: {e}"
    return ev


def summarize(before_removal, action, at_injected=None):
    """Did netem act on this pod's egress? loss: some packets dropped; delay: netem
    carried packets. None when there is no usable snapshot. With the AllInjected
    snapshot, also the pod's TCP counter deltas over the fault window."""
    netems = [n for ev in before_removal or [] for n in ev.get("netem") or []]
    tcp = {}
    for a, b in zip(at_injected or [], before_removal or []):
        for k, v in (b.get("tcp") or {}).items():
            if k in (a.get("tcp") or {}):
                tcp[k] = tcp.get(k, 0) + v - a["tcp"][k]
    if not netems:
        return {"netem_present": False, "applied": False if before_removal else None, "tcp_delta": tcp}
    sent = sum(n["sent_pkts"] for n in netems)
    dropped = sum(n["dropped_pkts"] for n in netems)
    applied = dropped > 0 if action == "loss" else sent > 0
    return {"netem_present": True, "params": [n["params"] for n in netems], "sent_pkts": sent,
            "dropped_pkts": dropped,
            "drop_pct": round(100 * dropped / (sent + dropped), 2) if sent + dropped else None,
            "applied": applied, "tcp_delta": tcp}
