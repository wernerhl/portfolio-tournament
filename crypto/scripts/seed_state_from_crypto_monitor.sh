#!/usr/bin/env bash
# One-time cutover step (MarketMonitoring, 2026-11-05): copy the generated data of a crypto-monitor
# checkout — data/ and site/data, site/alerts.xml — into crypto/, render the pages, and push it as the
# first crypto-state snapshot (scripts/state.sh). Run from a clone of MarketMonitoring with push rights,
# against an up-to-date checkout of crypto-monitor's main, after crypto-monitor's schedules are stopped
# (otherwise its bots keep writing data that never reaches here).
#
#   bash crypto/scripts/seed_state_from_crypto_monitor.sh /path/to/crypto-monitor
#
# Refuses to overwrite an existing crypto-state branch unless SEED_FORCE=1.
set -euo pipefail
src="${1:?usage: seed_state_from_crypto_monitor.sh /path/to/crypto-monitor}"
src=$(cd "$src" && pwd)
[ -d "$src/data/processed" ] || { echo "$src does not look like a crypto-monitor checkout (no data/processed)" >&2; exit 1; }
cd "$(dirname "$0")/.."                      # crypto/
if git ls-remote --exit-code --heads origin crypto-state >/dev/null 2>&1 && [ "${SEED_FORCE:-0}" != 1 ]; then
  echo "crypto-state already exists on origin; set SEED_FORCE=1 to replace it" >&2; exit 1
fi
echo "seeding from $src at $(git -C "$src" log -1 --format='%h %cd %s' --date=iso)"
rm -rf data site
cp -a "$src/data" data
mkdir -p site
cp -a "$src/site/data" site/data
[ -f "$src/site/alerts.xml" ] && cp "$src/site/alerts.xml" site/
find data site -name '* [0-9].*' -delete 2>/dev/null || true   # sync-agent duplicate copies
if [ "${SEED_RENDER:-1}" = 1 ]; then
  GIT_SHA="$(git rev-parse HEAD)" PYTHONPATH="$PWD/src" uv run --no-sync monitor site render --no-meta
fi
# a parentless first snapshot: no base to lease on, and the seed is not any job's write set
git update-ref -d refs/crypto-state/base 2>/dev/null || true
if [ "${SEED_FORCE:-0}" = 1 ]; then
  base=$(git ls-remote --heads origin crypto-state | cut -f1)
  [ -n "$base" ] && git fetch -q --depth=1 origin "+refs/heads/crypto-state:refs/crypto-state/base"
fi
STATE_SKIP_WRITE_SET=1 bash scripts/state.sh save seed
echo "seeded: $(find data -type f | wc -l) data files, $(find site -type f | wc -l) site files"
