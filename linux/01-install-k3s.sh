#!/usr/bin/env bash
# Single-node k3s (containerd) for the linux-v1 cohort. Needs sudo.
# - pinned K3S_VERSION from config/versions.env
# - traefik and servicelb disabled (frontend-external must not grab host :80;
#   services are exposed as fixed NodePorts by 04-deploy-stack.sh)
# - sch_netem loaded now and at boot (NetworkChaos delay/loss)
# - inotify limits raised (OTel filelog + many pods)
# - node name = the PC's environment ID when one is set (SENTRIX_ENVIRONMENT_ID
#   or linux/config/local.env), else k3s's default (the hostname)
# Re-running is safe: an existing k3s of the same version is left alone.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/config/versions.env"
if [ -z "${SENTRIX_ENVIRONMENT_ID:-}" ] && [ -f "$HERE/config/local.env" ]; then
  SENTRIX_ENVIRONMENT_ID="$(sed -n 's/^[[:space:]]*\(export[[:space:]]\+\)\?SENTRIX_ENVIRONMENT_ID=["'"'"']\?\([^"'"'"' ]*\).*/\2/p' "$HERE/config/local.env" | tail -1)"
fi
if [ -n "${SENTRIX_ENVIRONMENT_ID:-}" ]; then
  SENTRIX_ENVIRONMENT_ID="$SENTRIX_ENVIRONMENT_ID" python3 "$HERE/../scripts/host_state.py" >/dev/null || exit 1   # same validation as run records
fi

if command -v k3s >/dev/null 2>&1; then
  have="$(k3s --version | awk 'NR==1 {print $3}')"
  if [ "$have" = "$K3S_VERSION" ]; then echo "k3s $have already installed"; else
    echo "k3s $have installed but $K3S_VERSION pinned. Not changing it automatically." >&2
    echo "Either set K3S_VERSION=$have in config/versions.env (and record why) or uninstall k3s first." >&2
    exit 1
  fi
else
  EXTRA=""
  if awk 'NR>1 {found=1} END {exit !found}' /proc/swaps; then EXTRA="--kubelet-arg=fail-swap-on=false"; fi
  if [ -n "${SENTRIX_ENVIRONMENT_ID:-}" ]; then EXTRA="$EXTRA --node-name $SENTRIX_ENVIRONMENT_ID"; fi
  curl -sfL https://get.k3s.io | sudo env INSTALL_K3S_VERSION="$K3S_VERSION" \
    INSTALL_K3S_EXEC="server --disable traefik --disable servicelb --write-kubeconfig-mode 600 $EXTRA" sh -
fi

sudo modprobe sch_netem
echo sch_netem | sudo tee /etc/modules-load.d/sentrix-netem.conf >/dev/null
sudo tee /etc/sysctl.d/90-sentrix.conf >/dev/null <<'EOF'
fs.inotify.max_user_instances = 1024
fs.inotify.max_user_watches = 1048576
EOF
sudo sysctl --system >/dev/null

mkdir -p "$HOME/.kube"
sudo cat /etc/rancher/k3s/k3s.yaml > "$HOME/.kube/config.k3s.tmp"
chmod 600 "$HOME/.kube/config.k3s.tmp"
if [ -f "$HOME/.kube/config" ] && ! cmp -s "$HOME/.kube/config" "$HOME/.kube/config.k3s.tmp"; then
  cp "$HOME/.kube/config" "$HOME/.kube/config.backup-$(date -u +%Y%m%dT%H%M%SZ)"
fi
mv "$HOME/.kube/config.k3s.tmp" "$HOME/.kube/config"

# kubectl ships inside k3s; expose it without sudo. A plain symlink is not
# enough: k3s's kubectl ignores ~/.kube/config and reads the root-only
# /etc/rancher/k3s/k3s.yaml whenever KUBECONFIG is unset (206-40), so the
# wrapper supplies the same default as config/versions.env. rm first: writing
# through an old symlink would target the root-owned k3s binary.
mkdir -p "$HOME/.local/bin"
rm -f "$HOME/.local/bin/kubectl"
printf '#!/bin/sh\nexport KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"\nexec %s kubectl "$@"\n' \
  "$(command -v k3s)" > "$HOME/.local/bin/kubectl"
chmod 755 "$HOME/.local/bin/kubectl"

echo "Waiting for the node to be Ready..."
"$HOME/.local/bin/kubectl" wait --for=condition=Ready node --all --timeout=180s
"$HOME/.local/bin/kubectl" get nodes -o wide
if [ -n "${SENTRIX_ENVIRONMENT_ID:-}" ] && ! "$HOME/.local/bin/kubectl" get node "$SENTRIX_ENVIRONMENT_ID" >/dev/null 2>&1; then
  echo "WARNING: no k3s node named $SENTRIX_ENVIRONMENT_ID (k3s was installed before the ID was set?)" >&2
fi
echo "containerd socket for Chaos Mesh: /run/k3s/containerd/containerd.sock"
sudo test -S /run/k3s/containerd/containerd.sock && echo "  present" || { echo "  MISSING: fix linux/values/chaos-mesh-k3s.yaml socketPath" >&2; exit 1; }
