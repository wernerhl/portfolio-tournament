# Options lens — Phase 4 (the hedge selector: held names, descriptive, DIAGNOSTIC)

Order 26 September 2026, commit [O4]. `scripts/options/hedge_selector.py`, rules frozen in
`data/options/hedge_rules.json`, output `data/options/hedges.json`, rendered on the book
page. Every row carries "DIAGNOSTIC: descriptive; no execution path; option overlays not yet
validated" (acceptance §9.5).

## Referee

Unchanged: 45 findings, 19 CRITICAL, all pre-existing freshness; `options:language` and
`options:directive` pass on hedges.json.

## What is priced, per held name, at two tenors

The first expiry beyond the next earnings release and the expiry nearest 90 days. Four
structures (five rows — the protective put at 10 and at 15 percent): protective put, put
spread 10/20, collar 15% put / 10% call, covered call 10% OTM. For each: net cost or credit
per share and on the position (contracts noted), floor and cap, breakeven, the change in
position delta, and the book's loss in the three standing scenarios (SMH −30, SPY −20, SPY
−34) with the structure in place — the position's stressed price is spot × (1 + β_index ×
shock), and the structure's payoff at that price less its premium replaces the position's
unhedged loss in the book total. Legs are priced at the chain's price_used; a leg priced at
the last trade is flagged.

## The rankings against the 25-Sept vintage (first tenor)

| name | risk share | state | term | earnings in tenor | ranked first | rule | SPY −20 book loss, unhedged → with structure |
|---|---|---|---|---|---|---|---|
| MU | 60% | mixed | inverted | yes (09-30) | collar 15/10, credit $10.20/sh | 1 (risk share > 40%); covered call excluded by rule 5 | 34.4% → **21.3%** of NAV |
| NVDA | 7% | cheap | — | yes (11-17) | protective put 15%, $2.23/sh | 2 (cheap → protection) | 34.4% → 32.3% |
| GEV | 12% | cheap | — | yes (10-28) | protective put 15%, $10.15/sh | 2 | 34.4% → 31.9% |
| AVGO | 7% | cheap | — | yes (12-09) | protective put 15%, $5.28/sh | 2 | 34.4% → 32.8% |
| BMNR | 2% | cheap | — | yes (11-20) | put spread 10/20, $1.09/sh | 2 | 34.4% → 34.2% |
| ANET | 10% | mixed | — | yes (11-03) | protective put 10%, $7.28/sh | none fired: the registered order | 34.4% → 31.9% |
| GOOG | 2% | mixed | — | yes (10-28) | protective put 10%, $2.84/sh | none fired: the registered order | 34.4% → 33.0% |

The reading the panel makes plain, without a verb: the book's stress is one position. A
collar on MU alone moves the SPY −20 book loss by 13 points of NAV; protection on any other
name moves it by one to two points.

## Rules, as registered

1. Risk share above 40 percent: collar first, regardless of volatility state. 2. State cheap:
protective put or put spread first. 3. State rich with no earnings inside the tenor: covered
call first. 4. Calls richer than puts at matched distance: collar first. 5. Earnings inside
the tenor and term structure inverted: no naked premium selling ranked. 6. Embedded gain over
50 percent on cost: structures avoiding a sale rank above a trim at the same stress
reduction, the tax consideration in words, no computation (no held name is above 50% on
cost today; NVDA at +153% in the signals record is measured on a split-adjusted basis the
book's cost field does not use — the flag follows the book's field). Among structures a rule
ranked first the cheaper leads; with no rule fired the registered order (protection first)
stands, so a credit never ranks first merely for being a credit.

## Deviations

- None against the order's list. The overlays are unvalidated until the Phase 5.3 tests run
  (which need the item-1.4 history); the label stays on every row until then.
