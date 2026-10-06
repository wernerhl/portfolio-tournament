# Execution Order: Revision of the Entry-State Indicator and Related Fixes (6 October 2026, revised) — report

The revised order differs from the morning's text in four places:
1. **The WAIT state is removed**, and short interest of 20% or more of the float becomes a second heavily-shorted trigger (section 2).
2. **A new section 6b**, the operator's picks against QQQ.
3. **The registration gains the overbought events** as contestant (d) (section 7).
4. **Two more ledger entries.**

Sections 3–6 were implemented this morning, unchanged by the revision: the ceiling, the provider checks, earnings timing and conflicts, days-to-cover, the volume check and the drawer. Their commits are 3c596ca..36d9854, prefixed by the morning's numbering. This afternoon's commits carry the revised numbering:

| item | section | commit |
|---|---|---|
| [R1] | 2 · rules version 3: no WAIT, the short-interest trigger | 4f3719b |
| [R2]–[R5] | 3–6 · done this morning, no change needed | 3c596ca..2a9848c |
| [R6] | 6b · picks against QQQ | f571322 |
| [R7] | 7 · registration v4 | e35f948 |
| [R8] | 8 · the two new ledger entries | 2eb9f04 |
| [R9] | 9 · referee and this report | this commit |

## Acceptance

| # | criterion | result |
|---|---|---|
| 1 | referee before and after; zero CRITICAL | Before (`reports/audit_2026-10-06_R2_before.txt`, the committed tree at c096619, run in a clean worktree): 30 findings, 0 CRITICAL. After (`…_R2_after.txt`): 30 findings, 0 CRITICAL, line for line the same. |
| 2 | states at the 5-Oct close | See the list below the table. |
| 3 | Incyte's card: ceiling near $131.50, 5-year high, all-time high $152.66 | Ceiling **$131.47** (2015-09 $131.47 then −27.6%; 2026-07 $129.93 then −12.2%), state capped at WATCH. 5-year closing high $129.93 (2026-07-28). All-time closing high **$152.66** (2017-03-15). The provider's close series gives $131.47 for the 2015 peak. |
| 4 | TPL's forward P/E and free cash flow greyed with the reason | Unchanged since this morning: greyed and struck through on the book page's TPL card, each with its reason. |
| 5 | GEV's reactions, before-open: −4.5, +1.3, +2.7, +3.1, +14.6, −1.6, +2.7, +13.7, −8.7 | Exact (2024-07 to 2026-07, all before the open). |
| 6 | max pain and dealer gamma only in the drawer | The book page has neither phrase outside a details drawer (checked in the preview). |
| 7 | section 7 registration committed before any run | `reports/entry_state_validation_registration_v4_2026-10-06.md` and `data/entry_state_validation_registration_v4.json` (e35f948). No run has happened or can happen until the data arrives. |
| 8 | the seven ledger entries | `mistake-2026-10-06-1` to `-06-4`, `2026-10-05-1`, `-05-2` and `2026-10-02-3` are present; the ledger verifies intact. |
| 9 | picks against QQQ | See below the table. |

**Acceptance 2, the states at the 5-October close:**
- **Lockheed Martin: READY-HALF.**
  - Flags: `below_200d` and the earnings-date conflict (provider 22 Oct, WSJ 27 Oct, investor relations 22 Oct).
  - Stop **$487.62** (40-session low $498.55 less ATR $10.93).
- **Micron: READY at full size.**
  - It is above its 200-day ($1,063.96 against $685.77) with 12-1 momentum of +421%.
  - Earnings are on 23 December (56 sessions away). It reads 1.07 days to cover and 2.5% of the float short.
  - 4 shares, with $1,045 at risk.
- **Powell: READY with `below_200d` at half size.**
  - Close $197.84 under the 200-day $208.09, momentum +70.9%, RSI 78 (extended).
  - Earnings 17 Nov, 31 sessions away.
  - 15 shares, half the base.
- **No WAIT anywhere.** 0 of 535 names. The board, the book, the tournament and the home page carry no WAIT.
- **Incyte: WATCH** with the ceiling flag. Its modifiers are earnings and heavy shorting (7.62 days to cover).
- **Texas Pacific Land:** heavily shorted (days-to-cover **12.59**), with the provider-data flag on forward P/E, free cash flow and revenue growth.
- **Ondas: AVOID.**
  - Close **$7.42**, 200-day **$9.44**, 12-1 momentum **−17.2%**.
  - Heavily shorted, set by short interest of **41.0%** of the float. Its 3.83 days to cover would not have set it.

