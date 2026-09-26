# Options lens — Phase 1 (data engineering)

Order 26 September 2026. Commits [O1.1] the IV engine (never the provider's field), [O1.2]
the 15:45 ET snapshot and immutable archive, [O1.3] earnings calendar and reaction history;
[O6] the referee checks land alongside (§8). Item 1.4 (history purchase) is a note, below.

## Referee, before and after (verbatim in the audit files)

| | findings | CRITICAL | of which the options module |
|---|---|---|---|
| before (`audit_2026-09-26_options_O1_before.txt`) | 44 | 19 | 0 |
| after data (`audit_2026-09-26_options_after_data.txt`) | 45 | 19 | 0 (+1 INFO: the flagged backfill) |

**All 19 CRITICALs pre-date this order** and are the same finding nineteen times: freshness —
every served file stuck at 2026-09-15 (16 tournament, 3 screener). Root cause, found and
fixed during this phase (commit `8f022c3`, not part of the options items): GitHub delivers the
22:00 UTC nightly cron up to 2.5 hours late; from 22 September its runs landed after
midnight UTC, the decide step inferred "late-retry schedule" from the wall clock and skipped
them ("no retry needed") — every nightly since was a 54-second no-op. And when a close run
did execute (17/18 Sept), the provider had no close bar yet; compute_nav's assertion is only
a warning inside the pipeline, so the validator recorded the downstream FRESHNESS symptom and
the 01:30 retry — built for exactly that case — never armed. The gate now keys off the cron
that fired and the FRESHNESS symptom arms the retry. The first clean referee is expected
after Monday's close run. The options module adds no CRITICAL or HIGH.

## What was built

**1.1 — never the provider's IV.** `options_common.implied_vol` inverts Black-Scholes by
Brent's method on [0.01, 5.0], risk-free from the canonical 3-month bill (`us03m`, 4.11%),
dividend yield from the fundamentals store. Price per strike: bid-ask mid where both are
positive, else last flagged `quote: last`; at or below intrinsic + $0.01, or a failed
inversion → `iv: null` with the reason. Round-trip exact. The snapshot does not store the
provider's `impliedVolatility` column at all, and the referee's `options:provider_iv` check
is CRITICAL if it ever appears in a vintage or in lens.json (acceptance §9.3).

**1.2 — snapshot and archive.** `snapshot_chains.py` pulls once at 15:45 ET on trading days
(the job writes only inside 15:30–16:00 ET; after-hours pulls are prohibited and exit
without writing), for the 45 analyzed names (7 held, the board's top 40, SPY/QQQ/SMH), the
full chain within 400 days, into `data/options/vintages/YYYY-MM-DD/{ticker}.parquet`,
immutably: an existing file is never rewritten (verified — a second run skips all names),
and each file's sha256 is recorded in `_meta.json` for the referee's `options:immutable`
check. Workflow `options_snapshot.yml` spreads crons across the window in EDT and EST so a
late-delivered schedule still lands inside it.

**1.3 — earnings and reactions.** `build_earnings_reactions.py`: for every analyzed name the
next earnings date with its time of day, source and retrieval date, and the six-year
reaction series from the price store (close before the release to close after; after-close
releases react close(D)→close(D+1), before-open close(D−1)→close(D)). 42 names fetched, 0
failed. The event calendar's ticker set now includes the board's top 40. MU: 24 releases in
six years, median |reaction| 5.25%, max 16.2%, next 2026-09-30 after the close.

## Numeric checks (acceptance §9.2, §9.6)

- First vintage: 2026-09-25, 45 names, 45 files, 3.8 MB; MU 16 expiries, 5,934 strikes,
  5,616 inversions; live-quote share on the held names' front expiry 72–88% (all above the
  70% bar; GEV the lowest at 72%).
- Immutability: a second run of the same session wrote 0 and skipped 45; the sha256 of every
  file matches its record (§9.6 first half; the second session appends Monday).
- MU's 24 releases and 5.2% median reproduce the order's figures exactly.
- The after-hours gate, verified in CI: a manual dispatch of `options_snapshot.yml` on
  Saturday 26 Sept (run 36274812763) completed without writing a vintage or making a commit
  — outside the 15:30–16:00 ET window the job is a no-op, as designed.

## Deviations, with reasons

1. **The first vintage is a flagged backfill, not a 15:45 snapshot.** The order was received
   on a Saturday; the last session's chain (25 Sept) was pulled on 26 Sept from a closed
   market, where the provider retains the session's closing bid-ask (84–88% live quotes on
   the held names — after-hours zeroing applies to the immediate post-close window, not the
   weekend). `_meta.json` carries `snapshot_kind: backfill` and the pull time; the referee
   reports it as INFO, never as a scheduled vintage. The first scheduled vintage lands
   Monday 28 September at 15:45 ET.
2. **1.4, the history purchase, was not made** (a vendor purchase is Werner's decision and
   requires payment). IV rank and percentile are `null` with the reason; the Phase 5 tests are
   registered, not run. The archive supplies both after about a year.
3. **The price store was stale (09-14) from the nightly outage.** The engine's `closes()`
   reads the store first and fills the gap to the last session from the provider in memory —
   the store itself is not modified and the overlay is recorded in every output's
   provenance. With the nightly fixed the overlay becomes a no-op.
4. **`lxml` added** to the venv and the CI install lines (the provider's earnings-date
   endpoint is scraped HTML).
5. **`options_layer_design.md` is not on this machine**; the order states every decision this
   phase needed.
