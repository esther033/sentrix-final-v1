#!/usr/bin/env bash
# Start the campaign queue in a detached tmux session so it survives SSH /
# desktop logout (still NOT a reboot: after a reboot, run this again and the
# queue resumes at the first incomplete pair).
#   linux/campaign/start.sh                      # formal campaign (frozen schedule)
#   linux/campaign/start.sh --max-pairs 1        # one pair, then stop
#   linux/campaign/start.sh --only <pair-id> --allow-draft   # rehearsal
#   linux/campaign/start.sh --shard campaigns/linux-v1/shards/<ID>.json   # parallel collection
# The PC's environment ID (SENTRIX_ENVIRONMENT_ID > linux/config/local.env >
# hostname) is resolved here and exported into the session, so run-campaign's
# shard check and every run record use the same ID.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_ID="$(python3 "$ROOT/scripts/host_state.py")" || exit 1
SESSION="${SENTRIX_TMUX_SESSION:-sentrix-campaign}"
if tmux has-session -t "$SESSION" 2>/dev/null; then
  echo "tmux session $SESSION already running: tmux attach -t $SESSION"; exit 1
fi
ARGS="$(printf '%q ' "$@")"
tmux new-session -d -s "$SESSION" -c "$ROOT" \
  "set -a; . linux/config/endpoints.env; set +a; export SENTRIX_ENVIRONMENT_ID=$ENV_ID; export PATH=\$HOME/.local/bin:\$PATH; \
   .venv/bin/python -B scripts/run-campaign.py $ARGS 2>&1 | tee -a runs/campaign-console.log; \
   echo 'queue exited; press enter'; read"
echo "environment id: $ENV_ID"
echo "started: tmux attach -t $SESSION   (detach: Ctrl-b d)"
echo "graceful stop after current pair: linux/campaign/stop.sh"