**Acceptance 9, the picks-against-QQQ panel:** it is on the book page and renders from `data/actions.jsonl` with `data/tournament.json`.
- The number of independent decisions (n) sits beside every figure.
- The algorithmic tiers appear pooled, with each tier in a drawer.
- Index funds, sector funds and gold are excluded by list; none was held in the windows.
- The panel states that below about 30 decisions it cannot distinguish skill from chance.

## The picks against QQQ, through the 5-October close

| book | window | difference | % | risk-adjusted | closed that beat QQQ | n |
|---|---|---|---|---|---|---|
| Operator | from 1 Oct (from the 30-Sept close) | +$912 | +1.05% | +$232 | none closed | 2 |
| Algorithmic tiers | from 1 Oct | −$3,277 | −0.66% | −$4,297 | 18 of 40 | 5 (closed: 2) |
| Operator | since the first logged trade (from the 15-Sept close) | −$195 | −0.14% | −$1,527 | 3 of 5 | 2 (closed: 1) |
| Algorithmic tiers | since the first logged trade | −$9,502 | −1.94% | −$12,319 | 11 of 40 | 5 (closed: 2) |

QQQ rose 2.22% from 30 Sept and 6.63% from 15 Sept. With 2 and 5 independent decisions, these figures are descriptive.

## Decisions taken, stated

1. **The risk adjustment.** The order's phrase "each position's excess return divided by its beta to QQQ times QQQ's return" is read as the return in excess of beta times QQQ's return.
   - It is implemented as a shadow holding beta dollars of QQQ per dollar in the position, with the same dollars in and out.
   - Beta comes from the 252 sessions of daily returns before the position's start (a minimum of 60, else 1).
   - The plain difference uses a beta of 1.
2. **Dates without the brokerage export.** The transactions log has no export rows yet.
   - The operator's dates come from holdings snapshots (the trade was on or before the snapshot) and from the two trades the operator reported (MU and ANET).
   - A reported trade replaces the snapshot change it explains.
   - **ANET** (sale reported 16–18 Sept, before the first snapshot that shows the purchase) and **MU** (bought and sold in one session by the log) cannot be placed in time. They are listed as not measurable and enter no figure.
   - The panel says all of this, and the figures become exact once the export is ingested.
3. **"Since the first logged trade"** starts at the first day the log allows for the operator's first trade row: the ANET sale's range begins 16 Sept, so the window opens at the 15-Sept close. The tiers use the same dates.
4. **Independent decisions.** These are distinct entry dates. Positions held when the record begins (20 May) count as one decision. The tiers pooled count distinct dates across tiers, since all four rebalance on the same scoring.
5. **Prices.** The record's as-published closes are used for positions and QQQ alike. A full exit is priced at the exit session's canonical close; a sale priced at the prior close lost the exit day, a defect found and fixed before commit. Price returns only; dividends are left out.
6. **Version 2 kept for the record.** The morning's version-2 configuration is kept byte-identical (`data/entry_state_config_2026-10-06_v2.json`, sha `4aa58cc4`). The registration that pinned it is superseded before any run and left unedited.
7. **Short interest as a share of the float** is the provider's `shortPercentOfFloat`, from the canonical fetch (now also fetched for names under review).
   - Ondas reads 41.0%; the order's 41.6% is presumably from another source.
   - Either way it is above 20%, and its days-to-cover of 3.83 matches the order's 3.8.
8. **Entry timing in a drawer.** Section 2 has entry timing "displayed as information", and section 6's main-view rule shows a field only if it can change a state, a size or an exit. The setup measures and the confirmation therefore sit in an "entry timing" drawer on every card.

## Consequences to know

- **More READY names.** At the 5-Oct close the count is 234 READY and 75 READY-HALF, against 125 and 26 under version 2. Of the 180 names that read WAIT, 123 now read READY, 36 READY-HALF and 21 WATCH.
- **Short interest of the float flags 19 names** with 20% or more, including Ondas, Charter (38.8%), Skyworks (34.4%) and The Trade Desk (24.2%). For 14 of them it is the only trigger: their days-to-cover is under 7.
- **Published history keeps its words.** The entry-state log keeps this morning's v2 transitions (some "to WAIT"), as published. New log lines carry `rules_version`. This morning's daily brief also keeps its facts as published.

## Left for the operator

1. **The brokerage transactions export** (inbox/, then `ingest_brokerage.py --write` and `seed_actions_from_transactions.py --write`). It turns the panel's snapshot dates into trade dates and prices, and makes ANET and MU measurable.
2. **The survivorship-free data**, to run the registered validation (v4).
