# Decision memo: the crisis-channel vote in the headline

Order of 1 October 2026, item [R2]. Prepared 1 October 2026 for the operator's decision. Nothing in this memo has been implemented. No served file, no script and no line of `app.js` was changed to produce it.

## Summary

- On 30 September the headline reads **DEFENSIVE**. The regime index reads LOW RISK (R_full 0.314). Early warning reads CLEAR (R_lead 0.283). The only reason for DEFENSIVE is the crisis vote: two channels, HY OAS and DXY, are classed "crisis".
- Both are extremes only against their own past year. On longer scales they are ordinary. HY OAS: z +1.27 on 252 sessions, −0.05 on 756 sessions, 47th percentile of its stored history. DXY: z +1.99 on 252, −0.13 on 756, 70th percentile of ten years.
- The vote is nearly always on. Across 5,427 sessions since April 2005, at least one channel was classed crisis on 97.0% of sessions. Four or more were classed crisis on 54.9%.
- The vote alone raised the headline above the index's own reading on 4,632 sessions (85.4%). In the last 252 sessions it did so on 232 (92.1%). On the 72 served sessions it did so on 54.
- Headline changes over the full history: A (keep the vote) 401, B (ten-year filter) 404, C (no vote) 245. Last 252 sessions: 36, 37 and 15.
- The advisor recommends C. B is the fallback if a tail vote is wanted. Section 4 gives the reasons.

## 1. Today's state (finding F3)

The served snapshot for session 30 September (`data/regime_indicators.json`, nightly commit 2082b01, 1 Oct 04:22 UTC):

| field | value |
|---|---|
| R_full | 0.3143 → regime **LOW RISK** (hysteresis corridor; R has not reached the 0.32 entry threshold) |
| R_lead | 0.2830 → early warning **CLEAR** |
| n_crisis | **2** (hy_oas, dxy) |
| complacency_flag | true (SKEW 141.92 > 140 and VIX 16.34 < 17) |
| headline (A, as served) | **DEFENSIVE**, from `n_crisis >= 1` alone |

Channels classed crisis on 30 September:

| channel | direction | value | Φ(z) | z, 252 sessions | z, 756 sessions | ten-year percentile, risky direction | observations in the window (first date) |
|---|---|---|---|---|---|---|---|
| HY OAS | higher | 3.08% (308 bp) | 0.898 | +1.270 | −0.053 | **47.3** | 846 (2023-06-05) |
| DXY | higher | 101.45 | 0.977 | +1.992 | −0.131 | **70.1** | 2,533 (2016-09-30) |

The HY figure is not a ten-year figure. The stored HY OAS series starts on 5 June 2023, so its "ten-year" window is 3.3 years. No longer HY OAS history exists in the repository.

The previous session, 29 September (nightly commit e478308), also had n_crisis 2 on the same channels:

| channel | served value | served z, 252 | z, 756 (served value) | ten-year percentile (served value) | today's panel value for 29 Sept | z 252 / z 756 / percentile on today's panel |
|---|---|---|---|---|---|---|
| HY OAS | 3.02% | +0.929 | −0.204 | 43.9 | 3.08% (the 29 Sept print, published T+1) | +1.281 / −0.057 / 47.3 |
| DXY | 101.33 | +1.904 | −0.171 | 69.2 | 101.37 | +1.943 / −0.157 / 69.6 |

What each option would have shown on these two sessions:

| session | A (keep the vote) | B (ten-year filter) | C (no vote) | B with complacency rule | C with complacency rule |
|---|---|---|---|---|---|
| 29 Sept | DEFENSIVE | DEPLOY | DEPLOY | COMPLACENT | COMPLACENT |
| 30 Sept | DEFENSIVE | DEPLOY | DEPLOY | COMPLACENT | COMPLACENT |

Under B neither channel counts: both are below 90 on the ten-year scale. Under B or C the complacency rule then applies, because the headline would be at rank 0 and the flag is on. **Under B or C, today's headline would read COMPLACENT, not DEPLOY.** Under plain bands, without the corridor, R_full 0.314 would read ELEVATED and the headline CAUTIOUS. The corridor is the served convention, so the tables use it.

## 2. History

### Sessions covered

| source | sessions | dates |
|---|---|---|
| served snapshot | 72 | 2026-06-02 to 2026-09-30 |
| revised (recomputed) | 5,355 | 2005-04-05 to 2026-09-28 |
| total | 5,427 | every session with an R_full |

Within the served period (84 sessions from 2 June), 12 sessions have no served snapshot. They are 24 June, 26 June, 27 August, and 16–28 September (the nightly outage, nine sessions). Those 12 are revised.

### Sessions raised by the vote alone

"Raised" means the option-A headline sits above the higher of the regime label and the early-warning label, so the vote alone set it.

