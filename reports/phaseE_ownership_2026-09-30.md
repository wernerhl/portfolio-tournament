# Phase E report — Ownership and insider flows

Execution Order of 30 September 2026, items E1–E3. Executed 30 September 2026.

| commit | item |
|---|---|
| (E1) | [E1] Insider purchases: open-market Form 4 transactions, routine vs opportunistic, the cluster flag, the candidate signal registered |
| (E2) | [E2] Institutional ownership: quarterly 13F changes, every figure dated |
| (E3) | [E3] Congressional and executive trades: out — news only, labeled, nowhere else |

## The one blocking fact: EDGAR access

The SEC's fair-access policy requires automated clients to declare a contact of the form "Company Name contact@domain" in the User-Agent; every EDGAR host returned 403 to an undeclared client from this machine on 30 September (a browser-like string passes on one host and was not used — it would evade the policy rather than meet it). The address is not embedded anywhere: the jobs read `SEC_USER_AGENT` from the environment (a repository secret to add), exit 3 and write nothing without it, and the nightly only warns. Consequently no live Form 4 or 13F data exists on this machine; everything below is built and tested against fixtures, and the cards read "no EDGAR data on record (the ownership job needs the declared contact, SEC_USER_AGENT)" until the secret is set. The first live night then fetches the ticker map, ~43 submissions feeds, the last 90 days of Form 4 documents and twelve quarterly insider data sets (cached afterwards); the 13F job downloads the two latest quarterly data sets (about 100 MB each) once a week.

## E1 — Insider purchases

`scripts/ownership/insiders.py` → `data/ownership/insiders.json`. Open-market purchases (code P) and sales (code S) only; the last 90 days from the submissions feed and the Form 4 documents, the three prior years from the SEC's quarterly insider data sets kept in a store that fetches only the quarters it lacks. Classification by the Cohen, Malloy and Pomorski rule (2012): routine if the insider traded in the same calendar month in each of the three prior years; opportunistic otherwise, including insiders with fewer than three prior years (by the rule; the basis says which case). Per held name: the opportunistic purchases (insider, role, shares, dollars, date, the filing), the cluster flag when three or more distinct opportunistic insiders buy within 30 days, and sales only when opportunistic and clustered under "sales are mostly compensation or diversification"; the board carries the flag and counts.

Constructed test cases (`tests/test_ownership.py`, 18 passed): an insider buying every September for three years → routine, excluded; one who missed a year → opportunistic; one with two prior years → opportunistic by the rule; three distinct buyers within 30 days → the cluster fires (30 days fires, 31 does not); three buys by one insider → no flag; three opportunistic sellers → sales shown under the label, the routine seller excluded; the gate exits 3 and writes nothing without the contact; the live path end to end against a fake EDGAR. The referee (`insiders:*`) requires the stated classification and basis on every card row, the cluster flag consistent with the count, the sales rule, and the "enters no score" gate.

**Registration.** `reports/insider_signal_registration_2026-09-30.md` registers opportunistic-purchase clusters as a candidate return signal for the Phase 5 validation on the union universe (never the book): construction, factor neutralization, the C1 cost model, the paired bootstrap criterion and the pass threshold, point-in-time by filing date. Committed before any run; it enters no score before it passes.

## E2 — Institutional ownership (context only)

`scripts/ownership/holders_13f.py` → `data/ownership/holders_13f.json`, weekly: from the SEC's Form 13F data sets, for each held name the ten largest holders by shares with their change on the quarter, the new positions and full exits among funds above $1 billion of reported value (put/call and non-share rows excluded; one effective filing per manager and quarter). Every figure carries `as_of_quarter_end` and `disclosed`; each name carries the caption "positions as of {quarter-end}, disclosed {date}; long positions only; no hedges shown." (referee: `ownership:dates` CRITICAL, `ownership:caption` HIGH). No signal, no score. The fixture run reproduces the schema end to end and the referee accepts it (its only finding is the fixture's incomplete history).

## E3 — Congressional and executive trades (out)

Not added as signals, scores or panels, on the evidence the order states. In the news feed, a Tier-2 headline reporting a disclosed congressional or executive-branch trade in a held name carries the label "disclosed trade — reports lag the trade by up to 45 days; shown as news only, no signal" and appears nowhere else (`fetch_news.py`; test `test_disclosure_lag_label_e3`).
