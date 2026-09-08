# Ledger entries and abstract replacement — Decision Memo 9 September 2026 (order item 7)

The memo orders these into "the textbook": ledger entries 13 and 14, the supplement to Failure 10, and the deflated abstract sentence replacing the drawdown claims in the preface and the regime chapter. **No textbook, failure ledger, preface or regime chapter exists as a file on this machine** (Spotlight and a recursive search of `~/Documents` for "Failure 10", "Failure 11", "textbook", "preface" and "regime chapter" return nothing; `_paper/` holds only the May architecture note and the June regime-v3 draft, neither of which carries a failure ledger). The entries are therefore delivered here, verbatim from the memo, ready to paste; the location of the textbook is the one open item of this batch.

## Failure 13 — the Labor Day chain

> Failure 13, the Labor Day chain: a holiday run, a provider regression that rewrote history, a job with no input assertion, a validator that rejected correctly, and a publish step that shipped the rejected artifact. Five defects in one night, each individually small.

Cross-references: `reports/september_audit_remediation_2026-09-07.md` (items [1]–[8]); `reports/reconciliation_response_2026-09-08.md`; commits 48bb4f0 (holiday guard, session-keyed), d457947 (rejected runs write nothing, named reasons), 6ae6c73 (validator freshness keyed on the guard's session).

## Failure 14 — the referee's author

> Failure 14, the referee's author: a pre-registered decision rule that no contestant could satisfy, discovered only because the result forced the examination. Principle: an amendment clause is not a loophole if and only if the original verdict stays on record and the amendment's timing is disclosed. Fix: registration v2 as above, both verdicts everywhere.

Cross-references: `reports/c3_registration.md` (v1, c39e2aa), `reports/c3_registration_v2.md` (amended 2026-09-09, v1 verdict retained, amendment paragraph), `reports/retirement_test_C3_regime_vs_rules.md` (both verdicts), dashboard regime card (both verdicts, standing).

## Supplement to Failure 10

> Supplement to Failure 10: two diagnoses from served output (a seven-week death, a feed-driven column loss) falsified by the code within a day; and a provider close wrong by three quarters of a point caught by the canonical source on its first test.

Cross-references: `reports/september_audit_remediation_2026-09-07.md` (corrected diagnoses: vol regime current through Sept 4, not dead since July 17; v4 blank columns were the nightly's trailing-five blanking, not a feed loss); `reports/reconciliation_response_2026-09-08.md`; `data/vol_close_canonical.json` (Cboe canonical vs yfinance).

## The claim the evidence supports (replaces every prior drawdown-reduction statement in the preface and the regime chapter, and the paper's abstract)

> "A regime-conditional cash overlay reduced maximum drawdown by roughly half relative to buy-and-hold on point-in-time inputs over 2010 to 2026, against roughly 30 percent for the best one-line rule, at a cost of about half the benchmark's annualized return. Its return-per-volatility advantage over simple rules is positive on revised inputs and indistinguishable from zero on real-time inputs, and its drawdown advantage narrows to a few points in the 2008 crisis. The stock-selection component has no measurable skill. The graduated drawdown probability does not beat the base rate out of fold."

Words that do not appear: edge, alpha, 40 to 75 percent.

Supporting figures (for the chapter's footnotes): point-in-time drawdown reduction 51.6% vs 29.7% (C3 context run on C2's strict series, tier-4 overlay, 2010-02-01 → 2026-05-21); annualized return 7.92% vs 14.52% buy-and-hold; paired return-per-volatility interval [+0.017, +0.318] on revised inputs and [+0.006, +0.201] on point-in-time inputs; crisis-inclusive drawdown reduction 63.7% vs 57.0% for vol targeting; out-of-fold Brier 0.1989 vs base rate 0.1918.
