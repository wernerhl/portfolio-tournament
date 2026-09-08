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
