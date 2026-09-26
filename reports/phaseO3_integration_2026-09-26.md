# Options lens — Phase 3 (integration with fundamentals and momentum)

Order 26 September 2026, commit [O3] (items 3.1–3.4). Verified in the preview at 1400 px on
the book, tournament and screen views: no console errors, zero page-level horizontal
overflow. Screenshots: `reports/shotsO/{book,tournament,screen}_1400.jpg`.

## Referee

Unchanged by this phase (the pages are not audited): 45 findings, 19 CRITICAL, all
pre-existing freshness.

## 3.1 — the third column (acceptance §9.4)

The two-score card, on the tournament view (a scanner row expanded) and on the book page
(every position), shows three rows side by side: Business Quality, Trade-Now (the setup
reading, or the position-vs-rulebook reading for held names), and **Options** — the
volatility state with its marker (◯ cheap, ● rich, ◐ mixed; IMPAIRED when fewer than 70% of
front-expiry strikes carry live quotes), IV30 against RV21 and RV63, the term structure with
its reason when inverted, the event line, the skew with the 25-delta risk reversal beside
it, and for held names the structure the hedge selector ranks first with its cost and the
DIAGNOSTIC label. Dealer gamma is a collapsed block with its convention and caveat. MU's row
today: *IV30 59.1% · RV21 49.0% · RV63 78.3% · term inverted (earnings 2026-09-30 inside the
front tenor) · ◐ MIXED · earnings 2026-09-30 (5d, 3 sessions); market prices ±7.8% from the
2026-10-02 expiry; median past reaction 5.2% over 24; 8 of 24 exceeded; 5 of last 8
exceeded · skew −2.0 pts.* The screen board carries an OPTIONS column for all 40 names
(state marker, days to earnings ringed inside 30 days, the implied move).

## 3.2 — the scanner's third dimension

The scanner encodes the options state by marker (hollow for cheap, filled for rich, half for
mixed) in a sortable OPTIONS column and rings any name with a release inside 30 days (◎ and
the day count); an "◎ Earnings ≤30d" filter chip isolates them. Today: 53 scanner names, 19
with a chain vintage (the options universe is the held names, the board's top 40 and the
three index ETFs; the rest read "—"), 4 ringed. **Deviation:** the order describes "the
Business Quality versus Trade-Now scatter"; the scanner is the ranked quality × setup table
and there is no scatter chart in the site, so the marker encoding is applied to that table.

## 3.3 — the event line on held names' signal boxes

Whenever a release falls within 10 sessions, the position-mode box carries the event line
under the observation. Today MU (3 sessions to the 30-Sept release) shows it; no other held
name is inside 10 sessions.

## 3.4 — the event board (acceptance §9.4)

On the book page, above the stress and sleeves panels: every held name with a release in the
next 45 days, sorted by date, with the release and its time of day, the implied move in
percent and in dollars on the position, the historical median and maximum reaction, the
last-eight exceedance, and the position's share of book risk. Today: MU (30 Sept, ±7.8%,
±$3.8k on the position, median 5.2%, max 16.2%, 5 of 8, 60% of book risk), GEV (28 Oct,
±2.9%), GOOG (28 Oct), ANET (3 Nov).
