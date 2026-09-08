# September Audit Remediation — Report

Executed 2026-09-08 (00:14–06:10 ET) against the Execution Order issued 7 September 2026. Commits `[1]`–`[8]` on `portfolio-tournament` main (`ddb16e7 c6704b8 babab2e 9f9511b d7d5f3c 43182d5 410cf27 d457947`), `[5][8.3]` on `portfolio-screener` (`72269a2`). Rebased on the intraday bot's commits; nothing force-pushed.

## Acceptance referee — GAP, reported first

The order names `audit_nightly.py` and `system_audit_2026-09-07.md` ("both in this directory") as the acceptance referee and requires `reports/audit_before.txt` / `reports/audit_after.txt` verbatim. **Neither file exists**: not in `portfolio-tournament`, `portfolio-screener`, or `whl._Trading`; not under `/Users/whl` to depth 5; not on any branch or in the git history of either repo. Per the order's preamble I completed every other item and did not improvise a referee — the suite's output cannot be produced and its CI installation (item 6) cannot be done until the files are supplied. Every item below therefore carries its own direct evidence (numbers from files and runs), which the order explicitly says is *not* a substitute for the suite output. **When the two files are available, run** `python3 audit_nightly.py data ../portfolio-screener/data` **before/after against `ddb16e7^` and `d457947`** and append.

## Do-not-touch — honored

No registry content, as-published value, or vintage file changed. `regime_daily_published.csv`: all 72 published `R_t_published` values byte-identical (asserted in the [8.4] script); three rows added with the value **empty**. The July calendar guard on the daily job, benchmark/tier identities, published vintage, hysteresis, complacency null-guard, registries and decay engine, screener correlation/typed fields, vintages, event calendar — untouched. (The one edit inside the daily job's guard is item 2.3's ordered non-trading exit, added *before* the pre-close logic; the pre-close/force logic itself is unchanged.)

## Item 1 — Canonical vol-close provider chain (`ddb16e7`)

**Root cause (diagnosed, not assumed):** the July build called `cdn.cboe.com/api/global/delayed_quotes/charts/historical/{sym}.json` with `_`-prefixed symbols — it returned nothing for 4 of 5 indices. Probing the CDN: `us_indices/daily_prices/{SYM}_History.csv` returns **200 for all five** through 09/04/2026, and the schemas **differ per index** — VIX/VIX3M/VIX1D carry `DATE,OPEN,HIGH,LOW,CLOSE`; VVIX and SKEW carry `DATE,<INDEX>` (single value column). One parser, per-file column selection.

Changes: `refresh_data.build_canonical_close()` — per-field chain **cboe → yfinance bar → yfinance direct → unavailable+reason**, provider recorded per field, `null_reasons` for any null, `series_sources` (cboe from/to per field); Cboe history **overlaid** onto `vol_indicators.parquet`; write-time assertion (trading day + any of vix/vix3m/skew null → write refused, previous record retained, exit 1); validator names `canonical_vol_close_required_nonnull` / `_stale` / `_optional_needs_reason` in status.json; `--canonical-only` entry point.

Evidence (regenerated 2026-09-04 record):
```
providers {vix: cboe, vix3m: cboe, vvix: cboe, vix1d: cboe, skew: cboe}
vix 14.53 · vix3m 17.61 · vvix 84.42 · vix1d 12.03 · skew 151.58 · spread_spot_3m -3.08 · null_reasons {}
series_sources: vix 1990-01-02..2026-09-04 · vix3m 2009-09-18.. · vvix 2006-03-06.. · vix1d 2022-05-13.. · skew 1990-01-02..
parquet vix3m/vix1d/skew/vvix: last non-null 2026-09-04; 2026-07-20..09-04 = 35/35 sessions non-null
```
1.4 downstream: `intraday.json` `skew`/`vvix` populate on the first post-close reconcile after tonight's (Sept 8) close — the canonical now carries both. The four v4 columns will **not** resume from this fix — see item 7 for the separate diagnosis.

## Item 2 — Trading calendar in every writer (`c6704b8`)

Calendar already contained Labor Day 2026 and full 2027; the defect was that `refresh_data.py` and `compute_intraday.py` never imported it, and the daily job ran the full pipeline on the holiday (rejected by validation, paged as a failure).

Changes: `trading_calendar.require_trading_day(job)` (prints "market closed, nothing to do", exit 0), `now_et()` with `NOW_ET_OVERRIDE` test hook, `served_meta()`; gates in refresh_data, compute_intraday, build_canonical, update_daily (2.3: exit 0 **before** any sub-script), plus ast-inserted, idempotent gates in the 18 remaining `data/` writers (`--allow-non-trading` for manual analysis only). Phantom provider holiday bars removed from `vol_indicators.parquet` (13 rows: Juneteenth, Jul 3, Labor Day). Sept-7 canonical record replaced by the regenerated Sept-4 record; `intraday.json` restored to the Sept-4 session record with `session_date` — no served file carries `session: None`.

