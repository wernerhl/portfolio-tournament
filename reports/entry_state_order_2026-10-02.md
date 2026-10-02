# Execution Order: Entry-State Indicator (2 October 2026) — report

All six items executed on 2 October 2026, one commit or more per item, prefixed [E1]–[E6].

## Acceptance

| # | criterion | result |
|---|---|---|
| 1 | referee before and after, zero CRITICAL | before `reports/audit_2026-10-02_E_before.txt`: 27 findings, 0 CRITICAL; after `reports/audit_2026-10-02_E_after.txt`: 27 findings, 0 CRITICAL. The only line that differs is the live VIX figure. |
| 2 | Incyte and Corpay reproduce the reference | INCY at the 1-Oct close: 117.14, 20d 124.13, 50d 123.65, 200d 106.77, ATR 3.27, RSI 41, range 115.77–130.80, trend passes, setup yes, no trigger: **WATCH**; stop **112.50**; earnings 27 Oct, 18 sessions, so READY-HALF once triggered. CPAY: 389.73, 200d 346.32, ATR 7.47, RSI 31 (30.8), range 386.23–427.46: **WATCH**, stop **378.76**. Exact to the cent, as unit tests on fixtures and in the live file. |
| 3 | every card shows badge, trigger, stop, size, event countdown; no buy-zone language | screen board (five columns; on phones the badge sits under the ticker), book positions, tournament tier rows (badge column) and drill-downs, ticker detail. `entry_level` is the "mean-reversion reference" in the producer and on every page. The referee check `entry:buy_zone_language` scans the served pages and signals. |
| 4 | a synthetic series walks AVOID → WAIT → WATCH → READY → WATCH on a stop breach, each transition logged | `tests/test_entry_state.py`: 5 passed; the breach is logged with its reason ("stop breach (close below the armed stop …)"). |
| 5 | registration committed before any run; power check reported first | v1 registered (fc8ece3) and the script committed (fd48e7a) before any run. The v1 power check was committed (c33b59d) and exposed a flaw, so v2 was registered (e8f7bd8) before any v2 run. The v2 power check was committed (9e50473) before READY ran (8cd3de2). |
| 6 | mistakes-ledger entry for 2 October (advisor) | `mistake-2026-10-02-1` (advisor: a purchase recommendation built on the screen without an entry check, Incyte 30 Sept). Also `mistake-2026-10-02-2` (agent: the v1 pairing flaw). The ledger verifies intact. |

## What was built

- **[E1]** `scripts/entry_state.py` and the frozen rules in `data/entry_state_config.json` (label DIAGNOSTIC). The step runs nightly after the earnings calendar and before the brief. It keeps a daily OHLC store, `data/source/ohlc_daily.parquet` (about 520 sessions; a split in the stored window triggers a full refetch). Outputs: `data/entry_state.json` (534 names; size and book effect for every WATCH/READY name) and the append-only `data/entry_state_log.jsonl`. Reruns of a session reproduce the same record from the inputs it was first graded on, and the log deduplicates. Names with no bar for the session get no state and a reason (seven names: AVB, BK, CFLT, EA, EQR, PSTG and SATS return no current data from the provider). The earnings calendar now covers the tier positions, so every card has a countdown. New referee checks: `entry:states`, `entry:cards`, `entry:stop_floor`, `entry:size`, `entry:diagnostic_gate` (CRITICAL), `entry:language`, `entry:buy_zone_language` and `entry:log`. Each one was caught by a mutation on a scratch copy.
- **[E2]** The display and the relabels. Also: the rulebook's percentage stop is labelled RULEBOOK STOP so it is not confused with the entry state's stop, and tier drill-downs are pinned to the screen width on phones. The daily brief's facts gain `entry_state_changes` for held and board names.
- **[E3]** Validation registrations: v1, then v2, which superseded it.
- **[E4]** The run script and the two power checks.
- **[E5]** The READY comparison and the verdict, shown on every entry-state block.
- **[E6]** The ledger entries, the referee after, this report, the guide.

## The validation, in one paragraph

Registration v1 paired the contestants on (entry month, ticker) cells. Its power check ran opposite to expectation, and a diagnostic showed why: a later entry in the same month implies a pullback after the month-start baseline entered, so the paired baseline was the set that went on to fall. v1's READY stage never ran. v2 returned to the order's wording ("paired on common names"): every entry of the common names, months resampled jointly. v2's power check failed narrowly (MAE resolution ±0.27 point against ±0.25 required), so under the registration the READY result is **NO VERDICT**. It would not have passed either way. READY's median loss before 20 sessions was 0.19 point *higher* than month-start entries [−0.11, +0.49]; its 60-session return was 0.24 point better [−0.09, +0.59]; it was stopped out within 20 sessions 35% of the time against 21%. That matches the expected result stated in advance. **The badge stays DIAGNOSTIC.** Details: `reports/entry_state_validation_2026-10-02.md`.

## Observations at the 1-Oct close (descriptive)

534 names: AVOID 346, WAIT 110, WATCH 57, READY 14. The trend gate fails for about two-thirds of the universe, consistent with the canonical prices (34% are above their 200-day with a positive 12-1 return). Held names: AVGO AVOID, BMNR AVOID, GOOG AVOID (it moved from WAIT on 1 Oct: the trend gate failed), GEV WAIT, NVDA WAIT. Rule outputs, not instructions.

## Left for the operator

1. Whether to register a third test, and which. The options are in the validation report: a mean rather than a median for MAE20, a test of the stop rule itself, or exits at the stop. None is chosen here.
2. The rulebook's separate "ENTRY CONDITIONS n/5" signal label (a count of five technical conditions, not the reference level) is unchanged. Renaming it changes a stored signal string that other code matches on, so it waits for a decision.
3. Standing items from earlier orders, unchanged: the CLAUDE_CODE_OAUTH_TOKEN secret for the brief, the R2 choice, the R4/R5.4 authorizations, the REFUNDING display, the three model-input bug decisions, and the brokerage exports.
