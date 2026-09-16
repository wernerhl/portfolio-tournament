# Phase 3 report — Registry v4

Execution Order of 16 September 2026, Phase 3 (items 3.1–3.2). Executed 16 September 2026, 13:20–13:40 CST.

| commit | item |
|---|---|
| 8d56dc0 | [3.1] Registry v4: `sub` field on the members of ai_infra; GEV at 0.6 with sub power; consumers; treemap and exposure bars at sub-thesis resolution |
| 19c05b1 | [3.2] Three register entries (memory, power, networking) with earnings-anchored review dates; the earnings calendar job; the auto-log against these entries |

## 1. Referee, verbatim

**Before Phase 3** is the reading after Phase 2 (`reports/audit_2026-09-16_phase2_after.txt`, 20 findings, 0 CRITICAL).

**After Phase 3** (`reports/audit_2026-09-16_phase3_after.txt`):

```
last trading session: 2026-09-15
[HIGH    ] tournament:dead_columns      regime_v4_daily.csv: columns empty for last 5+ rows but populated earlier: ['p_15_20_elastic_net', 'p_15_40_logistic_pc', 'p_15_60_logistic_pc']
[HIGH    ] xfile:vol_single_source      intraday vix 16.73 vs canonical 17.2
[HIGH    ] nullguard                    intraday.vvix is null; dependent safety checks must read IMPAIRED not false
[HIGH    ] governance:coverage          5_werner: unclassified share 17% > 15%
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ANET review_by 2026-08-18 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ETN review_by 2026-08-14 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override GD review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override MSFT review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override NVDA review_by 2026-09-09 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override VRT review_by 2026-08-12 passed (decay should be active)
[INFO    ] tournament:freshness         loco_cv_results.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         ml_indicator_weights.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_loadings.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_variance_explained.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_v3_correlation.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           watchlist_top30.csv: no date axis found (static config?)
[INFO    ] book:export                  no brokerage export on record (holdings_export.json absent); holdings.json source: brokerage positions, 2026-09-16 (manual transcription; replaced by CSV ingestion in Phase 2)

20 findings; 0 CRITICAL
```

Zero CRITICAL. HIGH unchanged. `governance:coverage 5_werner: unclassified share 17%` persists only because `thesis_daily.json`'s tier-5 exposure is computed from the tournament's last NAV row (15-Sept positions: the old book); tonight's NAV row carries the 16-Sept holdings, and under v4 the book's unclassified share is 9 percent (GEV 0.4 + GOOG 0.3 remainders), below the 15 percent line.

## 2. Item by item

**3.1 Registry v4.** `data/thesis_registry.json`: version 4, `frozen_at` and `approved_at` 2026-09-16T13:25:00-06:00, `approved_by` "Werner Hernani-Limarino (written instruction, 2026-09-16)", `supersedes: 3`, the v3 record appended to `history`, `resolved_in_v4` (GEV). Inside `ai_infra` each member carries `{weight, sub}` — MU memory; NVDA, AVGO, TSM chips; ANET networking; GOOG, MSFT, META hyperscaler; GEV (new, 0.6), CEG, ETN, VRT, VST power — plus a `sub_theses` block with labels and a `sub_note` stating that the sub-resolution is a display dimension. The Σ-weights-per-name ≤ 1 invariant holds (checked). No other thesis and no judgment text changed.

Every consumer reads a member's weight through a helper: `compute_thesis_daily.member_weight`, `compute_thesis_backtest`, `update_daily`'s validator, `book_analytics.member_weight`, `app.js memberWeight`. The parent buckets — and with them the retirement and attribution machinery — are unchanged; the attribution figures after the change equal those before it apart from GEV now carrying 0.6 of ai_infra on the tiers that hold it.

Display: `thesis_daily.json` carries `exposure_sub` per tier (`ai_infra/chips`, `ai_infra/hyperscaler`, `ai_infra/power` on the 15-Sept row). The treemap groups the positions of ai_infra by sub-thesis with the parent total in every group label and a parent-totals line in the caption; verified in the browser: group labels `AI INFRASTRUCTURE · CHIPS · 25% (AI INFRASTRUCTURE 54%)`, `… HYPERSCALERS · 22% …`, `… POWER · 7% …`, caption "parent totals: AI infrastructure 54% = Chips 25% · Hyperscalers 22% · Power 7%". The exposure bars of the thesis section and the book panel render the sub-segments (shade steps of the parent colour, tokens only) with the parent total.

Effective theses for the book under v4: **1.30** (1.55 under v3), inside the order's 1.3–1.5 band.

**3.2 Register entries.** Three ticker-scoped entries appended to `data/thesis_claims.json` (the six parent entries untouched), each with the claim, disconfirmers and kill criterion as ordered, `frozen_at` 2026-09-16, the v4 provenance, `tickers`, `next_earnings`, `review_by` and `review_by_basis`:

| entry | tickers | next earnings (provider) | review_by |
|---|---|---|---|
| Memory | MU | 2026-09-30 | 2026-10-14 |
| Power | GEV | 2026-10-28 | 2026-11-11 |
| Networking | ANET | 2026-11-03 | 2026-11-17 |

The event calendar module carried no earnings dates. `scripts/build_earnings_calendar.py` now adds the provider's next earnings date (yfinance `Ticker.calendar`, "Earnings Date") as an `EARNINGS` event with its source URL, retrieval date and provenance for the held names, the register's claim tickers and the ai_infra members — 16 dates on the first run — one upcoming entry per ticker, refreshed weekly, a changed date keeping its history. It runs in the nightly before the thesis job. The auto-log (mechanical channel) records each earnings date of an entry's tickers against that entry with the equal-weight one-day return of those tickers, and rolls `review_by` to the next provider date plus fourteen days once a date has passed, logging the roll. Kill status is mechanical and keyed by claim id. GEV's visibility override in the screen view's registry keeps its own review date (noted on the entry).

## 3. Deviations and judgment calls

- The member value schema changed from a bare weight to `{weight, sub}` for ai_infra only (the order asks for "a `sub` field to members"); every reader tolerates both forms.
- SNDK and PLTR are members of ai_infra without an assignment in the order; they carry no `sub` and render as "other" inside ai_infra.
- The provider's earnings dates are estimates until the company confirms them; the event says so in `provenance`, and the weekly refresh replaces a changed date and keeps the old one in `history`.
- The three entries log earnings dates only (no macro-event entries), since the order ties them to earnings; the parent entries keep their CPI/NFP/FOMC entries.
- The register's kill status is now keyed by `claim_id` for the three entries and by `thesis_id` for the parents.
- The stress scenario "memory −40%" now takes its members from the registry's `sub: memory` (MU) instead of the v3 queue proposal.

## 4. Acceptance 6

Registry v4 frozen with provenance — yes. Three register entries with review dates — yes. Treemap at sub-thesis resolution — yes (browser evidence above).
