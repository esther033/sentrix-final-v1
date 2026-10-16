# shared helpers for capability probes
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINUX="$(cd "$HERE/.." && pwd)"
. "$LINUX/config/versions.env"
export PATH="$HOME/.local/bin:$PATH"
NS=sentrix-probe
OUT="${OUT:-$LINUX/out/capability-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT"
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$OUT/probe.log"; }
ensure_probes() {
  sed -e "s#__NETSHOOT__#$PROBE_NETSHOOT_IMAGE#" -e "s#__BUSYBOX__#$PROBE_BUSYBOX_IMAGE#" "$HERE/probe-pods.yaml" | kubectl apply -f - >/dev/null
  kubectl -n $NS rollout status deploy --timeout=300s >/dev/null
}
pod_of() { kubectl -n $NS get pod -l app="$1" -o jsonpath='{.items[0].metadata.name}'; }
ip_of() { kubectl -n $NS get pod -l app="$1" -o jsonpath='{.items[0].status.podIP}'; }
wait_cond() { # kind name condition timeout
  local end=$((SECONDS+$4))
  while [ $SECONDS -lt $end ]; do
    if kubectl -n $NS get "$1" "$2" -o json | python3 -c "import json,sys; c={x['type']:x['status'] for x in json.load(sys.stdin).get('status',{}).get('conditions',[])}; sys.exit(0 if c.get('$3')=='True' else 1)"; then return 0; fi
    sleep 2
  done
  return 1
}
cleanup_chaos() { kubectl -n $NS delete stresschaos,networkchaos,podchaos --all --wait=true >/dev/null 2>&1 || true; }
