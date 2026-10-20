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
#
# Service path (added 2026-10-20, SETUP-REVIEW 7.15): the app dials Service
# names, and kube-proxy DNATs ClusterIP -> pod IP in the host netns, after the
# source pod's egress tc. ping cannot reach a ClusterIP, so each phase runs
# N fresh HTTP requests (curl, new TCP connection each) from probe-src to the
# probe-dst Pod IP, probe-dst ClusterIP and the probe-other ClusterIP / Pod IP.
# Injection methods (NET_METHODS, default = NET_TEMPLATE_METHOD; the 7.15
# comparison ran NET_METHODS="current a b"):
#   current  selector=src, target=dst pod, direction to (template before 7.15)
#   a        current + externalTargets: [dst ClusterIP]
#   b        selector=dst, target=src pod, direction to (reply direction)
# Gate: the ping checks above AND the Service-path checks for
# NET_TEMPLATE_METHOD (default a = the method deploy/chaos-mesh/faults uses
# since 7.15), judge.py service.
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

rc=0
python3 "$HERE/judge.py" network "$D" \
  "$B_RTT" "$B_ORTT" "$DL_RTT" "$DL_ORTT" "$DA_RTT" "$L_LOSS" "$L_OLOSS" "$LA_LOSS" || rc=1

# ---- Service path ----
NET_TEMPLATE_METHOD="${NET_TEMPLATE_METHOD:-a}"
NET_METHODS="${NET_METHODS:-$NET_TEMPLATE_METHOD}"
DST=$(pod_of probe-dst)
DST_SVC=$(kubectl -n $NS get svc probe-dst -o jsonpath='{.spec.clusterIP}')
OTHER_SVC=$(kubectl -n $NS get svc probe-other -o jsonpath='{.spec.clusterIP}')
echo "dst_pod=$DST_IP dst_svc=$DST_SVC other_pod=$OTHER_IP other_svc=$OTHER_SVC" > "$D/svc-addresses.txt"
log "service path: dst_svc=$DST_SVC other_svc=$OTHER_SVC methods=[$NET_METHODS] gate=$NET_TEMPLATE_METHOD"

http_probe() { # file ip count -> one line per request: time_connect time_total http_code
  kubectl -n $NS exec "$SRC" -- sh -c "for i in \$(seq $3); do curl -s -o /dev/null --max-time 3 -w '%{time_connect} %{time_total} %{http_code}\\n' http://$2:8080/ || true; done" > "$D/$1" 2>&1 || true
}
probe_all() { # method phase count
  http_probe "svc-$1-$2-dst_pod.txt" "$DST_IP" "$3"
  http_probe "svc-$1-$2-dst_svc.txt" "$DST_SVC" "$3"
  http_probe "svc-$1-$2-other_svc.txt" "$OTHER_SVC" "$3"
  http_probe "svc-$1-$2-other_pod.txt" "$OTHER_IP" "$3"
}
tc_both() { # tag
  for pp in "$SRC" "$DST"; do
    echo "== $pp"; kubectl -n $NS exec "$pp" -- sh -c 'tc qdisc show; echo ---; tc filter show dev eth0 2>/dev/null; echo ---; ipset list 2>/dev/null | head -40' 2>&1 || true
  done > "$D/svc-tc-$1.txt"
}
svc_chaos() { # name method action spec-line
  local sel=probe-src tgt=probe-dst ext=""
  case "$2" in
    a) ext="externalTargets: [\"$DST_SVC\"]" ;;
    b) sel=probe-dst; tgt=probe-src ;;
  esac
  cat > "$D/manifest-$1.yaml" <<YAML
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata: {name: $1, namespace: $NS}
spec:
  action: $3
  mode: one
  selector: {namespaces: [$NS], labelSelectors: {app: $sel}}
  direction: to
  target:
    mode: one
    selector: {namespaces: [$NS], labelSelectors: {app: $tgt}}
  $ext
  $4
  duration: 900s
YAML
  kubectl apply -f "$D/manifest-$1.yaml" >/dev/null
  if ! wait_cond networkchaos "$1" AllInjected 60; then
    log "FAIL $1 not injected"; kubectl -n $NS get networkchaos "$1" -o yaml > "$D/status-$1.yaml"; return 1
  fi
  kubectl -n $NS get networkchaos "$1" -o yaml > "$D/status-$1-injected.yaml"
}

for m in $NET_METHODS; do
  log "service path method=$m"
  tc_both "$m-before"
  probe_all "$m" before 60
  svc_chaos "probe-svc-delay-$m" "$m" delay 'delay: {latency: "100ms", jitter: "0ms", correlation: "0"}' || { rc=1; continue; }
  tc_both "$m-delay-during"
  probe_all "$m" delay 60
  remove_chaos "probe-svc-delay-$m"
  tc_both "$m-delay-after"
  probe_all "$m" delay-after 60
  svc_chaos "probe-svc-loss-$m" "$m" loss 'loss: {loss: "10", correlation: "0"}' || { rc=1; continue; }
  tc_both "$m-loss-during"
  probe_all "$m" loss 150
  remove_chaos "probe-svc-loss-$m"
  tc_both "$m-loss-after"
  probe_all "$m" loss-after 150
done

python3 "$HERE/judge.py" service "$D" "$NET_TEMPLATE_METHOD" $NET_METHODS || rc=1
exit $rc
