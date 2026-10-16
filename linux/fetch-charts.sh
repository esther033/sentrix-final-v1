#!/usr/bin/env bash
# Download the pinned Helm charts (config/versions.env) into linux/charts/ and
# verify each tgz against the digest in its repository index.yaml. No sudo.
# Why: on 206-40, GitHub release assets took 90-260 s before the first byte,
# so `helm pull` / `helm upgrade --install` from the repo hit helm's 30 s HTTP
# timeout repeatedly. 04-deploy-stack.sh installs from linux/charts/ when the
# tgz is present. Existing verified files are kept; a digest mismatch stops.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
. "$HERE/config/versions.env"
DEST="$HERE/charts"; mkdir -p "$DEST/index"
PY="$ROOT/.venv/bin/python"; [ -x "$PY" ] || PY=python3
CURL=(curl -fsSL --retry 5 --retry-delay 10 --retry-all-errors --connect-timeout 60 --max-time 900 ${CURL_EXTRA:-})

repo_url() {
  case "$1" in
    grafana) echo https://grafana.github.io/helm-charts ;;
    prometheus-community) echo https://prometheus-community.github.io/helm-charts ;;
    open-telemetry) echo https://open-telemetry.github.io/opentelemetry-helm-charts ;;
    chaos-mesh) echo https://charts.chaos-mesh.org ;;
    *) echo "unknown repo $1" >&2; return 1 ;;
  esac
}

fail=0
for spec in "$CHART_LOKI" "$CHART_TEMPO" "$CHART_PROMETHEUS" "$CHART_OTEL" "$CHART_CHAOS_MESH"; do
  ref="${spec%%:*}"; ver="${spec##*:}"; repo="${ref%%/*}"; name="${ref#*/}"
  base="$(repo_url "$repo")"; index="$DEST/index/$repo-index.yaml"
  if [ ! -s "$index" ]; then
    echo "== index $repo"; "${CURL[@]}" -o "$index.tmp" "$base/index.yaml"; mv "$index.tmp" "$index"
  fi
  read -r url digest < <("$PY" - "$index" "$name" "$ver" "$base" <<'EOF'
import sys, urllib.parse, yaml
index, name, ver, base = sys.argv[1:]
entry = next(e for e in yaml.safe_load(open(index))["entries"][name] if e["version"] == ver)
print(urllib.parse.urljoin(base + "/", entry["urls"][0]), entry["digest"])
EOF
)
  out="$DEST/$name-$ver.tgz"
  if [ ! -s "$out" ]; then
    echo "== $name $ver <- $url"
    start=$SECONDS
    "${CURL[@]}" -o "$out.tmp" "$url"
    mv "$out.tmp" "$out"
    echo "   downloaded in $((SECONDS-start)) s"
  fi
  have="$(sha256sum "$out" | cut -d' ' -f1)"
  if [ "$have" = "$digest" ]; then echo "MATCH $name-$ver.tgz $have";
  else echo "MISMATCH $name-$ver.tgz have=$have index=$digest" >&2; fail=1; fi
done
exit $fail
