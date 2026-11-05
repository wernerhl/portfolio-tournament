#!/usr/bin/env bash
# Move raw files older than the retention windows (hourly 10 d, daily 90 d) out of crypto/data/raw
# into monthly tar parts stored as GitHub RELEASE ASSETS (MarketMonitoring, 2026-11-05):
#   release  crypto-raw-YYYY-MM      assets  rot-YYYYMMDD-NN.tar, each at most MAX_PART_MB (default 90)
# Release assets do not count toward the repository's git size; in crypto-monitor the raw archive
# was a git branch, and one monthly tar per branch file passed GitHub's 100 MB limit (Nov 2026).
# A tar is never rewritten: every rotation adds new parts. Restore a month with
#   gh release download crypto-raw-YYYY-MM -D parts && for t in parts/*.tar; do tar -xf "$t" -C data/raw; done
# (the pre-2026-11 archive is the `data-archive` branch of the archived crypto-monitor repository).
#
# Failure-safe: if anything fails before every part is uploaded, all moved files are put back
# under data/raw, so the state snapshot never drops an unarchived file.
# Runs from crypto/ (the workflows' working directory). ROTATE_UPLOAD=0 builds the parts in
# ROTATE_OUT (default: a temp dir) without uploading — for tests and dry runs.
set -euo pipefail
HOURLY_KEEP="${HOURLY_KEEP_DAYS:-10}"
DAILY_KEEP="${DAILY_KEEP_DAYS:-90}"
MAX_PART_BYTES=$(( ${MAX_PART_MB:-90} * 1024 * 1024 ))
ROOT="data/raw"
UPLOAD="${ROTATE_UPLOAD:-1}"
[ -d "$ROOT" ] || exit 0
now=$(date -u +%s)
stamp=$(date -u +%Y%m%d)
tmp=$(mktemp -d)
out="${ROTATE_OUT:-$tmp/parts}"
mkdir -p "$out"
done_ok=0

restore() {
  if [ "$done_ok" != 1 ] && [ -d "$tmp/files" ]; then
    n=0
    for month in "$tmp"/files/*/; do
      [ -d "$month" ] || continue
      cp -a "$month/." "$ROOT/" && n=$((n + 1))
    done
    [ "$n" -gt 0 ] && echo "::warning::raw rotation did not complete; moved files were restored under $ROOT" >&2
  fi
  rm -rf "$tmp"
}
trap restore EXIT

moved=0
while IFS= read -r f; do
  rel=${f#"$ROOT"/}
  y=${rel%%/*}; rest=${rel#*/}; m=${rest%%/*}; rest=${rest#*/}; d=${rest%%/*}
  day=$(date -u -d "$y-$m-$d" +%s 2>/dev/null || date -u -j -f "%Y-%m-%d" "$y-$m-$d" +%s)
  age=$(( (now - day) / 86400 ))
  keep=$DAILY_KEEP
  case "$f" in *_0000.json.gz) ;; *) keep=$HOURLY_KEEP ;; esac
  if [ "$age" -gt "$keep" ]; then
    mkdir -p "$tmp/files/$y-$m/$y/$m/$d"
    mv "$f" "$tmp/files/$y-$m/$y/$m/$d/"
    moved=$((moved + 1))
  fi
done < <(find "$ROOT" -type f -name '*.json.gz')
echo "raw files to rotate: $moved"
if [ "$moved" -eq 0 ]; then done_ok=1; exit 0; fi

# split each month into parts whose size (tar headers, 512-byte padding and the end-of-archive
# record included) stays under MAX_PART_BYTES
parts=()
for month in "$tmp"/files/*/; do
  mm=$(basename "$month")
  mkdir -p "$out/$mm"
  part=0; size=0; list=""
  flush() {
    [ -n "$list" ] || return 0
    part=$((part + 1))
    p="$out/$mm/rot-$stamp-$(printf '%02d' "$part").tar"
    printf '%s\n' "$list" | sed '/^$/d' > "$tmp/.list"
    (cd "$month" && tar -cf "$p" -T "$tmp/.list")
    bytes=$(stat -c %s "$p" 2>/dev/null || stat -f %z "$p")
    if [ "$bytes" -gt "$MAX_PART_BYTES" ]; then
      echo "::error::$p is $bytes bytes, over the $MAX_PART_BYTES-byte part limit" >&2; exit 1
    fi
    echo "  crypto-raw-$mm/$(basename "$p"): $(wc -l < "$tmp/.list") files, $((bytes / 1048576)) MB"
    parts+=("$mm:$p")
    list=""; size=0
  }
  while IFS= read -r rel; do
    fbytes=$(stat -c %s "$month/$rel" 2>/dev/null || stat -f %z "$month/$rel")
    cost=$(( 512 + (fbytes + 511) / 512 * 512 ))
    if [ -n "$list" ] && [ $(( size + cost + 20480 )) -gt "$MAX_PART_BYTES" ]; then flush; fi
    list="$list$rel"$'\n'; size=$(( size + cost ))
  done < <(cd "$month" && find . -type f -name '*.json.gz' | sed 's|^\./||' | sort)
  flush
done

if [ "$UPLOAD" = 1 ]; then
  for entry in "${parts[@]}"; do
    mm=${entry%%:*}; p=${entry#*:}
    tag="crypto-raw-$mm"
    gh release view "$tag" >/dev/null 2>&1 || gh release create "$tag" --title "Crypto raw archive $mm" \
      --notes "Raw envelopes of $mm rotated out of crypto-state (crypto/scripts/rotate_raw.sh). Extract every part into crypto/data/raw." >/dev/null
    # a part already on the release (a re-run the same day) is replaced, never duplicated
    gh release upload "$tag" "$p" --clobber >/dev/null
  done
fi
done_ok=1
find "$ROOT" -type d -empty -delete
mkdir -p "$ROOT"
echo "rotated $moved files into ${#parts[@]} release part(s)"
