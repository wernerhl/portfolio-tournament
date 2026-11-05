#!/usr/bin/env bash
# The crypto monitor's generated files live on the orphan branch `crypto-state`, never on main
# (MarketMonitoring, 2026-11-05). In crypto-monitor every hourly bot commit rewrote ~300 parquet
# files on main and the repository reached 6.8 GB of history; here each job replaces the branch
# with ONE parentless commit, so the generated data takes the space of a single snapshot.
#
#   state.sh restore        unpack the latest snapshot into crypto/data and crypto/site
#                           (plus raw envelopes the Mac collector pushed to `crypto-collector`)
#   state.sh save <job>     snapshot crypto/data and crypto/site, check the changed files against
#                           the job's write set (config/job_writes.yaml), and force-push with a lease
#                           on the snapshot the job restored: a concurrent writer is never overwritten
#
# Run from anywhere inside the repository. Needs `origin`; STATE_BRANCH overrides the branch name.
set -euo pipefail
top=$(git rev-parse --show-toplevel)
cd "$top"
BR="${STATE_BRANCH:-crypto-state}"
COLLECTOR_BR="${COLLECTOR_BRANCH:-crypto-collector}"
BASE_REF="refs/crypto-state/base"
PATHS=(crypto/data crypto/site)

restore() {
  if git fetch -q --depth=1 origin "+refs/heads/$BR:$BASE_REF" 2>/dev/null; then
    rm -rf "${PATHS[@]}"
    present=()   # a snapshot may lack one of the two trees (an empty site, a first save)
    for p in "${PATHS[@]}"; do git cat-file -e "$BASE_REF:$p" 2>/dev/null && present+=("$p"); done
    [ "${#present[@]}" -gt 0 ] && git archive "$BASE_REF" "${present[@]}" | tar -x
    echo "state: restored $(git rev-parse --short "$BASE_REF") ($(git log -1 --format=%s "$BASE_REF"))"
  else
    git update-ref -d "$BASE_REF" 2>/dev/null || true
    echo "state: no $BR branch yet; starting empty"
  fi
  mkdir -p crypto/data/raw crypto/data/processed crypto/data/archive crypto/site/data
  # raw envelopes from the Mac collector (append-only branch); existing files are never overwritten
  if git fetch -q --depth=1 origin "+refs/heads/$COLLECTOR_BR:refs/crypto-state/collector" 2>/dev/null; then
    n_before=$(find crypto/data/raw -type f | wc -l)
    if git cat-file -e refs/crypto-state/collector:crypto/data/raw 2>/dev/null; then
      git archive refs/crypto-state/collector crypto/data/raw | tar -x --skip-old-files
    fi
    echo "state: collector raw merged ($(( $(find crypto/data/raw -type f | wc -l) - n_before )) new files)"
  fi
}

save() {
  job="${1:?usage: state.sh save <job>}"
  export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-crypto-monitor-bot}" GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-crypto-monitor-bot@users.noreply.github.com}"
  export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"
  idx=$(mktemp); rm -f "$idx"
  # -f: both trees are ignored on main (crypto/.gitignore); the snapshot is built in its own index.
  # Only trees holding at least one file are added (git refuses a pathspec that matches nothing).
  present=()
  for p in "${PATHS[@]}"; do [ -n "$(find "$p" -type f -print -quit 2>/dev/null)" ] && present+=("$p"); done
  if [ "${#present[@]}" -eq 0 ]; then echo "state: nothing to save"; return 0; fi
  GIT_INDEX_FILE="$idx" git add -f -- "${present[@]}"
  tree=$(GIT_INDEX_FILE="$idx" git write-tree)
  rm -f "$idx"
  base=$(git rev-parse -q --verify "$BASE_REF" || true)
  if [ -n "$base" ] && [ "$(git rev-parse "$base^{tree}")" = "$tree" ]; then
    echo "state: no changes"; return 0
  fi
  # write-set check on what changed (generated html is the renderer's, outside the data contract)
  if [ -n "$base" ]; then
    changed=$(git diff --name-only "$base" "$tree" -- crypto | sed 's|^crypto/||' | grep -E '^(data/|site/data/|site/alerts\.xml$)' || true)
  else
    changed=$(git ls-tree -r --name-only "$tree" -- crypto | sed 's|^crypto/||' | grep -E '^(data/|site/data/|site/alerts\.xml$)' || true)
  fi
  if [ -n "$changed" ] && [ "${STATE_SKIP_WRITE_SET:-0}" != 1 ]; then
    # shellcheck disable=SC2086
    (cd crypto && ${STATE_PY:-uv run python} scripts/check_write_set.py "$job" --files $changed)
  fi
  commit=$(git commit-tree "$tree" -m "state: $job $(date -u +%Y-%m-%dT%H:%MZ)")
  # lease: the branch must still be the snapshot this job restored (or absent if it restored none)
  git push -q --force-with-lease="refs/heads/$BR:${base}" origin "$commit:refs/heads/$BR"
  git update-ref "$BASE_REF" "$commit"
  echo "state: saved $(git rev-parse --short "$commit") for $job ($(printf '%s\n' "$changed" | sed '/^$/d' | wc -l) changed files)"
}

case "${1:-}" in
  restore) restore ;;
  save) shift; save "$@" ;;
  *) echo "usage: state.sh restore | save <job>" >&2; exit 2 ;;
esac
