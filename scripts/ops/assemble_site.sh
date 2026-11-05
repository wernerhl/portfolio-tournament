#!/usr/bin/env bash
# The ONE MarketMonitoring site (2026-11-05). Every workflow that deploys GitHub Pages — the
# portfolio nightly, intraday, intraday analytics and market open, and the crypto hourly, daily
# and weekly — builds the same tree with this script, so whichever deploy runs last publishes the
# latest of both projects and a deploy cancelled in the shared `pages-deploy` queue loses nothing:
#
#   /            the portfolio tournament and screener (the repository root, as served before,
#                minus research/ (F5, 7-Oct-2026), crypto/ and the git metadata)
#   /crypto/     the crypto monitor, rendered by its own jobs onto the crypto-state branch
#
# Usage: bash scripts/ops/assemble_site.sh [out_dir=_site]   (run from a checkout of main)
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
out="${1:-_site}"
rm -rf "$out"
mkdir -p "$out"
# tar, not rsync: nothing beyond coreutils and git is assumed on the runner
tar -c --exclude='./.git' --exclude='./.github' --exclude='./research' --exclude='./crypto' \
  --exclude="./${out#./}" --exclude='./node_modules' -f - . | tar -x -C "$out"
mkdir -p "$out/crypto"
if git fetch -q --depth=1 origin "+refs/heads/crypto-state:refs/crypto-state/site" 2>/dev/null \
   && git cat-file -e refs/crypto-state/site:crypto/site 2>/dev/null; then
  tmp=$(mktemp -d)
  git archive refs/crypto-state/site crypto/site | tar -x -C "$tmp"
  cp -a "$tmp/crypto/site/." "$out/crypto/"
  rm -rf "$tmp"
  echo "assembled: portfolio + crypto (crypto-state $(git rev-parse --short refs/crypto-state/site))"
else
  cat > "$out/crypto/index.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>Crypto monitor</title>
<body style="background:#0f0e0c;color:#efe8d8;font:16px/1.5 Georgia,serif;max-width:640px;margin:10vh auto;padding:0 18px">
<p><a href="../index.html" style="color:#e5b85a">← Market monitoring</a></p>
<h1>Crypto monitor</h1><p>No crypto snapshot has been published yet: the crypto jobs have not run in this repository.</p></body>
HTML
  echo "assembled: portfolio + crypto placeholder (no crypto-state branch yet)"
fi
[ -f "$out/index.html" ] || { echo "::error::assembled site has no index.html"; exit 1; }
echo "site size: $(du -sh "$out" | cut -f1)"
