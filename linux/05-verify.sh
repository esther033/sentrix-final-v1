#!/usr/bin/env bash
# Endpoint + provenance check. Writes linux/out/deploy-<utc>/ with tool
# versions, helm releases, image digests, node info and endpoint results.
# This directory is the "배포 버전 및 image digest 파일" for ACCEPTANCE.md.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
set -a; . "$HERE/config/endpoints.env"; set +a
OUT="$HERE/out/deploy-$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$OUT"
fail=0

{ k3s --version; kubectl version -o yaml; helm version; k6 version; python3 --version; uname -a; } > "$OUT/versions.txt" 2>&1
helm list -A -o yaml > "$OUT/helm-releases.yaml"
kubectl get nodes -o wide > "$OUT/nodes.txt"
kubectl get pods -A -o json | python3 -c '
import json,sys
d=json.load(sys.stdin)
rows=sorted({(p["metadata"]["namespace"],c["name"],c.get("image"),c.get("imageID")) for p in d["items"] for c in p["status"].get("containerStatuses",[])})
for r in rows: print("\t".join(map(str,r)))' > "$OUT/image-digests.tsv"
kubectl get storageclass,pvc -A > "$OUT/storage.txt"
cp "$HERE/config/versions.env" "$HERE/config/endpoints.env" "$OUT/"

check() {
  if curl -fsS -m 10 -o /dev/null "$2"; then echo "PASS $1 $2"; else echo "FAIL $1 $2"; fail=1; fi
}
{
  check frontend "$SENTRIX_FRONTEND_URL/"
  check prometheus "$SENTRIX_PROMETHEUS_URL/-/ready"
  check tempo "$SENTRIX_TEMPO_URL/ready"
  check loki "$SENTRIX_LOKI_URL/loki/api/v1/labels"
} | tee "$OUT/endpoints.txt"
grep -q FAIL "$OUT/endpoints.txt" && fail=1

# Required Prometheus series for feature-schema.yaml (empty result = missing).
for q in 'container_cpu_usage_seconds_total{namespace="sentrix"}' \
         'container_cpu_cfs_throttled_seconds_total{namespace="sentrix"}' \
         'container_cpu_cfs_periods_total{namespace="sentrix"}' \
         'kube_pod_container_status_ready{namespace="sentrix"}' \
         'kube_pod_container_status_restarts_total{namespace="sentrix"}' \
         'kube_pod_container_resource_limits{namespace="sentrix",resource="cpu"}' \
         'traces_span_metrics_calls_total' \
         'container_network_transmit_packets_dropped_total{namespace="sentrix"}'; do
  n=$(curl -fsS -m 10 -G "$SENTRIX_PROMETHEUS_URL/api/v1/query" --data-urlencode "query=count($q)" \
      | python3 -c 'import json,sys; r=json.load(sys.stdin)["data"]["result"]; print(r[0]["value"][1] if r else 0)' 2>/dev/null || echo ERR)
  if [ "$n" = "0" ] || [ "$n" = "ERR" ]; then echo "FAIL series $q -> $n"; fail=1; else echo "PASS series $q -> $n"; fi
done | tee "$OUT/series.txt"
grep -q FAIL "$OUT/series.txt" && fail=1

# Scrape interval actually in force (feature-schema: 5 s).
curl -fsS -m 10 "$SENTRIX_PROMETHEUS_URL/api/v1/status/config" | grep -m3 -E 'scrape_interval' > "$OUT/scrape-interval.txt" || true
echo "Wrote $OUT"
exit $fail
