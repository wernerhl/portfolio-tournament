# Synthetic brokerage export fixtures

**Everything in this directory is SYNTHETIC.** The account numbers, tickers, quantities,
prices, dates and cash balances are made up for `tests/test_ingest_brokerage.py`; they do
not describe any real account, trade or holding, and nothing here is served.

| file | dialect | purpose |
|---|---|---|
| `schwab_like_positions.csv` | Schwab-style: preamble line with "as of" stamp, quoted cells, `$`/`,` numbers, `Cost Basis` = **total** cost, a `Cash & Cash Investments` line, an `Account Total` line, a disclaimer footer | header mapping, total-cost → per-share division, fractional shares (`100.1509`), padded ticker (`" ANET "`), cash from the cash line, export stamp → `as_of` / `exported_at` |
| `schwab_like_transactions.csv` | Schwab-style `Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount`; includes a Saturday trade date, a `MM/DD/YYYY as of MM/DD/YYYY` date, dividends, bank interest, a transfer and a `Reinvest Shares` line | transaction mapping, action classification, session mapping, no-publish regime note, idempotent seeding |
| `fidelity_like_positions.csv` | Fidelity-style: `Account Number,...,Cost Basis Total,Average Cost Basis,Type` with a `SPAXX**` money-market line, a `Pending Activity` line, leading-space cells, `Date downloaded` footer | per-share average cost preferred over total, money-market cash line, `Type = Cash` on equities NOT taken as cash, `**` suffix stripped |
| `fidelity_like_history.csv` | Fidelity-style `Run Date,...,Action,Symbol,...,Quantity,...,Price,...,Commission,Fees,...,Amount,Settlement Date` with negative sell quantities and long `YOU BOUGHT ... (Cash)` actions | `Run Date` → date, negative quantity → sell size, `Settlement Date` not confused with the trade date |
| `broken_positions_unmappable_qty.csv` | positions with the quantity column headed `Holding Amt` (not in the synonym table) | required column unmapped → exit 2, nothing served, best guess in scratch |

Tests copy these into temporary directories; nothing under `data/` or `inbox/` is ever written by them.
