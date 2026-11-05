#!/usr/bin/env bash
# Fails when tracked files plus the .git object store exceed LIMIT_MB (default 2000).
# Excludes .venv and other untracked build artefacts on purpose.
#
# The limit was raised from 800 to 2000 MB on 2026-09-14 (owner's decision, work order 6
# follow-up). The size is almost entirely .git history, not the working tree (tracked ~50 MB,
# .git ~860 MB): every hourly bot commit rewrites ~300 processed and archive parquet files, so
# the pack grows ~30 MB/day and raising the ceiling only defers the wall, it does not remove it.
# The durable fix is to stop versioning the derived parquet churn (squash the data history onto
# a fresh branch, or move data/processed and data/archive out of git into a release/branch/LFS
# store). GitHub tolerates repos to roughly 5 GB before it intervenes, so 2000 MB keeps the
# guardrail meaningful while buying about a month at the current rate.
set -euo pipefail
# sync-agent duplicate copies ("name 2.ext") must not be tracked
if git ls-files | grep -E " [0-9]\.[A-Za-z0-9]+$" | head -1 | grep -q .; then
  echo "::error::tracked files that look like sync duplicates ('name 2.ext'); delete them" >&2
  git ls-files | grep -E " [0-9]\.[A-Za-z0-9]+$" | head -20 >&2
  exit 1
fi
LIMIT_MB="${LIMIT_MB:-2000}"
# MarketMonitoring (2026-11-05): the jobs check out a shallow clone of a repository shared with the
# portfolio, so a local .git measures nothing; GitHub's own figure for the whole repository is used
# when a token is available (it is what GitHub's limits are applied to), the local one otherwise.
API_KB=""
if [ -n "${GH_TOKEN:-}" ] && [ -n "${GITHUB_REPOSITORY:-}" ] && command -v gh >/dev/null; then
  API_KB=$(gh api "repos/$GITHUB_REPOSITORY" --jq .size 2>/dev/null || true)
fi
if [ -n "$API_KB" ]; then
  SIZE_MB=$(( API_KB / 1024 ))
  echo "repository size (GitHub, all branches and history): ${SIZE_MB} MB (limit ${LIMIT_MB} MB)"
else
  top=$(git rev-parse --show-toplevel)
  TRACKED_KB=$(git -C "$top" ls-files -z | (cd "$top" && xargs -0 du -ck 2>/dev/null) | tail -1 | cut -f1)
  GIT_KB=$(du -sk "$(git rev-parse --git-dir)" | cut -f1)
  SIZE_MB=$(( (TRACKED_KB + GIT_KB) / 1024 ))
  echo "tracked files: $((TRACKED_KB/1024)) MB, .git: $((GIT_KB/1024)) MB, total: ${SIZE_MB} MB (limit ${LIMIT_MB} MB)"
fi
if [ "$SIZE_MB" -gt "$LIMIT_MB" ]; then
  echo "::error::Repository exceeds ${LIMIT_MB} MB (mostly .git history from parquet churn, not raw files). The crypto monitor's generated data lives on crypto-state and its raw archive in releases; look for a new source of churn on main (crypto/docs/runbook.md, 'Repository size')." >&2
  exit 1
fi
