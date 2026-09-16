# inbox/ — drop brokerage exports here

Drop two CSV files exported from the brokerage into this directory:

1. a **positions** CSV (one row per holding, with a cash / money-market line), and
2. a **transactions** (activity / history) CSV covering the period since the last export.

Any header dialect works — Schwab-style (`Symbol, Description, Quantity, Price, ..., Market
Value, ..., Cost Basis, ...` with a `Cash & Cash Investments` line), Fidelity-style (`Account
Number, Account Name, Symbol, Description, Quantity, Last Price, ..., Current Value, ..., Cost
Basis Total, Average Cost Basis, ...` with a `SPAXX**` money-market line), or anything whose
headers map through the synonym table in `scripts/ingest_brokerage.py`. The files are found
by **header sniffing, not by name**; preamble lines, BOMs, `$`/`,`/`%`/parenthesised numbers,
total rows and disclaimer footers are tolerated. Fractional shares are kept as exported.

`*.csv` in this directory is git-ignored (see `.gitignore`): raw exports are never committed.
The provenance that IS served is `input_sha256` and `exported_at` in `data/holdings.json`.

## Run the two jobs

```bash
# 1. positions + transactions → data/holdings.json (source "brokerage export")
.venv/bin/python scripts/ingest_brokerage.py                 # dry run: prints the header mapping it chose,
                                                             # the unmatched headers, the parsed positions and cash;
                                                             # full best guess under scratch/ingest_<timestamp>/
.venv/bin/python scripts/ingest_brokerage.py --write         # also writes data/holdings.json (only when every
                                                             # required column mapped; exit 2 otherwise)

# 2. each BUY/SELL transaction → one entry in data/actions.jsonl (tier 5_werner,
#    source "brokerage transactions", published regime R + label, the nightly signal record)
.venv/bin/python scripts/seed_actions_from_transactions.py           # dry run: prints the entries
.venv/bin/python scripts/seed_actions_from_transactions.py --write   # appends; idempotent per
                                                                     # (date, ticker, action, quantity, price, export hash)
```

`ingest_brokerage.py` exit codes: 0 ok · 2 a required column is unmapped (nothing served
written; the unmatched headers are printed — extend the synonym table and rerun) · 1 no CSV,
ambiguous files or unreadable input.

The seeding job reads the newest `scratch/ingest_*/transactions_parsed.csv` by default;
`--inbox inbox` re-parses the raw CSVs instead. Dividends, interest, fees and transfers are
counted and reported but never seeded; `--include-reinvest` seeds dividend-reinvestment
purchases as buys. Signal records come from git history of `data/ticker_signals.json`
(read-only `git log` / `git show`); `--no-signals` skips that.

Commit `data/holdings.json` and `data/actions.jsonl` after checking the printed report.
Then remove or archive the CSVs from this directory.
