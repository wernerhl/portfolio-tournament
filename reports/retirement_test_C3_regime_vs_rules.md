# Retirement test C3 — Regime index versus one-line rules (pre-registered)

**Order** (Governance Decisions and the Retirement Tests, 9 Sept 2026, C3): *"This is the test that can retire the core of the system, and it is registered here before any of it is run."* Registration `reports/c3_registration.md` was committed at **c39e2aa** (2026-09-08 06:52 UTC) before the first computation; the run followed the same hour. Section 6 restates the registration verbatim and section 7 shows the mechanical diff against the committed registration: **empty**.

## 1. Registered outcome

**The regime index fails the registered rule.** On tier 4 (the pure overlay: cash 0–100%, SPY, monthly, net of 10 bps one-way), over 2010-02-01 → 2026-05-21:

| | regime index | best one-line rule (10% vol targeting) | condition |
|---|---|---|---|
| after-cost return per unit of volatility | 0.993 | 0.822 | margin +0.171 must exceed the half-width of the regime's own 90% interval, 0.411 → **not met** |
| drawdown reduction vs buy-and-hold | 63.9% | 29.7% | regime ≥ rule → **met** |

The registered consequence reads: *"If it fails either condition, the regime layer is demoted to a context panel and tier sizing switches to the winning one-line rule; the indicator panel remains as information."* The winning one-line rule is volatility targeting (highest return per volatility among the three rules, and also the largest drawdown reduction among them). **That consequence has not been applied in this batch**: it changes served behaviour (the dashboard's regime layer and every tier's sizing), and the standing rule is that such a change is a human act with recorded provenance. Section 8 lays out the two routes the order itself allows.

## 2. What the numbers say beyond the rule