| subset | sessions | raised to DEFENSIVE (n_crisis ≥ 1) | raised to CRISIS (n_crisis ≥ 4) | raised, total | share |
|---|---|---|---|---|---|
| all | 5,427 | 2,195 | 2,437 | 4,632 | 85.4% |
| served | 72 | 49 | 5 | 54 | 75.0% |
| revised | 5,355 | 2,146 | 2,432 | 4,578 | 85.5% |
| last 252 sessions | 252 | 182 | 50 | 232 | 92.1% |

Why the count is so high: a channel is "crisis" when Φ(z) ≥ 0.80, which means z ≥ 0.84 against its own trailing 252 sessions. That is the top fifth of its own past year, which a channel reaches on roughly one session in five. With 23 channels, at least one is almost always there. Across all sessions, n_crisis was ≥ 1 on 97.0% and ≥ 4 on 54.9%; the median was 4.

### Channels responsible: served sessions (54 raised sessions)

| channel | direction | raised sessions where crisis | sole crisis channel | ten-year percentile, risky direction: median | min | max | sessions ≥ 90 |
|---|---|---|---|---|---|---|---|
| dxy | higher | 44 | 13 | 67.4 | 61.0 | 70.7 | 0 |
| skew | lower | 15 | 7 | 47.0 | 34.1 | 74.9 | 0 |
| anfci | higher | 14 | 0 | 63.3 | 62.4 | 68.0 | 0 |
| realized_vol | higher | 9 | 0 | 72.1 | 61.2 | 72.6 | 0 |
| spx_drawdown | lower | 8 | 0 | 58.3 | 56.0 | 64.5 | 0 |
| vix_term | higher | 5 | 0 | 83.7 | 72.6 | 90.2 | 1 |
| oil_60d_vel | higher | 3 | 3 | 94.0 | 94.0 | 95.3 | 3 |
| vix | higher | 2 | 0 | 76.4 | 75.1 | 77.7 | 0 |
| hy_oas | higher | 2 | 0 | 45.6 | 43.9 | 47.3 | 0 |

On the served sessions, DXY was the main channel. It never passed the 71st percentile of ten years. Only oil (three sessions) and the VIX term structure (one session) reached the 90th.

### Channels responsible: last 252 sessions (232 raised sessions)

| channel | direction | raised sessions where crisis | of which served | sole crisis channel | median | min | max | sessions ≥ 90 |
|---|---|---|---|---|---|---|---|---|
| gold_spx | higher | 139 | 0 | 59 | 98.4 | 86.7 | 100.0 | 126 |
| oil_60d_vel | higher | 92 | 3 | 3 | 96.2 | 56.0 | 99.4 | 67 |
| breakeven_5y | higher | 67 | 0 | 1 | 88.4 | 82.4 | 92.9 | 18 |
| dxy | higher | 62 | 44 | 15 | 66.7 | 60.4 | 70.7 | 0 |
| anfci | higher | 59 | 14 | 0 | 59.0 | 49.8 | 68.0 | 0 |
| skew | lower | 46 | 15 | 7 | 41.1 | 34.1 | 74.9 | 0 |
| vvix | higher | 38 | 0 | 0 | 88.2 | 80.3 | 97.7 | 16 |
| vix | higher | 27 | 2 | 0 | 86.0 | 75.1 | 95.1 | 4 |
| vix_term | higher | 22 | 5 | 0 | 93.2 | 72.6 | 97.4 | 18 |
| stlfsi | higher | 18 | 0 | 0 | 67.7 | 57.1 | 70.1 | 0 |
| spx_drawdown | lower | 18 | 8 | 0 | 60.5 | 56.0 | 81.0 | 0 |
| consumer_expect | lower | 16 | 0 | 0 | 29.0 | 28.7 | 29.3 | 0 |
| spx_ret_60d | lower | 15 | 0 | 0 | 89.4 | 83.8 | 93.8 | 5 |
| realized_vol | higher | 9 | 9 | 0 | 72.1 | 61.2 | 72.6 | 0 |
| hy_oas | higher | 5 | 2 | 0 | 47.3 | 43.9 | 71.8 | 0 |
| def_cyc | higher | 2 | 0 | 0 | 18.4 | 17.3 | 19.5 | 0 |

### Channels responsible: all sessions (4,632 raised sessions)

"n/a" counts sessions where the ten-year percentile could not be computed (fewer than 250 observations in the window).

