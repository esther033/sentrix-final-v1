#!/usr/bin/env bash
# Read-only host check for a (possibly shared) school Linux machine.
# Installs nothing and needs no sudo. Writes linux/out/preflight-<host>-<utc>/
# and prints PASS/WARN/FAIL lines. Run this FIRST and share summary.txt
# before deciding whether this machine can host the campaign.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$HERE/out/preflight-$(hostname -s)-$TS"
mkdir -p "$OUT"
SUMMARY="$OUT/summary.txt"
: > "$SUMMARY"
say() { echo "$1 $2" | tee -a "$SUMMARY"; }
cap() { local name="$1"; shift; { echo "\$ $*"; "$@" 2>&1; } > "$OUT/$name.txt" || true; }

cap os-release cat /etc/os-release
cap uname uname -a
cap lscpu lscpu
cap meminfo cat /proc/meminfo
cap df df -hT
cap ip-addr ip -brief addr
cap timedatectl timedatectl
cap loginctl loginctl show-user "$USER"
cap cgroup stat -fc %T /sys/fs/cgroup
cap swaps cat /proc/swaps
cap ss ss -ltnp
cap env-proxy sh -c 'env | grep -i _proxy || true'

. /etc/os-release 2>/dev/null || true
case "${ID:-}" in
  ubuntu) say PASS "OS ${PRETTY_NAME:-ubuntu}" ;;
  *) say WARN "OS ${PRETTY_NAME:-unknown}: scripts target Ubuntu 22.04/24.04" ;;
esac

CPUS=$(nproc)
if [ "$CPUS" -ge 12 ]; then say PASS "CPU $CPUS vCPU";
elif [ "$CPUS" -ge 8 ]; then say WARN "CPU $CPUS vCPU: enough for capability/pilot; full 138-run campaign competes with telemetry";
else say FAIL "CPU $CPUS vCPU: below 8, run capability checks only"; fi

MEM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)
if [ "$MEM_GB" -ge 30 ]; then say PASS "RAM ${MEM_GB} GiB";
elif [ "$MEM_GB" -ge 15 ]; then say WARN "RAM ${MEM_GB} GiB: pilot OK, full campaign tight (design assumed 64 GiB)";
else say FAIL "RAM ${MEM_GB} GiB: Online Boutique + Tempo/Loki/Prometheus will OOM"; fi

FREE_GB=$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc 0-9)
# Legacy cohort: 27.56 GiB for 28 runs (~1 GiB/run). 138 runs ~ 140 GiB + backends.
if [ "$FREE_GB" -ge 250 ]; then say PASS "disk free ${FREE_GB} GiB at $ROOT";
elif [ "$FREE_GB" -ge 60 ]; then say WARN "disk free ${FREE_GB} GiB: pilot OK; full campaign needs ~150-250 GiB (archive runs off-host)";
else say FAIL "disk free ${FREE_GB} GiB"; fi
# k3s keeps images, containerd state and local-path PVCs (Prometheus/Tempo/
# Loki, ~65 GiB) under /var/lib/rancher, which is often a different, smaller
# filesystem than the repo (205-13: /var had 14 GiB while /home had plenty).
K3S_DATA=/var/lib/rancher; [ -d "$K3S_DATA" ] || K3S_DATA=/var
K3S_FREE_GB=$(df -BG --output=avail "$K3S_DATA" | tail -1 | tr -dc 0-9)
K3S_FS=$(df --output=source "$K3S_DATA" | tail -1); ROOT_FS=$(df --output=source "$ROOT" | tail -1)
[ "$K3S_FS" = "$ROOT_FS" ] && SHARED=" (same filesystem as repo: runs/ and k3s share this space)" || SHARED=""
if [ "$K3S_FREE_GB" -ge 100 ]; then say PASS "k3s data disk free ${K3S_FREE_GB} GiB at $K3S_DATA$SHARED";
elif [ "$K3S_FREE_GB" -ge 40 ]; then say WARN "k3s data disk free ${K3S_FREE_GB} GiB at $K3S_DATA: images + PVCs need ~80 GiB; consider k3s --data-dir on a larger local disk$SHARED";
else say FAIL "k3s data disk free ${K3S_FREE_GB} GiB at $K3S_DATA: move k3s data (--data-dir) and local-path storage to a larger local disk$SHARED"; fi
FS_TYPE=$(df -T "$ROOT" | awk 'NR==2 {print $2}')
case "$FS_TYPE" in nfs*|cifs|smb*|fuse*) say WARN "repo on $FS_TYPE (network home?): file locks/fsync may be slow or unsupported; prefer a local disk path" ;; esac

# `sudo -l -n` also fails when a password is required, so it cannot tell
# "needs password" from "not allowed". Group membership (sudo/admin/wheel) is
# the read-only signal; whether the password works is checked with `sudo -v`.
if ! command -v sudo >/dev/null; then say FAIL "no sudo binary: ask the lab admin (see linux/README.md 'admin request')";
elif sudo -n true 2>/dev/null; then say PASS "passwordless sudo available";
elif id -nG | tr ' ' '\n' | grep -qxE 'sudo|admin|wheel'; then say WARN "sudo needs password (member of $(id -nG | tr ' ' '\n' | grep -xE 'sudo|admin|wheel' | head -1)): run sudo steps interactively; verify with 'sudo -v'";
elif sudo -n -l 2>&1 | grep -qi 'password is required'; then say WARN "sudo needs password (sudoers entry, no admin group): verify with 'sudo -v'";
else say FAIL "no sudo: k3s/containerd cannot be installed; ask the lab admin (see linux/README.md 'admin request')"; fi

