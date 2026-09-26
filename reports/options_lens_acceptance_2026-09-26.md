# Options lens — acceptance (§9), all phases

Order: Execution Order — The Options Lens, Per Stock, 26 September 2026. Commits
`[O1.1]` `[O1.2]` `[O1.3]` `[O2]` `[O3]` `[O4]` `[O5]` `[O6]`, one report per phase
(`reports/phaseO*_2026-09-26.md`). Built on a Saturday against the 25-September close.

## §9 checklist

1. **Referee before and after; zero CRITICAL.** ✘/✔ — Before: 44 findings, 19 CRITICAL.
   After: 45 findings, 19 CRITICAL. **The options module adds zero CRITICAL and zero HIGH**
   (one INFO: the flagged backfill). The 19 are the same pre-existing finding — every served
   file stuck at 2026-09-15 by the nightly outage — whose root cause was found and fixed
   during Phase 1 (commit `8f022c3`: the schedule gate misread late-delivered close runs,
   and the bar-missing retry never armed). The first clean referee is expected after
   Monday's close run; it could not be produced on a weekend without forcing a publish,
   which the guards exist to prevent.
2. **Numeric checks against the 25 September close.** ✔ with one finding — MU median
   reaction 5.25% over 24 releases (order ~5.2); MU term structure inverted; NVDA IV 29.6%
   below realized 43.0 / 38.6 on both windows (order ~31 vs 43/39); GEV put/call open
   interest 5.305 (order ~5.3). **MU event-implied move 7.78% with 8 of 24 exceeding**
   against the order's 8.3% / 7 of 24 — the first finding: total variance to the 2-Oct expiry
   is convention-free (0.0115); the order's figure reproduces only by counting the pull day
   for the base variance but not the total, or with a back-month base near 54% instead of
   58.5%. This implementation applies the stated rule consistently (sessions strictly after
   the snapshot session, identical for the inversion and the subtraction) and states it in
   the file. Phase 2 report, with the sensitivity table.
3. **No served IV originates from the provider's field (verify in code).** ✔ — the snapshot
   never stores the provider column; `implied_vol` inverts Black-Scholes; the referee's
   `options:provider_iv` is CRITICAL on any appearance.
4. **Three-column cards on screen, tournament and book; the scanner encodes state and
   earnings proximity; the event board renders.** ✔ — verified on all three views (Phase 3
   report; the scanner is the ranked table, no scatter exists).
5. **Hedge selector rows for every held name, each labeled DIAGNOSTIC, with stress-scenario
   effects.** ✔ — 7 names × 2 tenors × 5 rows, each with the three scenarios.
6. **The first daily chain vintage exists and a second session appends without rewriting
   the first.** ✔/pending — the 25-Sept vintage exists (a flagged backfill); immutability is
   verified (a second run writes 0, skips 45; every sha256 matches its record; the referee
   re-checks nightly). The second session appends Monday at 15:45 ET from the scheduled job.
7. **The Phase 5 registrations are committed before any validation run.** ✔ — `[O5]`, no
   run made.
8. **No page emits a buy or sell recommendation; the words edge and alpha appear nowhere.**
   ✔ — every panel descriptive; the referee's `options:language`/`options:directive` are
   CRITICAL; no whole-word edge/alpha in `scripts/options/`, `data/options/`, the options
   render functions, or the registration.

## Deviations, consolidated

1. Saturday build: the first vintage is a flagged post-close backfill, not a 15:45
   snapshot; scheduled vintages start Monday.
2. Item 1.4 (history purchase) not made — Werner's decision; IV rank/percentile null with
   the reason; Phase 5 registered, not run.
3. The price store was stale from the nightly outage; the engine overlays provider closes in
   memory to the last session (recorded), never modifying the store.
4. `options_layer_design.md` is not on this machine; the order stated every decision.
5. The scanner is a table, not a scatter; the marker encoding is applied to it.
6. `lxml` added to the environment for the earnings-date scrape.

## Governing premises honoured

Description and hedging only, shipped descriptive; return signals as registered candidates
on the union universe, never on the book; no panel emits a directional recommendation; the
provider's IV never used; after-hours pulls prohibited and gated; every vintage immutable
and hashed; the hedge selector DIAGNOSTIC on every row.
