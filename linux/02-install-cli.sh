#!/usr/bin/env bash
# helm and k6 as user-local binaries in ~/.local/bin (no sudo, no apt repos).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/config/versions.env"
BIN="$HOME/.local/bin"; mkdir -p "$BIN"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
case "$(uname -m)" in x86_64) ARCH=amd64 ;; aarch64|arm64) ARCH=arm64 ;; *) echo "unsupported arch" >&2; exit 1 ;; esac

if ! "$BIN/helm" version --short 2>/dev/null | grep -q "$HELM_VERSION"; then
  curl -fsSL -o "$TMP/helm.tgz" "https://get.helm.sh/helm-${HELM_VERSION}-linux-${ARCH}.tar.gz"
  curl -fsSL -o "$TMP/helm.tgz.sha256sum" "https://get.helm.sh/helm-${HELM_VERSION}-linux-${ARCH}.tar.gz.sha256sum"
  (cd "$TMP" && echo "$(cut -d' ' -f1 helm.tgz.sha256sum)  helm.tgz" | sha256sum -c -)
  tar -xzf "$TMP/helm.tgz" -C "$TMP"
  install -m 755 "$TMP/linux-${ARCH}/helm" "$BIN/helm"
fi

if ! "$BIN/k6" version 2>/dev/null | grep -q "${K6_VERSION}"; then
  curl -fsSL -o "$TMP/k6.tgz" "https://github.com/grafana/k6/releases/download/${K6_VERSION}/k6-${K6_VERSION}-linux-${ARCH}.tar.gz"
  tar -xzf "$TMP/k6.tgz" -C "$TMP"
  install -m 755 "$TMP/k6-${K6_VERSION}-linux-${ARCH}/k6" "$BIN/k6"
fi

case ":$PATH:" in *":$BIN:"*) ;; *) echo "Add to ~/.bashrc:  export PATH=\"$BIN:\$PATH\"" ;; esac
"$BIN/helm" version --short
"$BIN/k6" version