CG=$(stat -fc %T /sys/fs/cgroup 2>/dev/null)
if [ "$CG" = "cgroup2fs" ]; then say PASS "cgroup v2"; else say WARN "cgroup $CG: CPU probe reads cgroup v2 cpu.stat; adjust if v1"; fi

if [ -e "/lib/modules/$(uname -r)/kernel/net/sched/sch_netem.ko" ] || ls /lib/modules/"$(uname -r)"/kernel/net/sched/sch_netem.ko* >/dev/null 2>&1 || grep -q sch_netem /proc/modules 2>/dev/null; then
  say PASS "sch_netem module present (network delay/loss possible)"
else
  say FAIL "sch_netem not found for kernel $(uname -r): NetworkChaos delay/loss will not work (install linux-modules-extra-$(uname -r))"
fi

if [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = "yes" ]; then say PASS "NTP synchronized";
else say WARN "NTP not confirmed: label timestamps need <100 ms clock error"; fi
# Dual boot: Windows writes local time to the RTC. With LocalRTC=no Linux
# reads it as UTC, so right after a boot the clock is off by the UTC offset
# (+9 h in KST) until NTP corrects it. run-attended.py refuses to start a run
# until NTPSynchronized=yes.
LOCAL_RTC=$(timedatectl show -p LocalRTC --value 2>/dev/null || echo unknown)
if ls /dev/disk/by-label 2>/dev/null | grep -qiE '^(SYSTEM|Windows|OS)$' || lsblk -no FSTYPE 2>/dev/null | grep -qx ntfs; then DUAL=yes; else DUAL=no; fi
say INFO "RTC in local TZ=$LOCAL_RTC, NTP synchronized=$(timedatectl show -p NTPSynchronized --value 2>/dev/null || echo unknown), NTFS/Windows partition present=$DUAL"
if [ "$DUAL" = yes ] && [ "$LOCAL_RTC" = no ]; then
  say WARN "dual boot with RTC in UTC: after a Windows session the clock can be off by the UTC offset until NTP syncs; wait for NTPSynchronized=yes before starting any run"
fi
LAST_BOOTS=$(last -x reboot 2>/dev/null | grep -c '^reboot' || true)
say INFO "reboots recorded in wtmp: $LAST_BOOTS ($(last -x reboot 2>/dev/null | tail -1 | sed 's/^wtmp begins //'))"

if awk 'NR>1 {found=1} END {exit !found}' /proc/swaps; then say WARN "swap enabled: kubelet may refuse to start; 01-install-k3s.sh passes --kubelet-arg=fail-swap-on=false"; fi

LINGER=$(loginctl show-user "$USER" -p Linger --value 2>/dev/null || echo unknown)
if [ "$LINGER" = "yes" ]; then say PASS "systemd linger on (user processes survive logout)";
else say WARN "linger=$LINGER: a logout may kill the campaign; use tmux (campaign/start.sh) and ask admin for 'loginctl enable-linger $USER'"; fi

UPTIME_D=$(awk '{printf "%d", $1/86400}' /proc/uptime)
say INFO "uptime ${UPTIME_D} days (lab machines that reboot nightly cannot run multi-day queues)"

for port in 6443 30080 30090 30310 30320; do
  if ss -ltn "( sport = :$port )" | grep -q LISTEN; then say WARN "port $port already in use"; fi
done
if command -v docker >/dev/null; then say INFO "docker present ($(docker --version 2>/dev/null))"; fi
if command -v kubectl >/dev/null && kubectl version --request-timeout=5s >/dev/null 2>&1; then
  say WARN "an existing Kubernetes cluster is reachable: decide whether to reuse it (record context) or install k3s"
fi

for url in https://get.k3s.io https://ghcr.io https://registry-1.docker.io/v2/ https://github.com https://charts.chaos-mesh.org https://zenodo.org; do
  # Judge by curl's exit status: on failure curl still prints http_code "000",
  # and the old `|| echo 000` appended another 000 ("000000"), which passed.
  code=$(curl -s -o /dev/null -m 15 -w '%{http_code}' "$url"); rc=$?
  if [ "$rc" -ne 0 ]; then say FAIL "cannot reach $url (curl exit $rc; proxy/firewall/DNS?)"; else say PASS "reach $url ($code)"; fi
done

for c in python3 git curl tmux tar jq; do
  if command -v "$c" >/dev/null; then say PASS "tool $c"; else say WARN "missing $c"; fi
done
PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo none)
case "$PYV" in 3.1[0-3]) say PASS "python $PYV" ;; *) say WARN "python $PYV: need 3.10-3.13" ;; esac
# `import venv` succeeds without the python3-venv package; `python3 -m venv`
# then fails because ensurepip is missing (206-40), so check ensurepip.
python3 -c 'import venv, ensurepip' 2>/dev/null || say WARN "python3-venv missing: 03-python-env.sh cannot create .venv (sudo apt install python3-venv)"

echo
echo "Wrote $OUT"
grep -c '^FAIL' "$SUMMARY" | xargs -I{} echo "{} FAIL line(s)"
