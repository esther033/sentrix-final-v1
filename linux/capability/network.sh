#!/usr/bin/env bash
# Edge-scoped NetworkChaos capability: delay and loss on probe-src -> probe-dst,
# with probe-src -> probe-other as the must-not-change control path.
# Evidence per phase (before / during / after): ping RTT + loss, tc qdisc and
# tc filter inside probe-src, the applied manifest and Chaos Mesh status.
# PASS criteria (written to summary.json):
#   delay 100ms: during avg RTT >= before + 80 ms; other path < before_other + 20 ms;
#                after RTT <= before + 10 ms; qdisc after == qdisc before
#   loss 10%:    during loss >= 4 %; other path loss <= 1 %; after loss <= 1 %
# probe-network-pod.py (pod-wide) is NOT a substitute for this edge test.
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
D="$OUT/network"; mkdir -p "$D"
trap cleanup_chaos EXIT
ensure_probes
SRC=$(pod_of probe-src); DST_IP=$(ip_of probe-dst); OTHER_IP=$(ip_of probe-other)
kubectl -n $NS get pods -o wide > "$D/pods.txt"

ping_stats() { # tag ip count -> prints "avg_ms loss_pct"
  kubectl -n $NS exec "$SRC" -- ping -n -q -c "$3" -i 0.2 -W 2 "$2" > "$D/ping-$1.txt" 2>&1 || true
  python3 "$HERE/parse_ping.py" "$D/ping-$1.txt"
}
tc_state() { kubectl -n $NS exec "$SRC" -- sh -c 'tc qdisc show; echo ---; tc filter show dev eth0 2>/dev/null' > "$D/tc-$1.txt" 2>&1 || true; }

apply_chaos() { # name action spec-line
  cat > "$D/manifest-$1.yaml" <<YAML
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata: {name: $1, namespace: $NS}
spec:
  action: $2
  mode: one
  selector: {namespaces: [$NS], labelSelectors: {app: probe-src}}
  direction: to
  target:
    mode: one
    selector: {namespaces: [$NS], labelSelectors: {app: probe-dst}}
  $3
  duration: 120s
YAML
  kubectl apply -f "$D/manifest-$1.yaml" >/dev/null
  if ! wait_cond networkchaos "$1" AllInjected 60; then
    log "FAIL $1 not injected"; kubectl -n $NS get networkchaos "$1" -o yaml > "$D/status-$1.yaml"; exit 1
  fi
  kubectl -n $NS get networkchaos "$1" -o yaml > "$D/status-$1-injected.yaml"
}
remove_chaos() { kubectl -n $NS delete networkchaos "$1" --wait=true >/dev/null; sleep 5; }

log "network probe: src=$SRC dst=$DST_IP other=$OTHER_IP"
tc_state before
read -r B_RTT B_LOSS < <(ping_stats before-dst "$DST_IP" 50)
read -r B_ORTT B_OLOSS < <(ping_stats before-other "$OTHER_IP" 50)

apply_chaos probe-delay delay 'delay: {latency: "100ms", jitter: "0ms", correlation: "0"}'
tc_state delay-during
read -r DL_RTT DL_LOSS < <(ping_stats delay-dst "$DST_IP" 50)
read -r DL_ORTT DL_OLOSS < <(ping_stats delay-other "$OTHER_IP" 50)
remove_chaos probe-delay
tc_state delay-after
read -r DA_RTT DA_LOSS < <(ping_stats delay-after-dst "$DST_IP" 50)

apply_chaos probe-loss loss 'loss: {loss: "10", correlation: "0"}'
tc_state loss-during
read -r L_RTT L_LOSS < <(ping_stats loss-dst "$DST_IP" 300)
read -r L_ORTT L_OLOSS < <(ping_stats loss-other "$OTHER_IP" 300)
remove_chaos probe-loss
tc_state loss-after
read -r LA_RTT LA_LOSS < <(ping_stats loss-after-dst "$DST_IP" 300)

python3 "$HERE/judge.py" network "$D" \
  "$B_RTT" "$B_ORTT" "$DL_RTT" "$DL_ORTT" "$DA_RTT" "$L_LOSS" "$L_OLOSS" "$LA_LOSS"
