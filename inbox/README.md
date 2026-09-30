# inbox/ — drop brokerage exports here

Drop up to three CSV files exported from the brokerage into this directory:

1. a **positions** CSV (one row per holding, with a cash / money-market line),
2. a **transactions** (activity / history) CSV covering the period since the last export, and
3. a **realized gain/loss** CSV (one row per closed lot: symbol, closed/sold date, quantity,
   proceeds, cost basis, gain/loss, short/long term, wash-sale amount).

Any header dialect works — Schwab-style (`Symbol, Description, Quantity, Price, ..., Market
Value, ..., Cost Basis, ...` with a `Cash & Cash Investments` line), Fidelity-style (`Account
Number, Account Name, Symbol, Description, Quantity, Last Price, ..., Current Value, ..., Cost
Basis Total, Average Cost Basis, ...` with a `SPAXX**` money-market line), or anything whose
headers map through the synonym table in `scripts/ingest_brokerage.py`. For the realized
gain/loss export the same holds: Schwab-style (`Symbol, Name, Closed Date, Opened Date,
Quantity, ..., Proceeds, Cost Basis (CB), Gain/Loss ($), ..., Long Term Gain/Loss, Short Term
Gain/Loss, Wash Sale?, Disallowed Loss`), Fidelity-style (`Symbol, Description, Date Acquired,
Date Sold, Quantity, Proceeds, Cost Basis, Short Term Gain/Loss, Long Term Gain/Loss, Wash Sale
Loss Disallowed`) or a generic `..., Gain/Loss, Term` layout — synonym table in
`scripts/ingest_realized_gains.py`. The files are found by **header sniffing, not by name**
(the realized-gains export is the one with a closing/sale date column); preamble lines, BOMs,
`$`/`,`/`%`/parenthesised numbers, `--` blanks, total rows and disclaimer footers are tolerated.
Fractional shares are kept as exported. If the export has no term column the term is derived
from the acquired and closed dates (held more than one year = long) and the report says so.
Wash-sale amounts are reported separately, never netted.

`*.csv` in this directory is git-ignored (see `.gitignore`): raw exports are never committed.
The provenance that IS served is `input_sha256` and `exported_at` in `data/holdings.json` and
`data/realized_gains.json`.

## The one-shot

```bash
.venv/bin/python scripts/ingest_inbox.py --dry-run   # classifies the CSVs, runs all three jobs WITHOUT --write,
                                                     # moves nothing; prints every job's mapping report
.venv/bin/python scripts/ingest_inbox.py             # runs, in order, ingest_brokerage.py --write,
                                                     # seed_actions_from_transactions.py --write,
                                                     # ingest_realized_gains.py --write; then archives
```

`ingest_inbox.py` tolerates the absence of any one file type (the step that needs it is skipped
and the report says why) and refuses two files of the same kind (ambiguous, exit 1). After a
write run the CSVs whose job exited 0 are **moved to `inbox/archive/<ET timestamp>/`**
(git-ignored); a file whose job failed — exit 2, a required column unmapped — stays here for
you to extend the synonym table and rerun. The run ends with a checklist of the served files
that changed (`data/holdings.json`, `data/holdings_export.json`, `data/actions.jsonl`,
`data/realized_gains.json`); commit those. Exit code: 0 all good · 2 a column unmapped
somewhere · 1 ambiguous / nothing to do.

## Or run the three jobs by hand

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

# 3. realized gain/loss export → data/realized_gains.json (source "brokerage realized gain/loss
#    export"): gain and loss by year (from the closing date) and by position, short-term /
#    long-term, wash sales reported separately; the 2025 net is reconciled against the
#    operator-reported $42,453.34 (a mismatch is a printed WARNING and a `reconciliation` block)
.venv/bin/python scripts/ingest_realized_gains.py            # dry run: mapping report, per-year / per-position table;
                                                             # best guess under scratch/realized_gains_<timestamp>/
.venv/bin/python scripts/ingest_realized_gains.py --write    # replaces data/realized_gains.json (the operator-report
                                                             # seed included) — only when every required column mapped
```

`ingest_brokerage.py` and `ingest_realized_gains.py` exit codes: 0 ok · 2 a required column is
unmapped (nothing served written; the unmatched headers are printed — extend the synonym table
and rerun) · 1 no CSV, ambiguous files or unreadable input. Note that `ingest_brokerage.py` on
its own reads every CSV in this directory and would take a realized-gains export for a second
positions file — run it through `ingest_inbox.py`, or pass `--positions`/`--transactions`
explicitly, when all three files are here.

Until the first realized-gains export is ingested, `data/realized_gains.json` is the
operator-report seed (`source: "operator report, pending export confirmation"`,
`pending_export: true`, 2025 net $42,453.34 all short-term, 2026 pending); recreate it with
`scripts/ingest_realized_gains.py --seed-operator-report --write`.

The seeding job reads the newest `scratch/ingest_*/transactions_parsed.csv` by default;
`--inbox inbox` re-parses the raw CSVs instead. Dividends, interest, fees and transfers are
counted and reported but never seeded; `--include-reinvest` seeds dividend-reinvestment
purchases as buys. Signal records come from git history of `data/ticker_signals.json`
(read-only `git log` / `git show`); `--no-signals` skips that.

Commit `data/holdings.json` and `data/actions.jsonl` after checking the printed report.
Then remove or archive the CSVs from this directory.
