# Options lens — Phase 6 (referee checks)

Order 26 September 2026, commit [O6] — the options block in `scripts/audit_nightly.py`,
landed alongside Phase 1 (§8).

## Checks, machine-enforced

| check | severity | what it asserts |
|---|---|---|
| options:snapshot_window | CRITICAL | a scheduled vintage was pulled inside 15:30–16:00 ET on a trading day; a backfill is flagged and reported as INFO, never silently accepted |
| options:immutable | CRITICAL | every vintage file's sha256 equals the one recorded at write time (a rewritten vintage is caught) |
| options:provider_iv | CRITICAL | no vintage parquet and no lens.json carries the provider's impliedVolatility field |
| options:iv_range | CRITICAL | every computed ATM implied volatility lies in [0.05, 3.0] |
| options:language / options:directive | CRITICAL | no served options file contains edge, alpha, or a buy/sell directive |
| options:live_quotes | HIGH | each held name has at least 70% of front-expiry strikes with live bid-ask (else its options column reads impaired) |
| options:next_earnings | HIGH | every held name has a next-earnings date |
| options:vintage_missing | HIGH | the last session's vintage exists |
| options:held_missing / options:vintage_file | HIGH | a held name absent from the vintage; a file recorded in _meta but absent |

## Referee outputs (verbatim in the audit files)

| | findings | CRITICAL | options module |
|---|---|---|---|
| before Phase 1 (`audit_2026-09-26_options_O1_before.txt`) | 44 | 19 | — |
| after the vintage, lens and hedges (`audit_2026-09-26_options_after_data.txt`) | 45 | 19 | 1 INFO (the flagged backfill); 0 CRITICAL, 0 HIGH |

The 19 CRITICALs are the pre-existing freshness outage (Phase 1 report), fixed in
`8f022c3`; the first clean referee is expected after Monday's close run. The module's own
checks all pass on the 25-Sept vintage: 45 hashes match, no provider column, every ATM IV
in range, every held name at or above the 70% live-quote bar (GEV the lowest at 72%), every
held name with a next-earnings date, no prohibited language.
