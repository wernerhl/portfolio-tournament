# Phase C report — Fixes

Execution Order of 30 September 2026, items C1–C4. Executed 30 September 2026.

| commit | item |
|---|---|
| 8c7a05e | [C1] Options lens: event-implied move by the bracketing method |
| 9c2f856 | [C2] Referee: every held name's lens spot must be the last session; the event method must be the bracketing one |
| 3644858 | [C3] Referee: holdings older than 5 sessions; book tickers must equal holdings; dead_columns and gaps resolved |
| 7b1d6d8 | [C4] Holdings ingestion: the inbox one-shot; a realized-gains export no longer makes the inbox ambiguous |

## C1 — Event-move method

The 26-September specification subtracted base variance at the back-month IV from the first post-event expiry; whenever the event is weeks away or the back month carries term premium the subtraction collapses toward zero. Corrected method as ordered: PRE = the last expiry before the release, POST = the first after it; event variance = POST total variance − PRE total variance − IV_pre² × (non-event sessions between them)/252. An expiry on the release date expires at the close, so it precedes an after-close release and contains a before-open one. Without a pre-event expiry the fallback compares POST with a later expiry that contains no further release (the forward variance between them is the base per session) and is flagged. The superseded figure is kept beside each new one for the transition.

Recomputed on the 25-September vintage (the only vintage on disk; see C2):

| name | before (26-Sept method) | after (bracketing) | PRE → POST (sessions) | fallback |
|---|---|---|---|---|
| GEV | 2.90% | 6.87% | 10-23 → 10-30 (20, 25; 4 non-event) | no |
| NVDA | 2.20% | 7.61% | 10-30 → 11-20 (25, 40; 14) | no |
| MU | 7.78% | 8.74% | 09-28 → 10-02 (1, 5; 3) — a Monday expiry brackets the 30-Sept after-close release | no |
| AVGO | 2.58% | 9.75% | 11-20 → 12-18 (40, 59; 18) | no |
| GOOG | 4.37% | 6.67% | 10-23 → 10-30 (20, 25; 4) | no |
| BMNR | 4.89% | 12.08% | 11-20 → 2027-01-15 (40, 77; 36) | no |
| TSM | null | 3.98% | 10-09 → 10-16 | no |
| ORCL | 3.51% | 11.71% | 11-20 → 12-18 | no |
| NFLX | 6.67% | 9.12% | 10-16 → 10-23 | no |

42 of 45 names carry a move (SPY, QQQ and SMH have no release); one fallback (FDS: no listed expiry before its release, 10.96% by the forward-variance base). The MU figure stays near 8 percent as the order expected. The hedge selector's event line and the event board follow the new figure; the lens definitions and the board's caption state the method.

## C2 — Lens freshness and archive

The GEV record carried `spot_source: 2026-09-25 close` because no scheduled vintage exists: the 15:45 ET snapshot job's crons landed 3.5–5 hours late on 28 and 29 September and the sleep-until rewrite (334871a: hourly starts from 09:00 ET that sleep until 15:44 ET, serialized by a concurrency group, a no-op after the window) runs for the first time today. Nothing is backfilled — vintages are as-published. New referee checks: `options:lens_spot_stale` (HIGH) — each held name's lens spot date equals the last session; it fires on all five names now and clears with today's vintage — and `options:event_method` (HIGH). The schedule's first live test is 30 September; if GitHub's delays defeat even the sleep-until design, the fallback is a local launchd job dispatching the workflow at 15:44 ET (needs the operator's go).

## C3 — Referee

- `book:holdings_age` fires at 5 sessions (was 20).
- `book:holdings_mismatch` (CRITICAL): the tickers in book.json must equal the tickers in holdings.json. Mutation test on a copy of data/: TSM added to holdings → CRITICAL "book.json tickers […] != holdings.json tickers […]"; as_of set 7 sessions back → HIGH "7 sessions old (>5)". On the real data neither fires.
- `tournament:gaps` — cause: `regime_daily_published.csv` is append-only and receives a row only from a nightly that publishes; the outage of 16–28 September appended nothing for nine sessions (16, 17, 18, 21, 22, 23, 24, 25, 28). Resolved by recording those sessions as no-publish rows with the reason — the vintage's own convention for a session the system did not publish (no R value invented; every published value untouched).
- `tournament:dead_columns` — cause: the model-winner columns of `regime_v4_daily.csv` (p_15_20_elastic_net, p_15_40_logistic_pc, p_15_60_logistic_pc) are produced only by the monthly `regime_v4_ml` run (last 2026-09-07, rows through 09-04); the nightly scorer preserves them and never fills new rows, so they are empty by design after every monthly run and the generic "empty for the last 5 rows" test fired every day between runs. Those three columns are exempt from the generic test; the specific `v4:monthly_columns` check (populated through the monthly model's train_end, else HIGH) remains the assertion that can be satisfied.

Referee on the working tree after C3: 21 findings, 0 CRITICAL (both findings gone; the new lens-spot check on).

## C4 — Holdings ingestion

No brokerage export exists on this machine, so the parser stands complete against the known dialects and its fixtures (`tests/test_ingest_brokerage.py` 16 passed, unchanged). Added: `scripts/ingest_inbox.py`, the operator's one-shot (positions and transactions → holdings.json and holdings_export.json; transactions → actions.jsonl; the realized gain/loss export → realized_gains.json; each tolerating the others' absence; processed files archived under `inbox/archive/<stamp>/`, git-ignored; `--dry-run`), and a sniffing rule so a realized-gains CSV in the same inbox no longer reads as a second positions file. `inbox/README.md` documents the three files. Until an export is ingested every panel that uses the holdings shows "holdings as of 2026-09-30, manual" in amber (book, stress, sleeves, event board, hedge selector, the bonds book-integration panels, the goals).
