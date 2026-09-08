# Retirement test C3 — Regime index versus one-line rules (pre-registered; two verdicts of record)

**Order** (Governance Decisions and the Retirement Tests, 9 Sept 2026, C3): *"This is the test that can retire the core of the system, and it is registered here before any of it is run."* Registration v1 (`reports/c3_registration.md`) was committed at **c39e2aa** (2026-09-08 06:52 UTC) before the first computation. Registration v2 (`reports/c3_registration_v2.md`) was issued by the Decision Memo of 9 September 2026 **after the v1 result was known**, changes one condition, retains the v1 verdict, and carries the amendment paragraph. This report carries both verdicts; section 7 restates both registrations verbatim and section 8 shows the mechanical diffs (v1 against its commit: empty; v2 against its file: empty).

## 1. Verdicts of record

**Under registration v1 — the regime index FAILS.** Tier 4 (pure overlay: cash 0–100%, SPY, monthly, net of 10 bps one-way), 2010-02-01 → 2026-05-21, revised inputs:

| | regime index | best one-line rule (10% vol targeting) | v1 condition |
|---|---|---|---|
| after-cost return per unit of volatility | 0.993 | 0.822 | margin +0.171 must exceed the half-width of the regime's own 90% interval, 0.411 → **not met** |
| drawdown reduction vs buy-and-hold | 63.9% | 29.7% | regime ≥ rule → **met** |

**Under registration v2 — the regime index PASSES.** Same run, same resamples, same best rule:

| | value | v2 condition |
|---|---|---|
| paired difference, regime − vol targeting, return per volatility, 90% interval | [+0.017, +0.318] | lies entirely above zero → **met** |
| drawdown reduction vs buy-and-hold | 63.9% vs 29.7% | regime ≥ rule (unchanged) → **met** |

**The amendment paragraph (Decision Memo §1, verbatim; travels with the v2 verdict everywhere it appears):**

> The rule was defective, and the defect is objective rather than a matter of taste. Condition 1 compared a point-estimate margin to the half-width of the regime's own marginal bootstrap interval. That half-width (0.411) is dominated by market-path uncertainty shared by every contestant, because all of them hold the same index most of the time. The report shows no monthly overlay on this window could clear it: the rules' own half-widths are 0.44 to 0.45, larger than any plausible margin between two overlays. A test that no contestant can pass has no discriminating power. The correct statistic for comparing two strategies on one history is the paired difference, computed on the same resampled paths, which cancels the shared variance. The registration itself required the paired difference to be reported, as context.
>
> The asymmetry must be stated: had the regime passed under v1, this defect would not have been examined. The amendment is prompted by the result. That is exactly the situation the amendment clause exists for, and it is honest only if the v1 verdict stays on record and this paragraph travels with the v2 verdict everywhere it appears.

**Context, reported alongside and binding on what may be claimed (Decision Memo §2, verbatim):**

