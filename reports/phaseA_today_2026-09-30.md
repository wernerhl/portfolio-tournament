# Phase A report — Today, before the 08:30 ET releases

Execution Order of 30 September 2026 ("Daily Brief, News, Events, and the September 30 Fixes"), items A1 and A2. Executed 30 September 2026, 03:50–04:15 ET; pushed and deployed at 04:14 ET (dispatch of the intraday workflow), before the 08:30 ET releases.

| commit | item |
|---|---|
| 22a02e2 | [A1] Holdings: the 30-Sept book replaces the 16-Sept book; ledger carries the ANET and MU sales |
| dae9faf | [A2] Calendar coverage: PCE, GDP, PPI, JOLTS, ISM, retail sales, claims, the election, expirations; impact levels; the cluster detector |

## A1 — Holdings

`data/holdings.json` is now the 30-September account summary exactly as ordered (GEV 25, NVDA 100.1509, AVGO 50, GOOG 50, BMNR 200.0702; cash $148,316.97; cadence on_change; source "brokerage positions, 2026-09-30 (manual transcription …)"). MU and ANET are gone.

`compute_book.py` re-run on the 29-September closes against the order's independent computation "at the 29 September close with 30 September marks":

| figure | order | computed | note |
|---|---|---|---|
| total | $235,467 | $235,103 | the difference ($364, 0.15%) is the marks: the store's official 29-Sept closes versus the account summary's 30-Sept marks |
| equities | 37% | 36.9% | |
| portfolio volatility (with cash) | ~12% | 11.7% | 126 sessions |
| beta with cash / equity sleeve | ~0.73 / ~1.97 | 0.71 / 1.93 | Σ w β; the sleeve regression also 1.93 |
| risk shares GEV / NVDA / AVGO / GOOG / BMNR | 37 / 24 / 22 / 9 / 8 | 35.6 / 23.4 / 22.8 / 10.0 / 8.2 | |
| 2020-scale scenario (SPY −34%) | ~−25% of portfolio | −24.2% of NAV | $−56,908 |

Every figure lands within a point of the order's; nothing disagrees beyond the marks.

**Ledger.** Two entries appended to `data/actions.jsonl`, both `source: "operator report, pending export confirmation"`:

- ANET, 100 shares sold, `date_range` 2026-09-16 → 2026-09-18, price null ("unknown until the export"). Regime on the sale date: there is no published vintage for those sessions (the nightly outage of 16–28 September; they are now recorded as no-publish sessions under C3), so the entry carries the last published reading (2026-09-15, R 0.2683, LOW RISK) and the revised series (09-16 0.2871, 09-17 0.2326, 09-18 0.2084, all LOW RISK). The signal record is the last nightly's before the sale (c4efe34, file stamp 2026-09-15).
- MU, 50 shares sold, 2026-09-29, price $1,076.79 with `price_basis` "inferred: cash change divided by shares sold; flagged until the export confirms it", amount $53,839.50. Regime: published R 0.2796, LOW RISK. Signal record: the 29-Sept nightly's ("BELOW TRAILING LEVEL", e478308). Options lens at the time: event-implied move 7.78% (the 25-Sept vintage under the 26-Sept method, as served on 29 September), next earnings 2026-09-30 after the close, first expiry after 2026-10-02, historical median reaction 5.25%.

A reconciliation the ledger does not state: the cash change from the 16-September book ($74,527.68 → $148,316.97 = $73,789.29) less the MU proceeds at the inferred price leaves $19,949.79, which is $199.50 a share on 100 ANET — inside ANET's 16–18 September range (197.54–199.53). The export decides.

**Regenerated on the new book:** ticker_signals, comparators, the bonds book-integration (sleeve metrics, states), the options lens and hedges, factor exposure, thesis daily. `compute_lens` now takes each name's roles from the current holdings and board, keeping the vintage's roles beside them (`roles_at_snapshot`), so a name sold since the snapshot no longer reads "held" on the event board. Two as-published records still show the old book until tonight's session: the tournament's 29-September row (tier NAVs are history) and the screen board's held markers (its vintage for 29 September is immutable and is rebuilt for 30 September tonight).

## A2 — Calendar coverage

`build_event_calendar.py` v3.0 (477 events, 2 clusters). Sources retrieved on 30 September 2026 and recorded per event with URL, retrieval date and provenance:

| type | source | dates loaded |
|---|---|---|
| PCE, GDP | bea.gov/news/schedule (page last modified 30 Sept 2026) | PCE 09-30 (Aug), 10-29 (Sep), 11-25 (Oct), 12-23 (Nov); GDP 09-30 (Q2 third), 10-29 (Q3 advance), 11-25 (second), 12-23 (third) |
| PPI | bls.gov/schedule/news_release/ppi.htm | 2026 official (Oct 15, Nov 13, Dec 15); 2027 pattern estimate |
| JOLTS | bls.gov/schedule/news_release/jolts.htm | 2026 official (Sep 29, Nov 3, Dec 1) |
| ISM | ismworld.org (the dated calendar page redirects to a member login; the published rule — manufacturing first business day, services third, 10:00 ET — confirmed against the Oct 1 / Nov 2 / Dec 1 report pages) | rule-derived Oct 2026 → Dec 2027, flagged |
| retail sales | census.gov economic-indicator calendar | Oct 15, Nov 17, Dec 16 |
| claims | dol.gov/ui/data.pdf (Thursdays 08:30 ET; Wednesday in Thanksgiving week) | weekly Oct 2026 → Dec 2027, impact low |
| election | 2 U.S.C. §7; usa.gov | 2026-11-03 |
| OPEX | Cboe 2026 Options Expiration Calendar | third Fridays (Oct 16, Nov 20, Dec 18 quarterly …), Thursday when the Friday is a holiday |
| FOMC 2027 | federalreserve.gov FOMC calendars | the Board's published 2027 dates replace the earlier pattern estimates |

Every event carries an impact level (high: FOMC, CPI, NFP, PCE, election, held-name earnings; medium: PPI, GDP, JOLTS, ISM, retail, quarterly OPEX, other earnings; low: claims, monthly OPEX, auctions). Anchors asserted in the builder and in the referee (`calendar:anchor`, HIGH): PCE 2026-09-30, jobs 2026-10-02, CPI 2026-10-14, PPI 2026-10-15, FOMC 2026-10-28, PCE 2026-10-29, election 2026-11-03 — all present.

**Cluster detector** (a high-impact macro release on a held name's earnings date): 2026-10-28 FOMC with GEV and GOOG earnings; 2026-12-09 FOMC with AVGO earnings — exactly the two the order names. It runs in both calendar builders and the referee requires its presence.

Tests: `tests/test_event_calendar.py`, 8 passed.

## Deviations

- The ISM dated calendar is behind a login; the published rule is used and flagged per event.
- The election page states "November 2026"; the exact date comes from the statute (the Tuesday after the first Monday in November), recorded in the provenance.
- The ANET sale date and price, and the MU price, are flagged pending the export.
