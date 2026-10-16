#!/usr/bin/env bash
# Deploy observability backends, Chaos Mesh and Online Boutique on k3s.
# Base values are the legacy files in deploy/; Linux overlays in linux/values/
# override only what differs (socket, retention, PVC, limits). Idempotent:
# helm upgrade --install, kubectl apply. Re-run after any helm upgrade, since
# the NodePort patches at the end are not part of the charts.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
. "$HERE/config/versions.env"
export PATH="$HOME/.local/bin:$PATH"
cd "$ROOT"

chart() { echo "${1%%:*}"; }
ver() { echo "${1##*:}"; }

helm repo add grafana https://grafana.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts >/dev/null 2>&1 || true
helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null 2>&1 || true
helm repo update >/dev/null

kubectl apply -f deploy/namespace.yaml

install() { # release chart:version namespace values...
  local rel="$1" spec="$2" ns="$3"; shift 3
  local args=()
  for v in "$@"; do args+=(-f "$v"); done
  echo "== $rel ($spec) in $ns"
  helm upgrade --install "$rel" "$(chart "$spec")" --version "$(ver "$spec")" -n "$ns" --create-namespace "${args[@]}" --wait --timeout 15m
}

install loki "$CHART_LOKI" sentrix deploy/loki/values-minimal.yaml linux/values/loki-linux.yaml
install tempo "$CHART_TEMPO" sentrix deploy/tempo/values-minimal.yaml linux/values/tempo-linux.yaml
install prometheus "$CHART_PROMETHEUS" sentrix deploy/prometheus/values-minimal.yaml linux/values/prometheus-linux.yaml
install otel-gateway "$CHART_OTEL" sentrix deploy/otel-collector/gateway-values.yaml
install otel-daemonset "$CHART_OTEL" sentrix deploy/otel-collector/daemonset-values.yaml
install chaos-mesh "$CHART_CHAOS_MESH" chaos-mesh deploy/chaos-mesh/values-minimal.yaml linux/values/chaos-mesh-k3s.yaml

kubectl apply -k deploy/linux/online-boutique
kubectl -n sentrix rollout status deploy --timeout=15m

# Fixed NodePorts (see linux/config/endpoints.env). Strategic merge on `port`.
kubectl -n sentrix patch svc prometheus-server -p '{"spec":{"type":"NodePort","ports":[{"port":80,"nodePort":30090}]}}'
kubectl -n sentrix patch svc tempo -p '{"spec":{"type":"NodePort","ports":[{"port":3200,"nodePort":30320}]}}'
kubectl -n sentrix patch svc loki-gateway -p '{"spec":{"type":"NodePort","ports":[{"port":80,"nodePort":30310}]}}'

kubectl -n sentrix get deploy loadgenerator -o jsonpath='{.spec.replicas}' | grep -qx 0 \
  || { echo "built-in loadgenerator is not at 0 replicas" >&2; exit 1; }
kubectl get pods -A -o wide
echo "Next: linux/05-verify.sh"
