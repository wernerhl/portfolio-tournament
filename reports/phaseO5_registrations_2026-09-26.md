# Options lens — Phase 5 (validation registrations, registered and not run)

Order 26 September 2026, commit [O5] — `reports/options_registration_2026-09-26.md`,
committed before any validation run (acceptance §9.7).

## Referee

Unchanged by this phase (a document): 45 findings, 19 CRITICAL, all pre-existing freshness.

## What is registered

- **5.1 options-derived return signals** — candidates on the full union universe only, never
  on the seven-name book: the call-minus-put implied-volatility spread (Cremers & Weinbaum
  2010), the steepness of the put smirk (Xing, Zhang & Zhao 2010), changes in call and put
  implied volatility (An, Ang, Bali & Cakici 2014) — monthly quintile sorts,
  factor-neutralized, net of costs, by the retirement method; and the implied-minus-realized
  gap (Goyal & Saretto 2009) as a predictor of delta-hedged option returns, not of stock
  returns. None enters Business Quality or Trade-Now unless it passes.
- **5.2 the event-premium test** — implied moves against realized reactions for the held
  names and the top-40 board, by name and pooled, Wilson intervals on the exceedance rate;
  its result governs rule 5 of the hedge selector.
- **5.3 the overlay tests** — covered calls vs delta-matched exposure reduction; collars vs
  trimming to a 40 percent risk share; put-writes on the cash sleeve vs the policy rate;
  conditional protection vs the regime cash sleeve — point-in-time chains, costs at one third
  of quoted width, common-resample paired bootstrap (60-session blocks, 1,000 resamples,
  seed 20260926), the paired criterion. The DIAGNOSTIC label on the hedge selector lifts
  only on a pass; adoption is a separate written decision.

## Deviations

- Not run: the point-in-time option history these need is the item-1.4 purchase, which is
  Werner's decision; the system's own archive (started 25 Sept) cannot support a run for at
  least a year.
- `options_layer_design.md` is not on this machine; the four overlay tests are the ones the
  order enumerates.
