# Phase 5 report — Diversification sleeves, quality-gated

Execution Order of 16 September 2026, Phase 5. Executed 16 September 2026, 13:50 CST. Commit: `git log --grep='^\[5\]'`.

## 1. Referee, verbatim

Before: the reading after Phase 4 (`reports/audit_2026-09-16_phase4_after.txt`). After (`reports/audit_2026-09-16_phase5_after.txt`): 20 findings, 0 CRITICAL, HIGH unchanged — Phase 5 changes only `book.json`'s sleeves block.

## 2. The panel

`compute_book.py` writes `sleeve_groups`: four groups — staples and defensives (XLP, XLU; registry thesis defensive_quality), energy and hard assets (XLE, GLD; hard_assets), financial plumbing (XLF; fin_plumbing), Treasuries and gold (TLT, GLD; no equity thesis) — each sleeve with its 126-session correlation to the equity book's constant-weight return series, and within each group the screen view's names that pass its quality bar (fundamental ≥ 18 and visibility ≥ 15, the drawdown shelf's bar) and carry a registry thesis in the group, with their correlation to the book and their screen composite. The panel's heading is the order's sentence: "exposures the book lacks, at the level where the system has evidence". The flat ascending list of item 1.6 stays underneath as "other sleeves" (IWM).

Correlations through the 14-Sept close: XLP −0.44, XLU −0.03 · XLE −0.28, GLD +0.42 · XLF −0.02 · TLT +0.24, GLD +0.42 · IWM +0.66.

## 3. What the quality gate returns today

Of the 533 names on the screen view's board, 224 have fundamental ≥ 18 and 17 have visibility ≥ 15 (visibility above 15 requires a registered override; the sector fallback is capped at 10). Ten pass both: AVGO, GEV, TSM, GOOG, VRT, NVDA, ANET, ETN, META — all members of ai_infra — and LMT, which carries no registry thesis. None belongs to any of the four sleeve groups, so every group renders the line "no screen name in <thesis> passes the quality bar (fundamental ≥ 18, visibility ≥ 15) — the group's evidence is its ETFs". That is the level where the system has evidence, and the panel says so rather than lowering the bar.

## 4. Deviation

None. The quality bar is the screen view's own; the panel would fill the moment a defensive, hard-asset or financial name earns a registered visibility override and a fundamental score of 18.
