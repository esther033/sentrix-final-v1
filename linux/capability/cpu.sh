#!/usr/bin/env bash
# StressChaos capability on probe-cpu (500m limit, like the app services).
# Evidence: cgroup v2 cpu.max and cpu.stat deltas over 30 s before / during /
# after, Chaos status, and the processes inside the target cgroup.
# PASS: during usage >= 0.40 cores and nr_throttled delta > 0;
#       after usage <= 0.10 cores; cpu.max unchanged.
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
D="$OUT/cpu"; mkdir -p "$D"
trap cleanup_chaos EXIT
ensure_probes
P=$(pod_of probe-cpu)
stat30() {
  kubectl -n $NS exec "$P" -- sh -c 'cat /sys/fs/cgroup/cpu.max; cat /sys/fs/cgroup/cpu.stat; sleep 30; echo ---; cat /sys/fs/cgroup/cpu.stat' > "$D/cpu-$1.txt" 2>&1
}
stat30 before
cat > "$D/manifest.yaml" <<YAML
apiVersion: chaos-mesh.org/v1alpha1
kind: StressChaos
metadata: {name: probe-cpu-stress, namespace: $NS}
spec:
  mode: one
  selector: {namespaces: [$NS], labelSelectors: {app: probe-cpu}}
  stressors: {cpu: {workers: 1, load: 100}}
  duration: 120s
YAML
kubectl apply -f "$D/manifest.yaml" >/dev/null
if ! wait_cond stresschaos probe-cpu-stress AllInjected 60; then
  log "FAIL stress not injected"; kubectl -n $NS get stresschaos probe-cpu-stress -o yaml > "$D/status.yaml"; exit 1
fi
kubectl -n $NS get stresschaos probe-cpu-stress -o yaml > "$D/status-injected.yaml"
sleep 5
stat30 during
kubectl -n $NS exec "$P" -- sh -c 'cat /sys/fs/cgroup/cgroup.procs; ps' > "$D/procs-during.txt" 2>&1 || true
kubectl -n $NS delete stresschaos probe-cpu-stress --wait=true >/dev/null
sleep 10
stat30 after
python3 "$HERE/judge.py" cpu "$D"