- **The regime beats every rule on both metrics in the pure overlay, and the paired bootstrap says so with the same 90% coverage.** The registration reports the paired difference (regime − rule, same resampled paths) as context: against vol targeting the return-per-volatility difference is [+0.017, +0.318] and the drawdown-reduction difference is [+12.0, +39.5] points, both intervals entirely above zero. The registered criterion is stricter by construction: it asks the margin to exceed the half-width of the regime's *marginal* interval (0.411), which is dominated by market-path uncertainty common to all contestants and is more than twice the margin. No monthly overlay on this window clears such a bar; the three rules' own return-per-volatility intervals have half-widths of 0.44–0.45.
- **Drawdown reduction is where the regime layer is unambiguously different.** Regime 63.9% vs SMA 20.9%, momentum 0.0%, vol targeting 29.7%, with the regime's interval [41.5, 63.9] disjoint from momentum's and vol targeting's.
- **It costs return.** Annualized return 7.92% vs buy-and-hold 14.52% (the rules: 7.85%, 12.78%, 9.37%). The regime overlay sits in cash a lot (mean exposure well below the rules'); its edge is in the ratio and the drawdowns, not in the level of return.
- **Turnover is not the regime's problem at monthly cadence:** 0.97 one-way per year vs SMA 1.90, momentum 1.04, vol targeting 1.12.
- **Tiers 1–3 (the regime's own operating ranges) tell the same story with smaller numbers**, because floors and caps compress every contestant: the regime has the highest return per volatility in each tier and the largest drawdown reduction in tiers 1, 2 and 4; in tier 3 the SMA rule's drawdown reduction is larger (33.1% vs 27.9%, interval [−9.7, 33.1] vs [19.2, 29.3]).
- **On point-in-time inputs (C2's strict series; context, not decision) the picture holds but shrinks**, exactly as C2 predicted: regime return per volatility 0.930 (margin over vol targeting +0.108, paired interval [+0.006, +0.201]), drawdown reduction 51.6% vs 29.7%. The registered rule would give the same verdict — condition 1 fails, condition 2 holds with headroom.
- **Over 2005–2026 (context; includes 2008)** the pure-overlay regime keeps the best return per volatility (0.875 vs 0.657 / 0.728 / 0.724) and the largest drawdown reduction (63.7% vs 51.7 / 38.9 / 57.0; buy-and-hold max drawdown −55.2%), but the rules close much of the gap in the crisis year and the paired return-per-volatility intervals against SMA and momentum include zero.

## 3. Decision-window results (verbatim output of `scripts/c3_regime_vs_rules.py`, `reports/c3_run_stdout.txt`)

```
window 2010-02-01 → 2026-05-21 (4102 sessions, 196 rebalances)

### 1_cap_pres (cash floor 0.25 / slope 0.75 / max 1.00)
| contestant | max DD [90% CI] | ann. return [90% CI] | return/vol [90% CI] | turnover (1-way/yr) | DD reduction vs B&H [90% CI] |
|---|---|---|---|---|---|
| regime | -9.2% [-15.1, -7.3] | 6.33% [3.98, 8.49] | 1.060 [0.649, 1.466] | 0.72 | 64.3% [42.9, 64.4] |
| sma10 | -20.1% [-33.6, -13.8] | 6.36% [2.14, 10.08] | 0.655 [0.214, 1.097] | 1.47 | 22.0% [-42.7, 46.2] |
| tsmom_12_1 | -25.8% [-34.3, -14.2] | 10.06% [5.52, 14.04] | 0.844 [0.432, 1.308] | 0.85 | 0.0% [-7.6, 18.9] |
| vol_target_10 | -18.1% [-26.2, -10.2] | 7.46% [4.11, 10.59] | 0.877 [0.452, 1.325] | 0.84 | 29.8% [15.0, 41.4] |
| buy_and_hold | -25.8% [-35.3, -14.8] | 11.37% [6.79, 15.73] | 0.892 [0.490, 1.337] | 0.13 | — |
paired differences (regime − rule), 90% CI: sma10: RpV [+0.210, +0.633], DDred [+15.2, +92.9] pts; tsmom_12_1: RpV [+0.029, +0.366], DDred [+32.5, +66.0] pts; vol_target_10: RpV [+0.034, +0.328], DDred [+12.1, +40.1] pts

### 2_balanced (cash floor 0.15 / slope 0.70 / max 0.85)
| contestant | max DD [90% CI] | ann. return [90% CI] | return/vol [90% CI] | turnover (1-way/yr) | DD reduction vs B&H [90% CI] |
|---|---|---|---|---|---|
| regime | -13.8% [-20.9, -9.7] | 7.99% [4.89, 10.76] | 0.998 [0.585, 1.416] | 0.67 | 52.5% [35.5, 53.6] |
| sma10 | -21.3% [-35.0, -14.8] | 8.01% [3.25, 12.27] | 0.719 [0.284, 1.159] | 1.37 | 26.5% [-29.4, 47.5] |
| tsmom_12_1 | -29.0% [-38.3, -16.0] | 11.44% [6.29, 16.00] | 0.842 [0.424, 1.311] | 0.79 | 0.0% [-4.9, 18.1] |
| vol_target_10 | -21.9% [-30.7, -12.3] | 9.02% [4.89, 12.77] | 0.869 [0.443, 1.316] | 0.79 | 24.5% [13.4, 35.2] |
| buy_and_hold | -29.0% [-39.3, -16.7] | 12.64% [7.41, 17.67] | 0.873 [0.468, 1.324] | 0.11 | — |
paired differences (regime − rule), 90% CI: sma10: RpV [+0.117, +0.469], DDred [+3.2, +69.3] pts; tsmom_12_1: RpV [+0.007, +0.267], DDred [+26.0, +55.0] pts; vol_target_10: RpV [+0.016, +0.233], DDred [+9.8, +31.4] pts

### 3_aggressive (cash floor 0.10 / slope 0.40 / max 0.50)
| contestant | max DD [90% CI] | ann. return [90% CI] | return/vol [90% CI] | turnover (1-way/yr) | DD reduction vs B&H [90% CI] |
|---|---|---|---|---|---|
| regime | -22.1% [-31.2, -13.6] | 10.67% [6.34, 14.66] | 0.924 [0.513, 1.354] | 0.39 | 27.9% [19.2, 29.3] |
| sma10 | -20.5% [-35.0, -16.2] | 10.68% [5.57, 15.35] | 0.830 [0.412, 1.257] | 0.81 | 33.1% [-9.7, 33.1] |
| tsmom_12_1 | -30.6% [-40.8, -16.9] | 12.60% [7.03, 17.64] | 0.858 [0.451, 1.310] | 0.49 | 0.0% [-2.0, 13.4] |
| vol_target_10 | -26.5% [-36.3, -14.9] | 11.23% [6.30, 15.72] | 0.871 [0.452, 1.320] | 0.48 | 13.2% [8.0, 20.3] |
| buy_and_hold | -30.6% [-41.3, -17.7] | 13.27% [7.71, 18.63] | 0.864 [0.459, 1.317] | 0.09 | — |
paired differences (regime − rule), 90% CI: sma10: RpV [+0.005, +0.198], DDred [-5.4, +31.9] pts; tsmom_12_1: RpV [-0.010, +0.120], DDred [+10.3, +29.6] pts; vol_target_10: RpV [+0.003, +0.098], DDred [+4.3, +16.1] pts

### 4_tactical (cash floor 0.00 / slope 1.00 / max 1.00)
| contestant | max DD [90% CI] | ann. return [90% CI] | return/vol [90% CI] | turnover (1-way/yr) | DD reduction vs B&H [90% CI] |
|---|---|---|---|---|---|
| regime | -12.2% [-20.4, -9.8] | 7.92% [4.74, 10.79] | 0.993 [0.580, 1.402] | 0.97 | 63.9% [41.5, 63.9] |
| sma10 | -26.7% [-43.3, -18.5] | 7.85% [2.16, 12.91] | 0.604 [0.164, 1.055] | 1.90 | 20.9% [-43.7, 45.1] |
| tsmom_12_1 | -33.7% [-44.7, -18.8] | 12.78% [6.61, 18.29] | 0.796 [0.381, 1.273] | 1.04 | -0.0% [-6.8, 18.5] |
| vol_target_10 | -23.7% [-34.2, -13.6] | 9.37% [4.85, 13.61] | 0.822 [0.395, 1.277] | 1.12 | 29.7% [14.3, 40.5] |
| buy_and_hold | -33.7% [-45.2, -19.5] | 14.52% [8.29, 20.59] | 0.848 [0.441, 1.302] | 0.06 | — |
paired differences (regime − rule), 90% CI: sma10: RpV [+0.193, +0.618], DDred [+15.5, +88.8] pts; tsmom_12_1: RpV [+0.008, +0.349], DDred [+32.5, +64.9] pts; vol_target_10: RpV [+0.017, +0.318], DDred [+12.0, +39.5] pts

### Decision (4_tactical, registered rule)
best one-line rule: vol_target_10 (return/vol 0.822); regime 0.993; margin +0.171 vs half-width 0.411 → condition 1 NOT MET
drawdown reduction: regime 63.9% vs best rule 29.7% → condition 2 MET
paired difference (regime − vol_target_10) 90% CI, context: RpV [+0.017, +0.318]
**REGIME FAILS**
```

## 4. Context runs (explicitly outside the decision, registration B12)

Extended window 2005-01-03 → 2026-09-04, same code and constants (`reports/c3_context_stdout.txt`; in the first months of 2005 the SMA and momentum rules lack full history and are treated as invested, per the script's documented default):

```
window 2005-01-03 → 2026-09-04 (5453 sessions, 260 rebalances) — CONTEXT, NOT DECISION

### 1_cap_pres (cash floor 0.25 / slope 0.75 / max 1.00)
| contestant | max DD [90% CI] | ann. return [90% CI] | return/vol [90% CI] | turnover (1-way/yr) | DD reduction vs B&H [90% CI] |
|---|---|---|---|---|---|
| regime | -14.7% [-17.1, -8.1] | 5.82% [3.98, 7.81] | 0.958 [0.639, 1.328] | 0.68 | 66.6% [51.7, 71.7] |
| sma10 | -20.1% [-28.7, -13.5] | 6.75% [3.81, 9.97] | 0.719 [0.397, 1.100] | 1.18 | 54.4% [-0.4, 60.9] |
| tsmom_12_1 | -25.8% [-33.9, -14.5] | 8.72% [5.61, 12.05] | 0.787 [0.469, 1.172] | 0.72 | 41.6% [-1.7, 56.4] |
| vol_target_10 | -18.1% [-27.4, -11.3] | 6.60% [4.22, 9.20] | 0.791 [0.480, 1.179] | 0.78 | 59.0% [24.2, 62.4] |
| buy_and_hold | -44.1% [-47.0, -20.6] | 8.94% [4.68, 13.39] | 0.639 [0.313, 1.061] | 0.12 | — |
paired differences (regime − rule), 90% CI: sma10: RpV [+0.003, +0.441], DDred [+5.4, +58.7] pts; tsmom_12_1: RpV [-0.057, +0.367], DDred [+10.1, +64.8] pts; vol_target_10: RpV [+0.025, +0.295], DDred [+5.7, +36.2] pts

### 2_balanced (cash floor 0.15 / slope 0.70 / max 0.85)
| contestant | max DD [90% CI] | ann. return [90% CI] | return/vol [90% CI] | turnover (1-way/yr) | DD reduction vs B&H [90% CI] |
|---|---|---|---|---|---|
| regime | -23.4% [-25.5, -11.7] | 7.00% [4.48, 9.72] | 0.843 [0.526, 1.232] | 0.64 | 52.0% [42.6, 59.2] |
| sma10 | -21.3% [-31.9, -15.1] | 7.88% [4.48, 11.65] | 0.727 [0.407, 1.113] | 1.11 | 56.3% [4.8, 59.9] |
| tsmom_12_1 | -29.0% [-38.3, -16.7] | 9.68% [6.01, 13.46] | 0.761 [0.450, 1.148] | 0.67 | 40.6% [-0.4, 54.0] |
| vol_target_10 | -24.0% [-33.4, -14.4] | 7.71% [4.67, 10.98] | 0.742 [0.424, 1.139] | 0.73 | 50.7% [20.7, 53.2] |
| buy_and_hold | -48.8% [-52.2, -23.3] | 9.79% [4.94, 14.88] | 0.615 [0.288, 1.040] | 0.09 | — |
paired differences (regime − rule), 90% CI: sma10: RpV [-0.082, +0.292], DDred [-6.1, +42.5] pts; tsmom_12_1: RpV [-0.115, +0.247], DDred [+0.5, +52.5] pts; vol_target_10: RpV [-0.006, +0.198], DDred [+2.2, +28.8] pts

### 3_aggressive (cash floor 0.10 / slope 0.40 / max 0.50)
| contestant | max DD [90% CI] | ann. return [90% CI] | return/vol [90% CI] | turnover (1-way/yr) | DD reduction vs B&H [90% CI] |
|---|---|---|---|---|---|
| regime | -37.9% [-40.4, -17.7] | 8.70% [4.91, 12.58] | 0.704 [0.374, 1.107] | 0.37 | 25.6% [22.4, 32.4] |
| sma10 | -33.1% [-40.1, -18.7] | 9.25% [5.16, 13.54] | 0.702 [0.381, 1.099] | 0.67 | 35.0% [8.2, 40.9] |
| tsmom_12_1 | -35.5% [-43.9, -19.7] | 10.23% [5.95, 14.81] | 0.706 [0.393, 1.091] | 0.43 | 30.5% [-0.0, 39.0] |
| vol_target_10 | -38.1% [-43.7, -19.3] | 9.09% [5.12, 13.29] | 0.674 [0.357, 1.064] | 0.44 | 25.3% [11.4, 30.9] |
| buy_and_hold | -51.0% [-54.6, -24.6] | 10.21% [5.04, 15.63] | 0.604 [0.277, 1.029] | 0.08 | — |
paired differences (regime − rule), 90% CI: sma10: RpV [-0.087, +0.098], DDred [-10.9, +17.0] pts; tsmom_12_1: RpV [-0.107, +0.096], DDred [-9.5, +27.9] pts; vol_target_10: RpV [-0.017, +0.076], DDred [-0.4, +14.6] pts

### 4_tactical (cash floor 0.00 / slope 1.00 / max 1.00)
| contestant | max DD [90% CI] | ann. return [90% CI] | return/vol [90% CI] | turnover (1-way/yr) | DD reduction vs B&H [90% CI] |
|---|---|---|---|---|---|
| regime | -20.1% [-23.4, -11.1] | 7.09% [4.63, 9.78] | 0.875 [0.559, 1.246] | 0.92 | 63.7% [50.2, 70.5] |
| sma10 | -26.7% [-37.9, -18.0] | 8.26% [4.32, 12.62] | 0.657 [0.333, 1.046] | 1.53 | 51.7% [-0.9, 58.8] |
| tsmom_12_1 | -33.7% [-44.1, -19.3] | 10.86% [6.58, 15.42] | 0.728 [0.413, 1.121] | 0.88 | 38.9% [-2.4, 54.5] |
| vol_target_10 | -23.7% [-35.9, -15.1] | 8.10% [4.89, 11.63] | 0.724 [0.411, 1.115] | 1.04 | 57.0% [22.9, 60.3] |
| buy_and_hold | -55.2% [-59.0, -27.1] | 11.02% [5.21, 17.13] | 0.583 [0.257, 1.012] | 0.05 | — |
paired differences (regime − rule), 90% CI: sma10: RpV [-0.020, +0.419], DDred [+5.3, +57.6] pts; tsmom_12_1: RpV [-0.083, +0.340], DDred [+10.0, +63.9] pts; vol_target_10: RpV [+0.007, +0.282], DDred [+5.8, +35.9] pts
```

Registered window, regime contestant on C2's strict point-in-time series (`reports/c3_context_pit_stdout.txt`), tier 4 only:

```
window 2010-02-01 → 2026-05-21 (4102 sessions, 196 rebalances) — CONTEXT, NOT DECISION
### 4_tactical (cash floor 0.00 / slope 1.00 / max 1.00)
| contestant | max DD [90% CI] | ann. return [90% CI] | return/vol [90% CI] | turnover (1-way/yr) | DD reduction vs B&H [90% CI] |
|---|---|---|---|---|---|
| regime | -16.3% [-24.1, -10.4] | 7.75% [4.41, 10.68] | 0.930 [0.499, 1.379] | 0.86 | 51.6% [39.7, 55.9] |
| sma10 | -26.7% [-43.3, -18.5] | 7.85% [2.16, 12.91] | 0.604 [0.164, 1.055] | 1.90 | 20.9% [-43.7, 45.1] |
| tsmom_12_1 | -33.7% [-44.7, -18.8] | 12.78% [6.61, 18.29] | 0.796 [0.381, 1.273] | 1.04 | -0.0% [-6.8, 18.5] |
| vol_target_10 | -23.7% [-34.2, -13.6] | 9.37% [4.85, 13.61] | 0.822 [0.395, 1.277] | 1.12 | 29.7% [14.3, 40.5] |
| buy_and_hold | -33.7% [-45.2, -19.5] | 14.52% [8.29, 20.59] | 0.848 [0.441, 1.302] | 0.06 | — |
paired differences (regime − rule), 90% CI: sma10: RpV [+0.103, +0.583], DDred [+5.6, +87.6] pts; tsmom_12_1: RpV [+0.011, +0.232], DDred [+32.3, +55.2] pts; vol_target_10: RpV [+0.006, +0.201], DDred [+10.2, +30.8] pts
```

## 5. Implementation notes and corrections (none touch a registered constant)

- The script's first invocation stopped on a `KeyError` (the tier parameters live under `tier_specs`, not `tiers` in `config.json`) before any computation; fixed in f11a6eb.
- The pure buy-and-hold leg identified its initial purchase by "first session of the window", which is a rebalance day in the registered window (2010-02-01 is a month start) but not in the context window (2005-01-03), so tier-4 buy-and-hold in the first context run never bought. Fixed to "first rebalance of the run"; the decision-window output was re-generated and is byte-identical before and after the fix (checked with `diff`).
- A context-only input override (`C3_REGIME_CSV`) was added for the point-in-time run; the decision path refuses it. The decision run was re-generated after this edit and is again byte-identical.
- Regime input provenance: `data/regime_v2_daily.csv` blob 61381af1c160 at HEAD c39e2aa (as-published inputs, C2's "rev" variant).

## 6. Registered specification, restated verbatim (`reports/c3_registration.md` at c39e2aa)

# C3 registration — Regime index versus one-line rules (frozen before the run)

Registered 2026-09-08, before any C3 computation was run. Per the order, *"No metric, window, rule parameter, or threshold in this section may be changed after the run begins; a change requires a new registration with a stated reason and both results reported."* The results report must restate this section verbatim; the diff must be empty.

## A. The order's text (verbatim, C3 of "Governance Decisions and the Retirement Tests", 9 Sept 2026)

> C3. Regime index versus one-line rules, pre-registered (one week)
> This is the test that can retire the core of the system, and it is registered here before any of it is run.
> Contestants: (i) the 24-indicator regime index with the existing tier sizing; (ii) ten-month simple moving average on the index, monthly, fully invested above and in cash below; (iii) time-series momentum, sign of trailing twelve-month return excluding the last month, monthly; (iv) volatility targeting, exposure scaled to a 10 percent annualized target using 60-day realized volatility, monthly cap at 100 percent. Benchmark: buy-and-hold on the same index. Window: the full backtest history, on C2's as-published inputs, net of C1's costs.
> Metrics, fixed now: maximum drawdown; annualized return; return per unit of volatility; turnover; and drawdown reduction relative to buy-and-hold. Uncertainty: block bootstrap, 1,000 resamples, 60-day blocks, 90 percent intervals on every metric.
> Decision rule, fixed now: the regime index earns its place only if its after-cost return-per-volatility exceeds the best one-line rule by a margin larger than the bootstrap interval's half-width, and its drawdown reduction is at least as large. If it fails either condition, the regime layer is demoted to a context panel and tier sizing switches to the winning one-line rule; the indicator panel remains as information. If it passes, the margin is the system's first quantified evidence of edge and goes into the paper's abstract. No metric, window, rule parameter, or threshold in this section may be changed after the run begins; a change requires a new registration with a stated reason and both results reported.

## B. Implementation registration (every constant and convention, fixed now)

**B1. The index.** SPY, dividend-adjusted daily close from `data/source/sector_etfs.parquet` column `spy` (the engine's own benchmark series). Daily return = close-to-close percentage change. Cash earns the effective federal funds rate (`data/source/fred_indicators.parquet` column `effr`, forward-filled, missing → 0) at rate/252/100 per session, exactly as the engine does.

**B2. Window.** The engine's full backtest history as served in `data/backtest_equity_curves.csv`, first to last session: **2010-02-01 → 2026-05-21** (4,102 sessions). (`system_settings.backtest_start` is 2010-01-04; the served curves begin with the engine's first complete month, 2010-02-01, and end at `backtest_end` 2026-05-21.) The script reads the served curves' first and last dates, asserts they equal these registered dates, and stops if they differ. Signals may use price history before the window (SPY from 2005-01-03); performance is measured inside it only.

**B3. Regime input.** `data/regime_v2_daily.csv` column `R_full` — the as-published (revised-input) series, C2's "rev" variant, as committed at 50c9986. The point-in-time series is not used in C3 (the order specifies as-published inputs); C2's report is cited as context only.

**B4. Rebalance calendar.** Monthly, on the first trading session of each calendar month inside the window (the engine's calendar), identical for every contestant. Positions are set at that session's close and earn the next session's return onward.

**B5. Information timing.** Every signal — including the regime index — uses data through the close of the session *before* the rebalance session (t−1). This is applied uniformly so no contestant sees the rebalance day's close.

**B6. Contestant signals** (exposure e ∈ [0, 1] before tier mapping):
- (i) Regime: R = last available `R_full` at t−1; cash = clamp(floor + R × slope, floor, max); e = 1 − cash, using the tier's existing parameters (B7).
- (ii) Ten-month SMA: month-end closes = SPY close on the last session of each calendar month. Let P_m be the most recent month-end close before the rebalance session and SMA10 = mean of the last 10 month-end closes including P_m. e = 1 if P_m > SMA10, else 0.
- (iii) Time-series momentum 12-1: e = 1 if P_{m−1} / P_{m−12} − 1 > 0 (return from twelve month-ends ago to one month-end ago, excluding the most recent month), else 0.
- (iv) Volatility targeting: σ = sample standard deviation of the last 60 daily log returns through t−1, × √252. e = min(1.0, 0.10 / σ).
- Benchmark: e = 1 (buy-and-hold; no monthly trade, so zero turnover in the pure overlay).

**B7. Tier mapping.** Each contestant is evaluated inside each tier's existing cash range (`config.json`): 1_cap_pres floor 0.25 / slope 0.75 / max 1.00; 2_balanced 0.15 / 0.70 / 0.85; 3_aggressive 0.10 / 0.40 / 0.50; 4_tactical 0.00 / 1.00 / 1.00. The regime contestant uses the formula in B6(i). A rule's exposure maps as cash = floor + (1 − e_rule) × (max − floor). The benchmark in a tier holds cash = floor (rebalanced monthly to that constant); in tier 4 it is SPY buy-and-hold. **The decision rule (B10) is evaluated on tier 4**, the only tier whose sizing spans the full 0–100% range so that the regime index maps R_full directly and the rules map exposure directly; tiers 1–3 are reported in full as the regime's own operating ranges.

**B8. Costs.** C1's model: 10 bps one-way (3 bps half-spread + 7 bps impact) applied to one-way turnover in NAV-weight space at every rebalance, |e_new − w_pre| where w_pre is the drifted equity share just before the rebalance; the engine's convention, applied identically to all contestants. The initial position at the first rebalance is charged from all-cash, as in the engine.

**B9. Metrics** (after cost, on the window):
- maximum drawdown: min over t of NAV_t / max_{s≤t} NAV_s − 1;
- annualized return: (NAV_end / NAV_start)^(252/N) − 1;
- return per unit of volatility: annualized return ÷ (standard deviation of daily returns × √252);
- turnover: mean annual one-way turnover, Σ|e_new − w_pre| ÷ (N/252);
- drawdown reduction relative to buy-and-hold: 1 − maxDD_contestant / maxDD_benchmark, benchmark as defined in B7 for that tier.

**B10. Uncertainty and decision.** Circular block bootstrap of the *daily net return series* of all strategies jointly (same block indices for every strategy in a resample, preserving the pairing): block length 60 sessions, 1,000 resamples, seed 20260909, each resample of length N. Every metric except turnover (deterministic) is recomputed on each resample; the 90% interval is the 5th–95th percentile. Decision on tier 4: best one-line rule = the rule with the highest point-estimate after-cost return-per-volatility among (ii)–(iv). Margin = return-per-volatility(regime) − return-per-volatility(best rule), point estimates. Half-width = (95th − 5th percentile) / 2 of the regime contestant's own return-per-volatility interval. **The regime index passes only if margin > half-width AND drawdown reduction(regime) ≥ drawdown reduction(best rule), point estimates.** The 90% interval of the paired difference (regime − best rule) is reported as context and is not part of the rule.

**B11. Outputs.** `scripts/c3_regime_vs_rules.py` writes `data/c3_results.json` (cadence on_change) and per-tier NAV paths under `data/c3/`; the results report `reports/retirement_test_C3_regime_vs_rules.md` restates this section verbatim and shows the empty diff.

**B12. Context runs, explicitly outside the decision.** One additional run on the longer window 2005-01-03 → 2026-09-04 (full regime-index history, includes 2008) is reported under a "context, not decision" heading with the same code and constants. It cannot alter the decision.

## 7. Diff of section 6 against the committed registration

```
(empty — section 6 is byte-identical to reports/c3_registration.md at c39e2aa)
```

## 8. Referee before / after (verbatim, `scripts/audit_nightly.py`)

Before (`reports/audit_after_C2.txt`, the state C3 started from):

```
last trading session: 2026-09-04
[HIGH    ] governance:coverage          5_werner: unclassified share 16% > 15%
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ANET review_by 2026-08-18 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ETN review_by 2026-08-14 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override GD review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override MSFT review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override VRT review_by 2026-08-12 passed (decay should be active)
[MEDIUM  ] status:opaque                tournament failure_reason does not name the failing assertion
[INFO    ] tournament:freshness         loco_cv_results.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         ml_indicator_weights.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_loadings.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_variance_explained.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_v3_correlation.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           watchlist_top30.csv: no date axis found (static config?)

16 findings; 0 CRITICAL
```

After (`reports/audit_after_C3.txt`):

```
last trading session: 2026-09-04
[HIGH    ] governance:coverage          5_werner: unclassified share 16% > 15%
[HIGH    ] governance:review_overdue    visibility override AMZN review_by 2026-08-13 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ANET review_by 2026-08-18 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override ETN review_by 2026-08-14 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override GD review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override MSFT review_by 2026-08-12 passed (decay should be active)
[HIGH    ] governance:review_overdue    visibility override VRT review_by 2026-08-12 passed (decay should be active)
[MEDIUM  ] status:opaque                tournament failure_reason does not name the failing assertion
[INFO    ] tournament:freshness         loco_cv_results.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         ml_indicator_weights.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_loadings.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         pca_variance_explained.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         regime_v3_correlation.csv: no date axis found (static config?)
[INFO    ] tournament:freshness         scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           scored_universe.csv: no date axis found (static config?)
[INFO    ] screener:freshness           watchlist_top30.csv: no date axis found (static config?)

16 findings; 0 CRITICAL
```

Finding lines are identical; 0 CRITICAL. The C3 artifacts (`data/c3_results*.json` declare `cadence: on_change`; NAV paths under `data/c3/` are outside the scan and git-ignored) add nothing.

## 9. Commits

| commit | item |
|---|---|
| c39e2aa | [C3][registration] frozen spec + script, committed before any run |
| f11a6eb | [C3] script: config key fix (pre-computation) |
| (this) | [C3][results] buy-and-hold first-rebalance fix, context input override, results JSONs, stdout captures, this report, referee after |

## 10. Decisions for Werner (nothing applied)

The order pre-commits a consequence and also provides the only alternative to it. Both are recorded here as they stand; neither has been executed.

1. **Apply the registered consequence.** Demote the regime layer to a context panel; switch tier sizing to 10% volatility targeting (60-day realized, cap 100%, monthly) mapped into each tier's existing cash range as in registration B7; keep the indicator panel as information. This is a served-behaviour change to both the dashboard and the live tier NAV computation and needs a written go with the change list pinned to this report. If given, the switch is implemented behind the same run guard, with the current sizing archived as a vintage and the leaderboard carrying a model-change note for 30 sessions, as B1 did for v4.
2. **Re-register with a stated reason and report both results.** The order allows a change to the rule only through a new registration that names its reason, with both outcomes reported. The material fact for that judgment is in section 2: under the registered criterion no monthly overlay could pass on this window, while the paired-difference intervals, which the registration itself defined as context, are entirely positive for both metrics against every rule in the pure overlay. Whether that is a reason to re-register is a governance call, not a modelling one; I have not made it.
3. **C4** (point-in-time fundamentals purchase) was deferred by the order until C3 reports. This is that report. The order's own framing: if the regime layer is the only component with an edge, the fundamental sleeve's remaining value is a clean confirmation of the null for the paper.
