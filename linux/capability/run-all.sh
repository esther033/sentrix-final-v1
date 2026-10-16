#!/usr/bin/env bash
# All three capability gates into one evidence directory. Any FAIL blocks the
# campaign (LINUX-DATA-COLLECTION-PLAN.md section 3).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(cd "$HERE/.." && pwd)/out/capability-$(date -u +%Y%m%dT%H%M%SZ)"
export OUT
rc=0
for t in cpu pod network; do
  echo "== $t"
  bash "$HERE/$t.sh" || { echo "FAIL $t"; rc=1; }
done
echo "evidence: $OUT"
echo "Remove probes when done: kubectl delete ns sentrix-probe"
exit $rc