Evidence (`NOW_ET_OVERRIDE=2026-09-07`):
```
[update_daily] market closed, nothing to do (2026-09-07)   EXIT 0   git status data/ unchanged ✓
[refresh_data] market closed, nothing to do (2026-09-07)   EXIT 0
[compute_intraday] market closed, nothing to do (2026-09-07)   EXIT 0
```

## Item 3 — Restore vol_regime (`babab2e`)

**17-July diagnosis — corrects the order's expected mechanism.** The canonical file landed 2026-07-07, not the 17th, and `vol_regime.json` was **current through 2026-09-04** (as_of 07-23, 07-31, 08-07, 08-14, 08-24, 09-02, 09-04 in git history). On the Labor-Day run (09-07 — a non-trading day the job did not skip), `refresh_data`'s nightly full-history re-download of yfinance `^VIX3M`/`^VIX1D` came back **ending 2026-07-17** (provider-side regression; the parquet is overwritten every night), so `spread.dropna()` ended 07-17, `compute_vol_regime` wrote `as_of 2026-07-17` **with no input assertion**, validation correctly rejected it (`FRESHNESS vol_regime.json`), but the commit step published the rejected artifacts anyway (the item 8.2 defect). July 17 is the last date yfinance still serves for those symbols — not the day the job died.

Changes: `vol_regime_required_input_null` assertion (fails loudly naming the field); `history_backfill` 2026-07-20 → last session with source per day; dynamics, spike history, validation block regenerated; `small_n` flag + caveat on subsamples; `session_date`/`cadence` stamped.

Evidence:
```
as_of 2026-09-04 · state deep_contango · spread -3.08
history_backfill: 35 days 2026-07-20..2026-09-04 · sources {'cboe': 35}
validation/walk_forward/all_triggers_reversion n=792 small_n=False · event_day_only_reversion n=17 small_n=True
Assertion proof (vix3m nulled in a temp parquet): AssertionError: vol_regime_required_input_null: vix3m is null for 2026-09-04 — refusing to write; vol_regime.json hash unchanged (59837e3a0f1e)
```

## Item 4 — SKEW through the canonical file (`9f9511b`)

`^SKEW` removed from `refresh_data`'s yfinance ticker set; the SKEW series comes from the Cboe overlay (yfinance only as a recorded series fallback if Cboe fails). `regime_indicators` reads the same SKEW the flag and the intraday reconcile use.

Evidence (`compute_regime_v2` on the same inputs, published vintage hash `8eb65d6088fd` unchanged before/after):
```
verdict: COMPLACENCY FLAG — SKEW 152 > 140 and VIX 14.5 < 17 — tail priced, spot fear absent
indicator values: skew 151.58 · vix 14.53 · complacency_flag True (as of 2026-09-04)
```
(The order quotes VIX 15.3 — that was yfinance's phantom Sept-7 bar; Cboe's official Sept-4 close is 14.53. The flag fires either way.) The locally regenerated revised-vintage files were reverted; tonight's nightly regenerates them in CI.

## Item 5 — Stale badges and declared dates (`d7d5f3c`, `43182d5`; screener `72269a2`)

