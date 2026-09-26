# Options lens — Phase 2 (per-stock features, `data/options/lens.json`)

Order 26 September 2026, commit [O2]. Nightly, from the session's chain vintage, for all 45
analyzed names (0 warnings against the 25-Sept vintage).

## Referee

Unchanged by this phase: 45 findings, 19 CRITICAL, all pre-existing freshness (Phase 1
report); `options:iv_range`, `options:provider_iv`, `options:language` and
`options:directive` pass on lens.json.

## Numeric checks against the 25 September close (acceptance §9.2)

| check | order | this implementation | verdict |
|---|---|---|---|
| MU median historical reaction, 24 releases | ~5.2% | **5.25%**, 24 releases | ✔ |
| MU term structure | inverted | **inverted**: front 10-23 at 59.1% over back 12-18 at 58.5%, reason "earnings 2026-09-30 inside the front tenor" | ✔ |
| NVDA IV below realized on both windows | ~31% vs 43 / 39 | IV30 **29.6%** (10-23; 29.8% interpolated to 30 days) vs RV21 **43.0%**, RV63 **38.6%** → **cheap** | ✔ (state and both gaps; the IV level differs by an ATM/tenor convention, below) |
| GEV put/call open-interest ratio | ~5.3 | **5.305** at the front expiry (10-23) | ✔ |
| MU event-implied move, 2 Oct expiry | ~±8.3% | **±7.78%** | ✘ — the first finding, below |
| MU releases exceeding the implied move | 7 of 24 | **8 of 24** at 7.78% (7 of 24 at 8.3%) | consistent with the same reaction set |

**The first finding — MU's event-implied move.** Total variance to the 2-Oct expiry is fixed
by the option prices and independent of any day-count convention: 0.0115 (ATM IV 76.1%
over 5 sessions after the 25-Sept close, or equivalently 69.5% over 6 sessions counting the
pull day). The implied move depends on how much *base* variance is subtracted. Under the
order's definition — base at the back-month IV (58.5%, the 12-18 expiry) over the non-event
sessions — the result is:

| convention | sessions to expiry | non-event sessions | implied move | exceed |
|---|---|---|---|---|
| sessions strictly after the 25-Sept close (adopted) | 5 | 4 | **7.78%** | 8 of 24 |
| counting the pull day, applied consistently | 6 | 5 | 6.95% | 9 of 24 |
| pull day counted for the base only (a mixed convention) | 5 / 6 | 5 | 8.37% | 7 of 24 |

The auditor's 8.3% and 7-of-24 are reproduced exactly by the mixed convention, and also by a
consistent computation whose back-month base is about 54% instead of 58.5% (for example
the put side of the back expiry alone). Neither is the order's stated rule applied
consistently, so this implementation keeps the adopted convention — sessions strictly after
the snapshot session, used identically for the inversion and the subtraction, stated in the
file's definitions — and reports 7.78% with 8 of 24. The exceedance count is not in dispute:
it is the same 24 reactions (8.6, 8.0, 7.4 … percent around the threshold), and the one at
8.0% is what flips between the two counts. The ranking consequences are unchanged: the
event premium is positive either way (implied above the 5.25% median), MU's term structure
is inverted with earnings inside the tenor, and rule 5 excludes premium selling.

**NVDA's "about 31%".** The nearest-30-day expiry (10-23, 28 days) reads 29.6%; the next
(10-30) 30.4%; the 11-20 and 12-18 expiries are inflated to 35.6% by the 17-Nov release.
Interpolated to exactly 30 calendar days: 29.8%. The order's 31% sits within the choice of
ATM and tenor convention; the substantive claim (IV below realized on both windows, state
cheap) holds under every variant.

## Features shipped (per name)

Volatility pricing (IV30/IV90 at the nearest expiries, calendar-interpolated values beside
them, RV21/RV63, both gaps, the state; IV rank/percentile null until the archive holds 60
sessions), the term structure with its reason, the event (next release, days and sessions
to it, the first expiry after it, the implied move and its method, mean/median/max past
reaction, the share exceeding, the last eight alone, the event premium), the skew (10% OTM
put minus call IV, the 25-delta risk reversal, the 5-session change null until six
sessions), positioning (put/call OI, max pain and its distance, the three largest OI strikes
each side; descriptive only), dealer gamma (per 1% at spot, the flip level, the convention
and its caveat printed; collapsed by default), and the ATM IV at every expiry.

## Deviations

- IV rank/percentile and the 5-session skew change are `null` with their reasons until the
  archive matures (or the item-1.4 purchase supplies history).
- The "fair" label named in 3.1 is not defined by the Phase 2 rule (cheap/rich/mixed); the
  cards show the three defined states.
