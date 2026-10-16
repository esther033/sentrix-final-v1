#!/usr/bin/env bash
# Graceful stop: the queue finishes the pair in progress (including export and
# fault removal) and exits before starting the next one. Remove the file to
# allow the next start.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CAMPAIGN="${1:-linux-v1}"
mkdir -p "$ROOT/runs/_campaign/$CAMPAIGN"
date -u +%FT%TZ > "$ROOT/runs/_campaign/$CAMPAIGN/STOP"
echo "STOP requested for $CAMPAIGN; delete runs/_campaign/$CAMPAIGN/STOP before restarting."