| channel | direction | raised sessions where crisis | of which served | sole crisis channel | median | min | max | sessions ≥ 90 | n/a |
|---|---|---|---|---|---|---|---|---|---|
| yield_3m10y | lower | 1,721 | 0 | 89 | 94.4 | 16.9 | 100.0 | 923 | 154 |
| dxy | higher | 1,543 | 44 | 47 | 85.2 | 21.8 | 100.0 | 596 | 135 |
| breakeven_5y | higher | 1,405 | 0 | 361 | 66.3 | 16.8 | 100.0 | 289 | 0 |
| baa_aaa | higher | 1,304 | 0 | 0 | 81.7 | 13.5 | 99.9 | 295 | 170 |
| gold_spx | higher | 1,297 | 0 | 81 | 92.9 | 9.4 | 100.0 | 668 | 64 |
| loan_tightening | higher | 1,199 | 0 | 23 | 76.9 | 44.5 | 99.9 | 413 | 78 |
| consumer_expect | lower | 1,129 | 0 | 27 | 77.9 | 11.0 | 100.0 | 395 | 20 |
| anfci | higher | 1,116 | 14 | 0 | 62.5 | 9.0 | 100.0 | 382 | 129 |
| oil_60d_vel | higher | 1,054 | 3 | 81 | 87.1 | 43.4 | 100.0 | 416 | 34 |
| nfci | higher | 1,006 | 0 | 0 | 90.3 | 9.0 | 100.0 | 441 | 131 |
| skew | lower | 935 | 15 | 21 | 77.9 | 17.5 | 100.0 | 274 | 10 |
| mfg_new_orders | lower | 924 | 0 | 24 | 63.6 | 10.2 | 100.0 | 112 | 0 |
| kcfsi | higher | 867 | 0 | 0 | 83.2 | 25.0 | 99.9 | 370 | 31 |
| spx_ret_60d | lower | 866 | 0 | 9 | 83.7 | 33.5 | 100.0 | 268 | 7 |
| spx_drawdown | lower | 791 | 8 | 0 | 84.7 | 24.9 | 100.0 | 358 | 12 |
| def_cyc | higher | 766 | 0 | 0 | 58.4 | 7.9 | 99.9 | 284 | 38 |
| vvix | higher | 753 | 0 | 2 | 91.4 | 48.2 | 100.0 | 382 | 38 |
| stlfsi | higher | 715 | 0 | 0 | 67.8 | 31.6 | 100.0 | 220 | 20 |
| vix_term | higher | 691 | 5 | 5 | 84.0 | 36.6 | 100.0 | 195 | 32 |
| realized_vol | higher | 657 | 9 | 0 | 86.2 | 17.4 | 100.0 | 238 | 24 |
| vix | higher | 616 | 2 | 0 | 86.5 | 12.8 | 100.0 | 243 | 14 |
| tlt_spx | higher | 592 | 0 | 0 | 86.2 | 8.9 | 99.9 | 208 | 44 |
| hy_oas | higher | 46 | 2 | 0 | 66.0 | 43.9 | 81.2 | 0 | 22 |

Across all sessions there were 29,953 channel-sessions classed crisis. Of these, 11,350 (37.9%) were at or above the 90th ten-year percentile in the risky direction, and 1,543 had no percentile.

### The 30 most recent raised sessions

