#!/usr/bin/env bash
# Install (or remove with `--remove`) the launchd agents that run the collector from this Mac:
# hourly at :09, daily at 01:45 local time, and the resident websocket liquidation collector (liq). Logs: ~/Library/Logs/marketmonitoring-crypto-*.log.
# MarketMonitoring (2026-11-05): run it from crypto/scripts of a MarketMonitoring clone; it also
# unloads the old crypto-monitor agents, which pushed to the retired crypto-monitor repository.
# Run it from the clone the agents should use. That clone must live OUTSIDE ~/Documents,
# ~/Desktop and ~/Downloads: macOS privacy protection (TCC) blocks launchd jobs from those
# folders ("Operation not permitted") unless bash is granted Full Disk Access. A separate
# clone such as ~/MarketMonitoring also keeps the sync agent's duplicate copies away from it.
set -euo pipefail
cd "$(dirname "$0")/.."
DEST="$HOME/Library/LaunchAgents"
mkdir -p "$DEST"
for job in hourly daily liq; do
  old="com.wernerhl.crypto-monitor.$job"   # the retired repository's agents
  launchctl bootout "gui/$(id -u)/$old" 2>/dev/null || true
  rm -f "$DEST/$old.plist"
  label="com.wernerhl.marketmonitoring.crypto.$job"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  if [ "${1:-}" = "--remove" ]; then rm -f "$DEST/$label.plist"; echo "removed $label"; continue; fi
  sed "s#/Users/whl/MarketMonitoring/crypto#$PWD#g" "scripts/launchd/$label.plist" > "$DEST/$label.plist"
  launchctl bootstrap "gui/$(id -u)" "$DEST/$label.plist"
  echo "installed $label"
done
launchctl list | grep -E 'marketmonitoring|crypto-monitor' || true
