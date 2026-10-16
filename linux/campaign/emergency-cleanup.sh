#!/usr/bin/env bash
# Use only when a run was killed (power loss, kill -9) and its own finally-block
# could not remove the fault. Pauses, then deletes every Chaos object in the
# app and probe namespaces, waits for recovery, and records what it saw.
# Does NOT touch runs/ (the interrupted run keeps its ID and is excluded or
# retried under a new attempt ID by a human decision).
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
OUT="$ROOT/linux/out/emergency-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$OUT"
for ns in sentrix sentrix-probe; do
  kubectl -n "$ns" get stresschaos,networkchaos,podchaos -o yaml > "$OUT/chaos-before-$ns.yaml" 2>&1
  for kind in stresschaos networkchaos podchaos; do
    for name in $(kubectl -n "$ns" get "$kind" -o name 2>/dev/null); do
      kubectl -n "$ns" annotate "$name" experiment.chaos-mesh.org/pause=true --overwrite
      kubectl -n "$ns" delete "$name" --wait=true --timeout=120s
    done
  done
done
kubectl -n sentrix rollout status deploy --timeout=300s | tee "$OUT/rollout.txt"
kubectl -n sentrix get pods -o wide > "$OUT/pods-after.txt"
echo "evidence: $OUT"
echo "Check qdisc state on an affected app pod if needed: kubectl -n sentrix debug <pod> --image=nicolaka/netshoot -- tc qdisc show"