| date | source | regime | early warning | n_crisis | headline A | crisis channels (ten-year percentile, risky direction) | headline B |
|---|---|---|---|---|---|---|---|
| 2026-07-24 | served | ELEVATED | CLEAR | 1 | DEFENSIVE | dxy 70.2 | CAUTIOUS |
| 2026-07-27 | served | ELEVATED | CLEAR | 1 | DEFENSIVE | dxy 70.5 | CAUTIOUS |
| 2026-07-28 | served | ELEVATED | CLEAR | 1 | DEFENSIVE | dxy 69.9 | CAUTIOUS |
| 2026-07-29 | served | ELEVATED | WATCH | 4 | CRISIS | vix_term 83.7, skew 39.4, dxy 66.7, spx_drawdown 61.6 | CAUTIOUS |
| 2026-07-30 | served | ELEVATED | CLEAR | 2 | DEFENSIVE | skew 38.2, dxy 62.9 | CAUTIOUS |
| 2026-07-31 | served | LOW RISK | CLEAR | 1 | DEFENSIVE | skew 34.1 | DEPLOY |
| 2026-08-03 | served | LOW RISK | CLEAR | 2 | DEFENSIVE | skew 37.9, dxy 63.0 | DEPLOY |
| 2026-08-04 | served | LOW RISK | CLEAR | 1 | DEFENSIVE | skew 74.9 | DEPLOY |
| 2026-08-05 | served | LOW RISK | CLEAR | 1 | DEFENSIVE | skew 57.5 | DEPLOY |
| 2026-08-06 | served | LOW RISK | CLEAR | 2 | DEFENSIVE | skew 53.7, dxy 62.7 | DEPLOY |
| 2026-08-07 | served | LOW RISK | CLEAR | 1 | DEFENSIVE | skew 59.8 | DEPLOY |
| 2026-08-10 | served | LOW RISK | CLEAR | 1 | DEFENSIVE | skew 47.0 | DEPLOY |
| 2026-08-11 | served | LOW RISK | CLEAR | 1 | DEFENSIVE | skew 51.8 | DEPLOY |
| 2026-08-12 | served | LOW RISK | CLEAR | 2 | DEFENSIVE | skew 49.1, dxy 62.9 | DEPLOY |
| 2026-08-13 | served | LOW RISK | CLEAR | 2 | DEFENSIVE | skew 55.0, dxy 62.5 | DEPLOY |
| 2026-08-14 | served | LOW RISK | CLEAR | 1 | DEFENSIVE | skew 43.3 | DEPLOY |
| 2026-09-10 | served | LOW RISK | CLEAR | 1 | DEFENSIVE | oil_60d_vel 94.0 | DEFENSIVE |
| 2026-09-14 | served | LOW RISK | CLEAR | 1 | DEFENSIVE | oil_60d_vel 94.0 | DEFENSIVE |
| 2026-09-15 | served | LOW RISK | CLEAR | 1 | DEFENSIVE | oil_60d_vel 95.3 | DEFENSIVE |
| 2026-09-16 | revised | LOW RISK | CLEAR | 3 | DEFENSIVE | dxy 64.5, spx_drawdown 58.5, oil_60d_vel 95.5 | DEFENSIVE |
| 2026-09-17 | revised | LOW RISK | CLEAR | 2 | DEFENSIVE | dxy 63.9, oil_60d_vel 94.8 | DEFENSIVE |
| 2026-09-18 | revised | LOW RISK | CLEAR | 2 | DEFENSIVE | dxy 63.9, oil_60d_vel 95.3 | DEFENSIVE |
| 2026-09-21 | revised | LOW RISK | CLEAR | 1 | DEFENSIVE | dxy 65.1 | DEPLOY |
| 2026-09-22 | revised | LOW RISK | CLEAR | 2 | DEFENSIVE | dxy 65.9, oil_60d_vel 93.8 | DEFENSIVE |
| 2026-09-23 | revised | LOW RISK | CLEAR | 1 | DEFENSIVE | dxy 68.3 | DEPLOY |
| 2026-09-24 | revised | LOW RISK | CLEAR | 2 | DEFENSIVE | dxy 69.2, oil_60d_vel 94.0 | DEFENSIVE |
| 2026-09-25 | revised | LOW RISK | CLEAR | 2 | DEFENSIVE | dxy 67.4, oil_60d_vel 93.9 | DEFENSIVE |
| 2026-09-28 | revised | LOW RISK | CLEAR | 2 | DEFENSIVE | hy_oas 44.0, dxy 68.9 | DEPLOY |
| 2026-09-29 | served | LOW RISK | CLEAR | 2 | DEFENSIVE | hy_oas 43.9, dxy 69.2 | DEPLOY |
| 2026-09-30 | served | LOW RISK | CLEAR | 2 | DEFENSIVE | hy_oas 47.3, dxy 70.1 | DEPLOY |

## 3. Options

- **A. Keep the vote.** `n_crisis >= 1` → DEFENSIVE; `n_crisis >= 4` → CRISIS. This is what is served now.
- **B. Ten-year filter.** A crisis channel counts toward the vote only if its ten-year percentile in the risky direction is at least 90. The same thresholds (1 and 4) then apply to that count. A channel without a percentile does not count.
- **C. Show, do not vote (DIAGNOSTIC).** The crisis count stays on the card and in the inputs line. The headline is the worse of the regime label and the early-warning label. This applies the logic of the Decision Memo of 9 September 2026, §5: the headline is the index C3 measured, and the crisis-count vote was never measured.

Counts are sessions at each headline level. "Changes" counts transitions from one session's headline to the next. For the served and revised rows, a transition is counted under the source of the session it arrives at, so the two rows add up to the full-history figure. For the last 252 sessions, only transitions inside the window are counted (251 pairs). These tables leave out the complacency rule and the intraday shock (see below).

### Full history (5,427 sessions, 2005-04-05 to 2026-09-30)

| option | DEPLOY | CAUTIOUS | DEFENSIVE | CRISIS | changes | sessions differing from A |
|---|---|---|---|---|---|---|
| A | 116 | 49 | 2,283 | 2,979 | 401 | — |
| B | 546 | 917 | 2,844 | 1,120 | 404 | 2,904 |
| C | 838 | 2,241 | 1,806 | 542 | 245 | 4,632 |

### Served sessions (72)

| option | DEPLOY | CAUTIOUS | DEFENSIVE | CRISIS | changes | sessions differing from A |
|---|---|---|---|---|---|---|
| A | 18 | 0 | 49 | 5 | 13 | — |
| B | 45 | 23 | 4 | 0 | 16 | 51 |
| C | 48 | 24 | 0 | 0 | 11 | 54 |

Read as a sequence of served snapshots only, which skips the 12 unserved sessions, the changes are A 13, B 16, C 10.