> Point-in-time inputs (C2's strict series): paired return-per-volatility interval [+0.006, +0.201], lower bound at zero for practical purposes; drawdown reduction 51.6 percent against 29.7. On real-time information the regime's drawdown advantage is intact and its return-per-volatility advantage is not distinguishable from nothing.
> Crisis-inclusive window (2005-01-03 to 2026-09-04): drawdown reduction 63.7 percent against vol targeting's 57.0; paired return-per-volatility intervals against the moving-average and momentum rules include zero, against vol targeting [+0.007, +0.282]. In 2008, a one-line volatility-targeting rule captured most of the protection the regime layer provides.
> Cost of the overlay: annualized return 7.92 percent against buy-and-hold's 14.52 over the decision window. The regime overlay is insurance with a substantial premium; its value is the ratio and the drawdowns, not the level of return.
> Tier 3: the moving-average rule's drawdown reduction exceeds the regime's (33.1 against 27.9). The regime does not dominate in every operating range.

**Consequence.** The v1 consequence (demotion; tier sizing to the winning rule) is not applied: the memo's §4 records why ("procedure over outcome, the ledger's Failure 11"). The regime layer keeps its role. The combination hypothesis raised by the context runs is registered as C5 (`reports/c5_registration.md`), not run, not adopted.

## 2. What the numbers say beyond the rules

- **The regime beats every rule on both metrics in the pure overlay, and the paired bootstrap says so at 90% coverage.** Against vol targeting the return-per-volatility difference is [+0.017, +0.318] and the drawdown-reduction difference [+12.0, +39.5] points. The v1 criterion asked the margin to exceed the half-width of the regime's *marginal* interval (0.411), more than twice the margin; the three rules' own return-per-volatility intervals have half-widths of 0.44–0.45.
- **Drawdown reduction is where the regime layer is unambiguously different.** Regime 63.9% vs SMA 20.9%, momentum 0.0%, vol targeting 29.7%, with the regime's interval [41.5, 63.9] disjoint from momentum's and vol targeting's.
- **It costs return.** Annualized return 7.92% vs buy-and-hold 14.52% (the rules: 7.85%, 12.78%, 9.37%). The regime overlay sits in cash a lot; its edge is in the ratio and the drawdowns, not in the level of return.
- **Turnover is not the regime's problem at monthly cadence:** 0.97 one-way per year vs SMA 1.90, momentum 1.04, vol targeting 1.12.
- **Tiers 1–3 tell the same story with smaller numbers**, because floors and caps compress every contestant: the regime has the highest return per volatility in each tier and the largest drawdown reduction in tiers 1, 2 and 4; in tier 3 the SMA rule's drawdown reduction is larger (33.1% vs 27.9%).
- **On point-in-time inputs the picture holds but shrinks**, as C2 predicted: regime return per volatility 0.930 (margin over vol targeting +0.108, paired interval [+0.006, +0.201]), drawdown reduction 51.6% vs 29.7%. Under v2 the paired interval's lower bound is +0.006: met on the letter, "at zero for practical purposes" on the substance, which is why the memo binds the claim to the point-in-time sentence.
- **Over 2005–2026 (includes 2008)** the pure-overlay regime keeps the best return per volatility (0.875 vs 0.657 / 0.728 / 0.724) and the largest drawdown reduction (63.7% vs 51.7 / 38.9 / 57.0; buy-and-hold max drawdown −55.2%), but vol targeting closes most of the gap in the crisis year and the paired return-per-volatility intervals against SMA and momentum include zero.

## 3. Decision-window results (verbatim output of `scripts/c3_regime_vs_rules.py`, `reports/c3_run_stdout.txt`; the v1 block is byte-identical to the 8 September run, the v2 block is appended)

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

### Decision under registration v2 (amended 2026-09-09; v1 verdict above stays on record)
condition 1 (v2): paired difference regime − vol_target_10 in return/vol, 90% CI [+0.017, +0.318] entirely above zero → MET
condition 2 (unchanged): drawdown reduction regime 63.9% vs best rule 29.7% → MET
**REGIME PASSES under v2** (v1 verdict: FAILS; amendment disclosed in reports/c3_registration_v2.md §C)
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
- The pure buy-and-hold leg identified its initial purchase by "first session of the window", which is a rebalance day in the registered window (2010-02-01 is a month start) but not in the context window (2005-01-03), so tier-4 buy-and-hold in the first context run never bought. Fixed to "first rebalance of the run"; the decision-window output was re-generated and is byte-identical before and after the fix.
- A context-only input override (`C3_REGIME_CSV`) was added for the point-in-time run; the decision path refuses it. The decision run was re-generated after this edit and is again byte-identical.
- The v2 evaluation (`decision_v2`) was added on 9 September on the same run; the v1 portion of the output is byte-identical before and after (checked with `diff`).
- Regime input provenance: `data/regime_v2_daily.csv` blob 61381af1c160 at HEAD c39e2aa (as-published inputs, C2's "rev" variant).

## 6. Registration v1, restated verbatim (`reports/c3_registration.md` at c39e2aa)

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

## 7. Registration v2, restated verbatim (`reports/c3_registration_v2.md`)

# C3 registration v2 — amended 9 September 2026 (one change only)

This document amends `reports/c3_registration.md` (v1, committed c39e2aa before any run). It is issued by the Decision Memo of 9 September 2026 after the v1 result was known. **The v1 verdict stays on record and is never removed from the paper, the dashboard, or the ledger; the amendment paragraph in section C travels with the v2 verdict everywhere it appears.**

## A. The v1 verdict of record (retained verbatim from `reports/retirement_test_C3_regime_vs_rules.md`)

> **The regime index fails the registered rule.** On tier 4 (the pure overlay: cash 0–100%, SPY, monthly, net of 10 bps one-way), over 2010-02-01 → 2026-05-21:
>
> | | regime index | best one-line rule (10% vol targeting) | condition |
> |---|---|---|---|
> | after-cost return per unit of volatility | 0.993 | 0.822 | margin +0.171 must exceed the half-width of the regime's own 90% interval, 0.411 → **not met** |
> | drawdown reduction vs buy-and-hold | 63.9% | 29.7% | regime ≥ rule → **met** |

## B. Registration v2 (Decision Memo, section 2, verbatim)

> All of v1 stands except condition 1, which is replaced as follows. Condition 1: the 90 percent interval of the paired bootstrap difference (regime minus best rule, same resampled paths as v1's B10) in after-cost return per unit of volatility lies entirely above zero. Condition 2 unchanged: drawdown reduction of the regime is at least that of the best rule, point estimates. Consequence unchanged. Window, contestants, metrics, bootstrap, seed, cost model unchanged. Reason for amendment: v1's statistic admitted no passing contestant on this window and confounded strategy differences with shared market-path variance; the paired difference is the correct comparison and was already registered as a reported quantity.
>
> Verdict under v2, decision window (tier 4, 2010-02-01 to 2026-05-21, revised inputs, net of costs): condition 1 met, paired interval [+0.017, +0.318]; condition 2 met. Pass.
>
> Context, reported alongside and binding on what may be claimed:
> Point-in-time inputs (C2's strict series): paired return-per-volatility interval [+0.006, +0.201], lower bound at zero for practical purposes; drawdown reduction 51.6 percent against 29.7. On real-time information the regime's drawdown advantage is intact and its return-per-volatility advantage is not distinguishable from nothing.
> Crisis-inclusive window (2005-01-03 to 2026-09-04): drawdown reduction 63.7 percent against vol targeting's 57.0; paired return-per-volatility intervals against the moving-average and momentum rules include zero, against vol targeting [+0.007, +0.282]. In 2008, a one-line volatility-targeting rule captured most of the protection the regime layer provides.
> Cost of the overlay: annualized return 7.92 percent against buy-and-hold's 14.52 over the decision window. The regime overlay is insurance with a substantial premium; its value is the ratio and the drawdowns, not the level of return.
> Tier 3: the moving-average rule's drawdown reduction exceeds the regime's (33.1 against 27.9). The regime does not dominate in every operating range.

## C. The amendment paragraph (Decision Memo, section 1, verbatim; travels with the v2 verdict)

> The rule was defective, and the defect is objective rather than a matter of taste. Condition 1 compared a point-estimate margin to the half-width of the regime's own marginal bootstrap interval. That half-width (0.411) is dominated by market-path uncertainty shared by every contestant, because all of them hold the same index most of the time. The report shows no monthly overlay on this window could clear it: the rules' own half-widths are 0.44 to 0.45, larger than any plausible margin between two overlays. A test that no contestant can pass has no discriminating power. The correct statistic for comparing two strategies on one history is the paired difference, computed on the same resampled paths, which cancels the shared variance. The registration itself required the paired difference to be reported, as context.
>
> The asymmetry must be stated: had the regime passed under v1, this defect would not have been examined. The amendment is prompted by the result. That is exactly the situation the amendment clause exists for, and it is honest only if the v1 verdict stays on record and this paragraph travels with the v2 verdict everywhere it appears.

## D. Mechanics

`scripts/c3_regime_vs_rules.py` evaluates both rules on the same run: `decision` (v1, unchanged code path) and `decision_v2` (paired 90% interval of return-per-volatility, regime minus best rule, lower bound > 0; drawdown-reduction condition unchanged). The best rule is the same object in both (highest point-estimate return-per-volatility among the three rules). Bootstrap resamples, seed, block length, window, costs and contestants are those of v1; the v1 output is byte-identical before and after the addition of the v2 evaluation, and the results report shows that check.

## 8. Mechanical diffs

Section 6 against `reports/c3_registration.md` at c39e2aa:

```
(empty — section 6 is byte-identical to reports/c3_registration.md at c39e2aa)
```

Section 7 against `reports/c3_registration_v2.md` on disk:

```
(empty — section 7 is byte-identical to reports/c3_registration_v2.md)
```

## 9. Referee before / after (verbatim, `scripts/audit_nightly.py`)

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

Finding lines are identical; 0 CRITICAL. The C3 artifacts add nothing (`data/c3_results*.json` declare `cadence: on_change`; NAV paths under `data/c3/` are outside the scan and git-ignored).

## 10. Commits

| commit | item |
|---|---|
| c39e2aa | [C3][registration] frozen spec v1 + script, committed before any run |
| f11a6eb | [C3] script: config key fix (pre-computation) |
| 14e969a | [C3][results] v1 verdict, buy-and-hold first-rebalance fix, context runs, referee after |
| 5f18559 | [C3][report] cross-reference fix |
| (memo batch) | [C3-v2] registration v2, `decision_v2` evaluation, this report regenerated with both verdicts |

## 11. Decisions taken by the Decision Memo of 9 September 2026 (recorded, not made here)

1. v1 verdict stays on record; registration v2 issued in the open with the amendment paragraph; v2 verdict: pass.
2. Demotion not applied; regime layer keeps its role.
3. C5 (regime plus vol targeting versus each alone, paired criterion) registered only; not run until told.
4. The paper's abstract carries the deflated sentence of the memo's §3; the words "edge", "alpha" and "40 to 75 percent" do not appear.
