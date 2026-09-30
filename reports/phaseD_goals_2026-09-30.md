# Phase D report — The operator's goals

Execution Order of 30 September 2026, items D1–D3. Executed 30 September 2026.

| commit | item |
|---|---|
| ddacff9 | [D1] House goal in reais at the live rate |
| 80765a1 | [D2] Claims register, never edited |
| 528b546 | [D3] Realized gains: the parser; 2025 seeded from the operator's total |

## D1 — House goal

`scripts/compute_goals.py` → `data/goals.json` (nightly at the last settled USDBRL close; every two hours at the live tape, stamped intraday). At the 29-September close, USDBRL 5.2229:

| figure | value |
|---|---|
| total book in reais | R$1,227,921 — 49.1% of the R$2,500,000 target (the order: about 49% at 5.20) |
| cash in reais | R$774,645 — 31.0% (the order: about 31%) |
| the target in dollars at the rate | $478,661 |
| months remaining to 2029-09-18 | 36 |
| required monthly savings on the reais floor | 0%: R$35,336 ($6,765) · 5%: R$27,877 ($5,337) · 13%: R$16,832 ($3,223) |

FX sensitivity row (the target's dollar cost and the book's reais value at 4.6 … 5.8) on the card. Descriptive; no recommendation.

**Deviation.** The analysis of 18 September was not found on this machine (the trading folder, the repository and its full history were searched for the target, the rate, the savings figures and the account value; nothing matches), so the sensitivity row is recomputed from the same inputs and the card says so.

## D2 — Claims register

`data/claims_register.json` records the claim exactly: account value $229,245.80 on 18 September 2026; target 29 percent annualized for three years. The record is immutable: the referee pins it (`claims:record_changed`, CRITICAL if the 18-Sept claim's fields change) and `goals.json` only computes against it (`register_sha256` must match, else HIGH). Progress at the 29-September close: NAV $235,103, since start +2.56% over 7 sessions (11 calendar days), annualized equivalent +148.0% shown in amber with the caption "annualized figures under one year are not informative"; the 29 percent path stands at $231,011 today (gap −$4,093), and at $295,727 / $381,488 / $492,120 at one, two and three years.

## D3 — Realized gains

`scripts/ingest_realized_gains.py` parses the brokerage's realized gain/loss CSV by header sniffing (Schwab-, Fidelity- and generic-style dialects; term from the column, else derived from the dates; wash sales reported, never netted; a reconciliation of the export's 2025 net against the operator's $42,453.34) → `data/realized_gains.json` by year and by position, short- and long-term. `scripts/ingest_inbox.py` runs it with the other two ingestion jobs. Until the export is ingested the served file carries the operator's report: 2025 net $42,453.34, all short-term; 2026 year to date pending. Tests: 16 passed. Descriptive; no tax computation — the card says so.
