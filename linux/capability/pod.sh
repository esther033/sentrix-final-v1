#!/usr/bin/env bash
# PodChaos pod-failure capability on probe-cpu.
# PASS: Ready=False observed while injected, Ready=True after removal,
#       same pod UID (pod-failure is not pod-kill).
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
D="$OUT/pod"; mkdir -p "$D"
trap cleanup_chaos EXIT
ensure_probes
# Trailing echo: jsonpath prints no newline, `read` then returns 1 at EOF and
# set -e (lib.sh) silently killed this script before any injection (206-40).
ready() { kubectl -n $NS get pod -l app=probe-cpu -o jsonpath='{.items[0].metadata.uid} {.items[0].status.containerStatuses[0].ready}'; echo; }
read -r UID0 R0 < <(ready)
cat > "$D/manifest.yaml" <<YAML
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata: {name: probe-pod-failure, namespace: $NS}
spec:
  action: pod-failure
  mode: one
  selector: {namespaces: [$NS], labelSelectors: {app: probe-cpu}}
  duration: 60s
YAML
kubectl apply -f "$D/manifest.yaml" >/dev/null
wait_cond podchaos probe-pod-failure AllInjected 60 || { log "FAIL pod-failure not injected"; exit 1; }
SEEN_FALSE=false
for _ in $(seq 1 30); do
  read -r U R < <(ready); echo "$(date -u +%T) $U $R" >> "$D/readiness.txt"
  [ "$R" = "false" ] && SEEN_FALSE=true
  sleep 2
done
wait_cond podchaos probe-pod-failure AllRecovered 180 || log "WARN AllRecovered not observed"
kubectl -n $NS get podchaos probe-pod-failure -o yaml > "$D/status-final.yaml"
kubectl -n $NS wait --for=condition=Ready pod -l app=probe-cpu --timeout=180s >/dev/null || true
read -r UID1 R1 < <(ready)
python3 "$HERE/judge.py" pod "$D" "$UID0" "$R0" "$SEEN_FALSE" "$UID1" "$R1"