### Revised sessions (5,355)

| option | DEPLOY | CAUTIOUS | DEFENSIVE | CRISIS | changes | sessions differing from A |
|---|---|---|---|---|---|---|
| A | 98 | 49 | 2,234 | 2,974 | 388 | — |
| B | 501 | 894 | 2,840 | 1,120 | 388 | 2,853 |
| C | 790 | 2,217 | 1,806 | 542 | 234 | 4,578 |

### Last 252 sessions (2025-09-30 to 2026-09-30; 72 served, 180 revised)

| option | DEPLOY | CAUTIOUS | DEFENSIVE | CRISIS | changes | sessions differing from A |
|---|---|---|---|---|---|---|
| A | 19 | 1 | 182 | 50 | 36 | — |
| B | 49 | 43 | 148 | 12 | 37 | 106 |
| C | 77 | 150 | 25 | 0 | 15 | 232 |

### The last 252 sessions by month (DEPLOY / CAUTIOUS / DEFENSIVE / CRISIS)

| month | sessions | A | B | C |
|---|---|---|---|---|
| 2025-09 | 1 | 0/0/1/0 | 0/1/0/0 | 0/1/0/0 |
| 2025-10 | 23 | 0/0/22/1 | 0/9/14/0 | 0/23/0/0 |
| 2025-11 | 19 | 0/0/17/2 | 0/3/16/0 | 0/19/0/0 |
| 2025-12 | 22 | 0/0/22/0 | 0/0/22/0 | 8/14/0/0 |
| 2026-01 | 20 | 0/0/20/0 | 0/0/20/0 | 11/9/0/0 |
| 2026-02 | 19 | 0/0/18/1 | 0/0/19/0 | 0/19/0/0 |
| 2026-03 | 22 | 0/0/2/20 | 0/0/10/12 | 0/4/18/0 |
| 2026-04 | 21 | 0/0/9/12 | 0/0/21/0 | 0/14/7/0 |
| 2026-05 | 20 | 0/1/10/9 | 0/4/16/0 | 0/20/0/0 |
| 2026-06 | 21 | 1/0/16/4 | 3/17/1/0 | 3/18/0/0 |
| 2026-07 | 22 | 0/0/21/1 | 13/9/0/0 | 13/9/0/0 |
| 2026-08 | 21 | 11/0/10/0 | 21/0/0/0 | 21/0/0/0 |
| 2026-09 | 21 | 7/0/14/0 | 12/0/9/0 | 21/0/0/0 |

### By year (share of sessions at DEFENSIVE or CRISIS; changes)

| year | sessions | n_crisis ≥ 1 | A | B | C | changes A | changes B | changes C |
|---|---|---|---|---|---|---|---|---|
| 2005 | 189 | 100% | 100% | 95% | 95% | 0 | 7 | 5 |
| 2006 | 251 | 100% | 100% | 98% | 34% | 13 | 14 | 9 |
| 2007 | 251 | 100% | 100% | 100% | 84% | 5 | 13 | 11 |
| 2008 | 253 | 100% | 100% | 100% | 93% | 10 | 6 | 3 |
| 2009 | 252 | 92% | 92% | 59% | 31% | 11 | 14 | 9 |
| 2010 | 252 | 97% | 97% | 57% | 24% | 31 | 26 | 14 |
| 2011 | 252 | 97% | 97% | 61% | 44% | 20 | 19 | 12 |
| 2012 | 250 | 99% | 99% | 30% | 18% | 28 | 21 | 3 |
| 2013 | 252 | 98% | 98% | 5% | 0% | 37 | 23 | 7 |
| 2014 | 252 | 89% | 89% | 35% | 34% | 25 | 27 | 23 |
| 2015 | 252 | 100% | 100% | 100% | 100% | 4 | 20 | 20 |
| 2016 | 252 | 100% | 100% | 100% | 76% | 10 | 3 | 4 |
| 2017 | 251 | 92% | 92% | 80% | 0% | 29 | 20 | 8 |
| 2018 | 251 | 100% | 100% | 96% | 61% | 8 | 9 | 10 |
| 2019 | 252 | 100% | 100% | 100% | 56% | 28 | 15 | 12 |
| 2020 | 253 | 96% | 96% | 74% | 37% | 17 | 15 | 10 |
| 2021 | 252 | 95% | 95% | 85% | 6% | 18 | 27 | 16 |
| 2022 | 256 | 100% | 100% | 100% | 97% | 0 | 10 | 9 |
| 2023 | 257 | 95% | 95% | 74% | 23% | 19 | 29 | 11 |
| 2024 | 259 | 100% | 100% | 46% | 11% | 25 | 36 | 20 |
| 2025 | 251 | 93% | 93% | 55% | 19% | 33 | 18 | 15 |
| 2026 | 187 | 89% | 89% | 58% | 13% | 30 | 32 | 14 |