`stamp_served_json()` in update_daily (runs before validation; idempotent; never touches a data field): 11 daily files → `session_date`; on_change/weekly/static files → `cadence` + `as_of` (from `frozen_at`/`generated_at` or the file's last git change). Applied now to **25 files**; validator asserts `served_json_missing_session_date` / `_missing_cadence_as_of`. `vol_canonical_close.json` (pre-July filename) marked `superseded_by`. Screener `visibility_registry.json` stamped `on_change`/`as_of 2026-07-29`.

Frontend: vol_regime, thesis_daily, regime_indicators badges prefer `session_date`; the v4 headline carries its own `asOfBadge`. **Found and fixed while testing:** `lastTradingSessionISO()` skipped weekends but not holidays — the morning after Labor Day it would have badged every current panel STALE. Now mirrors `NYSE_HOLIDAYS` 2025–2027.

Evidence (served a stale `vol_regime` copy, as_of 2026-08-20, then restored):
```
lastSession 2026-09-04
REGIME & OVERLAY  STALE · as of 2026-08-20   (amber)
THESIS — … as of 2026-09-04 · CYCLE POSITION … AS OF 2026-09-04 · P(≥5%/40d) = 13% as of 2026-09-04   (grey)
```

## Item 6 — Audit suite in CI — GAP; HOLIDAYS 2027 already satisfied

Cannot install a suite that does not exist (see referee gap). `NYSE_HOLIDAYS` already carries all ten 2027 closures (01-01, 01-18, 02-15, 03-26, 05-31, 06-18, 07-05, 09-06, 11-25, 12-24); the frontend set now mirrors it. Existing tripwires (validate_outputs + screener CI) continue to block publish on their checks.

## Item 7 — v4 display (`410cf27`)

`regime_v4_daily.csv` gains `raw_score` (the isotonic input — equal-weight mean of the risk scores), backfilled for **5,390 of 5,394** rows (the 4 without ≥12 indicators stay NaN). Dashboard shows it beside the calibrated headline with the verbatim note.

Evidence:
```
2026-09-01 raw 0.2696  cal 0.1309 | 09-02 raw 0.2675 cal 0.1309 | 09-03 raw 0.2275 cal 0.1309 | 09-04 raw 0.2253 cal 0.1309
render: "raw score 0.225 (pre-calibration)  calibrated probability moves in steps; the raw score moves continuously."
```

**Separate diagnosis of the four empty columns (1.4):** `p_7_60_logistic_pc`, `p_15_20_elastic_net`, `p_15_40/60_logistic_pc` are produced **only by the monthly `regime_v4_ml` run**, and the nightly trailing-5 rescore **blanked them every night** — so they always ended exactly 5 sessions before the monthly's data end (Sept-1 run → Aug 24; confirmed from the CSV state two nightlies later). Not a feed issue: the risk-score inputs have no NaN columns after Aug 24. Fixed: the nightly preserves them; `v4_delta_attribution.json` records `model_cols_scored_at: 2026-08-24`. They advance with the next monthly run (Oct 1); re-running the monthly recalibration early was not ordered and would move the calibrated headline, so it was not done.

## Item 8 — Hygiene (`d457947`; screener `72269a2`)

- **8.1** `status.json.failure_reason` names the failing checks (validator raises `SystemExit` with the identifiers; screener already `CI FAIL: <check>`).
- **8.2** a rejected run restores every tracked served file from the last good commit and drops untracked run outputs before writing status.json. Test hooks `FORCE_VALIDATION_FAIL`, `--validate-only`.
- **8.3** screener naive-UTC `updated` removed; header reads `session_date` + tz-aware `computed_at`.
- **8.4** explicit rows: 2026-06-24 and 06-26 — `validation rejected: FRESHNESS vol_regime.json max date 2026-06-18 < last session` (runs 28135598842, 28270479077); 2026-08-27 — `run guard refused: cron throttled past 00:00 UTC, run started 02:02 ET 08-28 and the guard saw pre-close 08-28 (exit 78, run 33146601709)`. `R_t_published` empty, `no_publish_reason` populated. Dashboard reliability figure: **3 no-publish sessions of 75 since inception**.

Evidence (8.2 forced rejection, post-close override, validate-only; probe field written into `tournament.json` first):
```
VALIDATION FAILED: forced_test_failure: FORCE_VALIDATION_FAIL set
data/ diff after rejection: data/status.json only (tournament.json probe reverted)
status.failure_reason: "forced_test_failure: FORCE_VALIDATION_FAIL set; FRESHNESS tournament.json: …" · last_success preserved 2026-09-04
```

**Finding, not fixed (do-not-touch):** the Aug-27 no-publish is a latent interaction — when the cron is throttled past 00:00 UTC, the daily job's pre-close guard sees the *next* trading day pre-close and refuses, skipping the session entirely. The guard is in Section 1; flagged for a decision.

## Item 9 — Thesis coverage — gated on Werner

Not implemented. Dashboard currently shows 20 names unclassified across 5 tiers (banner live). Awaiting the provisional-classification vs manual-approval decision.

## Deviations / mechanics resolutions

1. Referee suite absent → before/after outputs and item 6 install not produced; per-item evidence supplied instead (flagged above).
2. Item 3 diagnosis differs from the order's expected mechanism (documented with git evidence).
3. Item 2.3 required an ordered edit inside the daily job's guard (non-trading exit only); pre-close/force logic untouched.
4. Locally regenerated revised-vintage regime files (regime_daily.csv, regime_v2_*.parquet, regime_indicators.json) were reverted rather than committed, so CI — not a local environment — produces the served revised series tonight. The [4] evidence is from the local run's output.
5. `stamp_served_json` runs as one pass in update_daily rather than editing every writer's payload; intraday/vol_regime/canonical/v4-attribution stamp themselves.

## What tonight's run (Sept 8) will confirm

`intraday.json` post-close reconcile → `skew`/`vvix` populated from canonical; canonical record for 2026-09-08 with all five `cboe`; `vol_regime` as_of 2026-09-08; validator green with the new named checks; nothing published if any tripwire fires.
