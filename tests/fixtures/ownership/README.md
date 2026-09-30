# Synthetic EDGAR fixtures for the ownership module

**Everything in this directory is SYNTHETIC.** The insiders, funds, CIKs, accession numbers,
share counts, prices and dates are made up for `tests/test_ownership.py`; the issuer CIKs and
tickers are real only so the universe lookup works, and nothing here describes any real filing,
trade or holding. Nothing here is served.

Both jobs read this directory with `--offline tests/fixtures/ownership` (no network; `--data-dir`
or `--dry-run` required so fixture output never lands in the repository's `data/`). The as-of
date the tests use is 2026-09-30 (window 2026-07-02 .. 2026-09-30).

| path | what it stands in for | what it exercises |
|---|---|---|
| `universe.json` | `data/holdings.json` + the screen board's top-40 rows | held = NVDA, AVGO, GOOG, GEV, MU; board = NVDA, AVGO, GOOG, GEV, LMT, TSM (TSM files no Form 4) |
| `company_tickers.json` | `https://www.sec.gov/files/company_tickers.json` | ticker → CIK, company titles for the 13F name match |
| `form4/*.xml` | the live Form 4 ownership documents of the last 90 days (file name = accession) | P/S parsing, dollars = shares × price, ignored codes (F, M, A, derivative table), a joint filing (MU: two reporting owners), a trade outside the window (NVDA 2026-06-20) |
| `form4/filings.json` | the submissions feed's `filingDate` / `primaryDocument` per accession | filing dates and EDGAR folder URLs on the card rows |
| `datasets/2023q1_form345/`, `2023q3`, `2024q3`, `2025q3` | the SEC quarterly Insider Transactions data sets (SUBMISSION, REPORTINGOWNER, NONDERIV_TRANS; dates as `DD-MON-YYYY`) | the three-prior-year histories: Rita buys every September (routine), Oscar has three years but missed September 2023 (opportunistic), Tina has two prior years plus a non-open-market `M` row (opportunistic by the rule), Ned's only 2023 row is a `4/A` (excluded), Rob sells every September (routine seller), a noise issuer that must not appear |
| `13f/01mar2026-31may2026_form13f/`, `13f/01jun2026-31aug2026_form13f/` | two quarterly Form 13F data sets (SUBMISSION, COVERPAGE, SUMMARYPAGE, INFOTABLE) | top-10 by shares (11 holders, one dropped), share change, a RESTATEMENT amendment that replaces the original, a late prior-quarter filing inside the next window, new positions and full exits above/below $1B, a PUT-only fund and a `PRN` row (excluded), a prior holder with no current filing (not an exit), a `13F-NT` notice (ignored), Alphabet class A vs class C kept apart |

Expected results the tests pin down: NVDA cluster flag on (Oscar, Tina, Ned within 20 days; Rita
excluded as routine); AVGO three buys by one insider, no flag; GOOG three distinct opportunistic
sellers → sales shown under the label, the routine seller excluded; GEV two sellers → nothing
shown; LMT board-only flag with no card fields; NVDA 13F top holder 1,250,000 shares (restated),
+250,000 on the quarter, disclosed 2026-08-20; new ≥$1B: Dover, Nova Point; exits ≥$1B: Birch,
Pine Valley; Maple Grove listed as "no current filing".