Under A, the share at DEFENSIVE or worse equals the share of sessions with any crisis channel. In 2013 and 2017, years in which the index itself never read DEFENSIVE, A would have read DEFENSIVE or CRISIS on 98% and 92% of sessions.

### What keeps B voting

B is above C on 2,180 sessions over the full history and on 147 of the last 252. In the last 252, the channels that qualified on those sessions were gold_spx (113 sessions), oil_60d_vel (54), breakeven_5y (17), vix_term (16), vvix (14), spx_ret_60d (5) and vix (4). Over the full history: yield_3m10y (631), gold_spx (543), loan_tightening (401), nfci (393), dxy (376), anfci (360), spx_drawdown (347), kcfsi (336). B removes the votes that are extreme only against the past year. It keeps the votes of channels sitting at ten-year highs or lows for long stretches, such as the gold/S&P 500 ratio through 2025–26 and the 3m–10y inversion. B does not reduce changes: 404 against A's 401 over the full history, 37 against 36 in the last 252.

### With the complacency rule

app.js turns a rank-0 headline into COMPLACENT when the complacency flag is truthy. The string "impaired" also counts, because the check is `!!(reg.complacency_flag || …)`. Applying that rule:

| subset | option | DEPLOY | COMPLACENT | CAUTIOUS | DEFENSIVE | CRISIS | changes |
|---|---|---|---|---|---|---|---|
| all | A | 69 | 47 | 49 | 2,283 | 2,979 | 405 |
| all | B | 427 | 119 | 917 | 2,844 | 1,120 | 429 |
| all | C | 634 | 204 | 2,241 | 1,806 | 542 | 306 |
| served | A | 1 | 17 | 0 | 49 | 5 | 13 |
| served | B | 20 | 25 | 23 | 4 | 0 | 23 |
| served | C | 23 | 25 | 24 | 0 | 0 | 21 |
| last 252 | A | 1 | 18 | 1 | 182 | 50 | 36 |
| last 252 | B | 20 | 29 | 43 | 148 | 12 | 44 |
| last 252 | C | 24 | 53 | 150 | 25 | 0 | 26 |

Under A the vote mostly hides the complacency flag, because the headline is already at rank 2. The flag would show on 204 sessions under C; A shows it on 47 of them. In the last 252 sessions it would show on 53 under C and on 18 under A. Choosing C or B therefore makes COMPLACENT a frequent headline. The operator should expect it, starting with 30 September. The intraday shock override (INTRADAY STRESS) depends on a live intraday snapshot and cannot be reconstructed for past sessions. It sits outside this question and is unchanged by every option.

## 4. The advisor's recommendation

**The advisor recommends option C.** It is the ratified convention for unvalidated signals, applied the way the Decision Memo of 9 September 2026, §5 applied it to v4. The crisis count stays on the card, labelled DIAGNOSTIC, and stops voting in the headline.

The reasons, as the advisor reads the numbers above:

1. **The vote was never measured.** It entered the headline on 5 June 2026 (commit 4e4118c) and has no registration. No report under `reports/` mentions it. C3 measured the regime index, R_full from `data/regime_v2_daily.csv`, as an overlay. §5 took v4 out of the headline for the same reason: "the headline is the regime index whose value C3 measured" (app.js, headlineVerdict()).
2. **The convention exists and is in use.** The rates-regime state (`reports/bonds_module_acceptance_2026-09-16.md`, item 8) and the hedge selector (`reports/options_registration_2026-09-26.md`, §D) are both shown, labelled DIAGNOSTIC, and drive nothing until their registered tests pass. The crisis count is the same kind of signal.
3. **It is nearly always on.** The vote alone raised the headline on 85.4% of all sessions and 92.1% of the last 252. A label raised that often does not single out the sessions that differ.
4. **It moves the headline more.** Changes: 401 under A, 245 under C over the full history; 36 against 15 in the last 252.
5. **Nothing else reads it.** No sizing script reads `n_crisis`; a grep of `scripts/` finds it only in the v1 `compute_regime.py` text and in the v2 snapshot writer. The tournament cash schedules are a function of R_t = R_full (`compute_nav.py`, `cash_pct_from_formula`). The vote changes the label and the action sentence under it, not any schedule. On a session raised by the vote alone, the DEFENSIVE sentence ("the regime schedules hold roughly half of full deployment") describes a label, not the schedules' actual state.

**B is the fallback** if the operator wants to keep a tail vote. If B is chosen, the advisor notes that the 90th-percentile threshold is a choice, not a tested value. It would need its own registration before it is presented as more than a display rule. B also keeps the headline at DEFENSIVE or worse on 73% of all sessions (63% in the last 252) and does not reduce changes.

**Implement nothing in headlineVerdict() until the operator's written choice.**

## Method

