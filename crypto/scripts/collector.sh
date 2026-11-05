#!/usr/bin/env bash
# Mode (b) collector (build prompt §3.2; work orders 6/7): fetch the raw envelopes that
# GitHub-hosted runners cannot get (Binance and Bybit answer 451/403 from US runner IPs — see
# docs/data_sources.md "Runner reachability") and push ONLY those raw files. The runner's
# hourly/daily job parses them on its next run. The collector deliberately does NOT compute or
# push any processed table: two jobs writing the same tables conflicted on 2026-09-10.
#
# MarketMonitoring (2026-11-05): the raw files go to the append-only branch `crypto-collector`
# (crypto/data/raw/...), never to main; `scripts/state.sh restore` merges them into each runner
# job. The commit is built in a separate index on top of origin/crypto-collector, so the clone's
# checkout of main is never touched and there is no rebase to stall on.
#
# Usage:  crypto/scripts/collector.sh hourly     (launchd :09)
#         crypto/scripts/collector.sh daily      (launchd 01:45 local)
# Requires: uv, a clone of MarketMonitoring with push rights, crypto/.env with keys.
set -euo pipefail
JOB="${1:-hourly}"
BR="${COLLECTOR_BRANCH:-crypto-collector}"
cd "$(dirname "$0")/.."                      # crypto/
top=$(git rev-parse --show-toplevel)
export PYTHONPATH="$PWD/src"
set -a; [ -f .env ] && . ./.env; set +a

find data site/data -name '* [0-9].*' -delete 2>/dev/null || true   # sync-agent duplicate copies
git -C "$top" pull -q --ff-only origin main || echo "collector $JOB: main not fast-forwardable; running the checked-out code" >&2

# fetch writes raw envelopes under data/raw; ignore a non-zero exit (per-dataset failures are
# isolated) so one blocked venue does not stop the push of the others
uv run --no-sync monitor fetch "$JOB" || echo "collector $JOB: fetch returned non-zero (per-dataset isolation)" >&2

# ONLY the raw envelopes the runners cannot fetch, newer than this run's start minus a day
mapfile -t files < <(find data/raw -type f -name '*.json.gz' -mtime -1 | grep -E '/(binance|bybit)_|liquidations_ws' || true)
[ "${#files[@]}" -gt 0 ] || { echo "collector $JOB: nothing to push"; exit 0; }
uv run --no-sync python scripts/check_write_set.py collector --files "${files[@]}"

export GIT_AUTHOR_NAME=crypto-monitor-bot GIT_AUTHOR_EMAIL=crypto-monitor-bot@users.noreply.github.com
export GIT_COMMITTER_NAME=$GIT_AUTHOR_NAME GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL
for attempt in 1 2 3; do
  idx=$(mktemp); rm -f "$idx"
  parent=""
  if git -C "$top" fetch -q origin "+refs/heads/$BR:refs/crypto-state/collector-base" 2>/dev/null; then
    parent=$(git -C "$top" rev-parse refs/crypto-state/collector-base)
    GIT_INDEX_FILE="$idx" git -C "$top" read-tree "$parent"
  fi
  (cd "$top" && GIT_INDEX_FILE="$idx" git add -f -- "${files[@]/#/crypto/}")
  tree=$(GIT_INDEX_FILE="$idx" git -C "$top" write-tree); rm -f "$idx"
  if [ -n "$parent" ] && [ "$(git -C "$top" rev-parse "$parent^{tree}")" = "$tree" ]; then
    echo "collector $JOB: already pushed"; exit 0
  fi
  commit=$(git -C "$top" commit-tree "$tree" ${parent:+-p "$parent"} -m "collector raw $JOB $(date -u +%Y-%m-%dT%H:%MZ)")
  if git -C "$top" push -q origin "$commit:refs/heads/$BR"; then
    echo "collector $JOB done $(date -u +%FT%TZ): ${#files[@]} raw file(s) on $BR"; exit 0
  fi
  echo "collector $JOB: push rejected (attempt $attempt), refetching" >&2
done
exit 1