**Source for §5.** The Decision Memo of 9 September 2026 is not in `reports/` or elsewhere in the repository. Its §5 is cited from three places: the comment in `headlineVerdict()` (app.js at HEAD 2ef8d0d, lines 753–756), commit 675aac4 ("[memo-§5][memo-§6] … v4 removed from the headline vote … headline = regime index"), and the execution report `reports/decision_memo_execution_2026-09-09.md`, item 2. The quoted phrase comes from the app.js comment.

**Sessions.** Every session for which the v2 model produces an R_full (n_full ≥ 12), 5 April 2005 to 30 September 2026. Sessions are exchange sessions as the model defines them (`build_daily_panel`).

**Served snapshots.** Read from the git history of `data/regime_indicators.json` with `git log` and `git show` only. 113 versions were committed up to 1 October 2026 12:00 UTC. They carry 72 distinct `as_of` sessions. For each `as_of` the script takes the last nightly commit (the nightly's subject starts with "📊") and reads `as_of`, `regime`, `early_warning`, `n_crisis`, `complacency_flag` and each indicator's `status`, `value` and `direction`. Ten sessions had more than one version. The label or count differed between versions on 2 June, 3 June and 7 July. The rule "last nightly" and the rule "last version of any kind" disagree only on 2 June: the nightly 397e631 read LOW RISK / UNKNOWN / 0, and a manual rebuild two minutes later (5627f6d) read ELEVATED / WATCH / 1. The R1 display commit 2ef8d0d rewrote the 30 September file after the nightly. It is not a nightly; its label and count are the same. Served `n_crisis` equals the number of `status == "crisis"` entries in every version read.

**Revised sessions.** Recomputed from the source parquets with the unchanged v2 code. The script imports `load_sources`, `load_series_dict`, `build_daily_panel`, `compute_zscores_and_risk`, `compute_composites`, `classify` and `status_from_phi` from `scripts/compute_regime_v2.py`. It never calls `main()`, which writes served files. Before running, it checks that each imported function is byte-identical to the committed file (blob 7e17dc5 at HEAD 2ef8d0d and at 5f3694b). The R1 commit changed only display code inside `main()`. The inputs are the source parquets of the 1 October nightly (2082b01). While this memo was prepared, the R3 and R5 commits (80e2bbc, 5f3694b) added new columns to `fred_indicators.parquet` and `vol_indicators.parquet`. Every column the v2 model reads, and the index, is identical to the 2082b01 nightly; this was checked column by column against `git show 2082b01:…`. The model's inputs therefore did not change, and the outputs of runs before and after those commits are identical. "Revised" means today's data vintage under today's code, not what the system knew on the day.

**Label field.** The served `regime` field is the output of `classify()` in `compute_regime_v2.py`. Up to the July audit commit 12b5a38 (7 July 2026), `classify()` assigned plain bands; 21 served sessions (2 June to 6 July) carry plain-band labels. From `as_of` 7 July it applies the hysteresis corridor (bands at 0.30 / 0.50 / 0.70; enter a higher band at the boundary + 0.02, leave it at the boundary − 0.02). That corridor is the same rule as `scripts/regime_label.py`: run over the same R_full series, `regime_label.corridor_series` reproduces `classify()` on all 5,427 sessions, with no mismatch. Revised sessions use the corridor label from `classify()` run over the whole revised history. Plain bands would differ on 411 of those sessions.

**Headline rule.** Ranks as in `app.js`: LOW RISK / CLEAR / DEPLOY 0; ELEVATED / WATCH / CAUTIOUS 1; HIGH RISK / WARNING / DEFENSIVE 2; CRISIS / DANGER 3. UNKNOWN casts no vote. Today's rule is applied to every session, including sessions before 9 September when v4 still voted. v4 is left out throughout. Complacency is reported in its own table. The served flag is used for served sessions. For revised sessions the flag is SKEW > 140 and VIX < 17 from the panel, or "impaired" if either value is missing.

**Ten-year percentile.** The same method as `scripts/bonds/compute_bonds.py::pctile`: the share of the trailing ten calendar years of the series, through the session, strictly below the value, × 100, rounded to 0.1. It is None with fewer than 250 observations. It is computed on the v2 daily panel series. The risky direction is 100 − percentile for channels whose direction is "lower". For served sessions the value is the served value, ranked against today's panel history through that session. For revised sessions it is the panel value. The 30 September figures match the `pctile_10y_risky` fields R1 now serves (47.3 and 70.1).

**756-session z.** The same rolling mean and standard deviation as `compute_zscores_and_risk`, window 756, `min_periods` 60 (the model's own MIN_PERIODS), sign flipped for "lower" channels. For HY OAS and DXY on 29 and 30 September the full 756 sessions are present, so `min_periods` does not bind. The 30 September values match R1's served `z_756` (−0.053 and −0.131).

## Limitations

1. **HY OAS history is short.** The stored series starts 5 June 2023, so its "ten-year" percentile covers 3.3 years. HY has no status in the revised history before late August 2023.
2. **Revised data.** Revised sessions use today's FRED values, including revisions, and today's code. The percentile reference for served sessions is also today's panel. On the 72 served sessions, the revised recompute gives the same option-A headline on 68. It differs on 2 June, 9 June, 24 August and 10 September.
3. **A numerical difference between machines.** On 136 revised sessions (22 June to 29 December 2023), R_full here differs from the CI-written `data/regime_v2_daily.csv` by up to 0.017. Cause: `loan_tightening` is constant across a full 252-session window. Its rolling standard deviation comes out at 7.7e-07 on this machine and exactly zero on the CI runner. Here that gives z = 0 (a "neutral" status); on CI the channel has no score. Twenty labels differ. With the CI labels, option A is unchanged on every session; B differs on 8 sessions and C on 12. Changes become A 401, B 402, C 245 (against 401, 404, 245). No crisis status is affected.
4. **Early served snapshots.** The 2–4 June versions came from a model still being assembled. Some versions had 11–18 channels, and early warning read UNKNOWN on 2 June.
5. **Complacency definitions.** Served flags before 7 July used the June definition, which the July audit reversed. They are taken as served.
6. **What C keeps.** C keeps the early-warning label (from R_lead) in the headline. C3 measured R_full, not R_lead. Whether the early-warning label should vote is outside this memo's question.
7. **Frequency, not usefulness.** These counts say how often each rule speaks and how often it changes. They do not test whether any option improves an outcome. No option is validated by this memo.

## Discrepancies with the order's figures

| figure | order | found | explanation |
|---|---|---|---|
| HY OAS z, 252 sessions | +1.27 | +1.270 (30 Sept, served); +0.929 (29 Sept, served) | Reproduced for 30 September. |
| HY OAS z, 756 | about +0.06 | −0.053 (30 Sept); −0.057 (29 Sept) | The order's value comes from 756 observations of the raw FRED series (+0.063). That series has 871 observations since 5 June 2023, against 846 exchange sessions in the model's panel. The specified method, rolling on the panel, gives −0.05. Both are near zero; the reading does not change. |
| DXY z, 252 | +2.14 | +1.992 (30 Sept); +1.904 (29 Sept, served; +1.943 on today's panel) | Not reproduced for either close. The order's two DXY figures match a DXY of about 101.63 (z +2.12 to +2.15 and −0.074 to −0.076). That is the 1 October pre-open intraday print in `data/intraday.json` (05:53 UTC, last 101.627). They look like an intraday reading, not the 29 September close. |
| DXY z, 756 | −0.07 | −0.131 (30 Sept); −0.171 (29 Sept, served) | As above. |
| n_crisis | 2 | 2 on both 29 and 30 Sept (hy_oas, dxy) | Reproduced. |

## Observed in passing (outside [R2]; nothing changed)

- **Weekend-dated monthly and quarterly prints are dropped.** `build_daily_panel` reindexes each series onto business days before forward-filling. A FRED observation dated on a Saturday or Sunday therefore disappears, and the previous print is carried on. This affects 75 of 260 monthly prints for `consumer_expect`, `mfg_new_orders`, `kcfsi` and `baa_aaa`, and 26 of 87 quarterly prints for `loan_tightening`. On 30 September the panel carries the July values for the four monthly series; the August prints, dated Saturday 1 August, are missing (for example, `consumer_expect` shows 4.2 against August's 4.0). The same mechanism produced the constant `loan_tightening` stretch in limitation 3.
- **`realized_vol` has been stale since 4 September.** `vol_derived.parquet` has no `spx_realized_vol_20d` value after 4 September 2026, so the panel carries 8.30 forward to 30 September.

## Reproducibility

Run from the repository root:

```
.venv/bin/python scripts/analysis/crisis_vote_history.py
```

- Script: `scripts/analysis/crisis_vote_history.py`. It is read-only. It imports the v2 functions, never `main()`. It reads git history with `git log`, `git show`, `git rev-parse` and `git hash-object` only. It writes only `reports/crisis_vote_history_2026-10-01.csv` and prints every table in this memo to stdout. It runs in about 10 seconds.
- CSV: one row per session, with date, source, commit, R_full, R_lead, regime, early_warning, n_crisis, n_crisis_B, crisis channels with their ten-year percentiles, the headline under A, B and C with and without complacency, and the revised option-A headline for served sessions.
- The served history is pinned to commits at or before 1 October 2026 12:00 UTC (`CUTOFF_CT` in the script). The revised history depends on the source parquets in the working tree. The script prints their blob ids. This memo's figures were produced on the 2082b01 inputs and reproduced unchanged at HEAD 5f3694b. A rerun after a later nightly will move the revised figures for recent sessions.
