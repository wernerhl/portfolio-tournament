# Phase 4 report — Book-aware sizing, descriptive

Execution Order of 16 September 2026, Phase 4. Executed 16 September 2026, 13:40 CST. Commit: see `git log --grep='^\[4\]'` (the posture card retitled and its caption completed).

## 1. Referee, verbatim

Phase 4 changes no data file. Before and after are the reading after Phase 3 (`reports/audit_2026-09-16_phase3_after.txt`, copied as `reports/audit_2026-09-16_phase4_after.txt`): 20 findings, 0 CRITICAL, HIGH unchanged.

## 2. What the panel holds

The order pre-answers this phase: "This is the comparators panel of 1.4 with the tier schedules added; if 1.4 already renders them, this phase is a reorganization rather than new computation." Item 1.4 rendered the tier schedules from the first commit (`comparators.json → book_posture.rows`, kind `regime_schedule`, one row per tier including WERNER, each with today's cash share scaled by the equity sleeve's beta and the full-deployment share), volatility targeting at 10 and 15 percent on the book's own realised volatility (60-session registered window, 126-session figure beside), and the actual equity share beside every row. The nightly recomputes it (compute_book.py, then compute_comparators.py). No execution path exists: the job writes a JSON file and the page renders a table.

Phase 4 therefore retitles the card "BOOK-AWARE SIZING, DESCRIPTIVE · posture versus every rule at the book's beta · updated nightly", completes the caption with the order's description and the sentence **"descriptive; no rule drives this book."**, and leaves the computation untouched. The card moves to `book.html` with the merge (6.3).

## 3. Figures on the card (through the 14-Sept close)

| rule | index share (β = 1) | translated to the book (β 2.47) | actual |
|---|---|---|---|
| regime schedule · CAP PRES | 54.9% | 22.2% (full deployment 30.3%) | 66.5% |
| regime schedule · BALANCED | 66.2% | 26.8% (34.4%) | 66.5% |
| regime schedule · AGGRESSIVE | 79.3% | 32.1% (36.4%) | 66.5% |
| regime schedule · TACTICAL | 73.2% | 29.6% (40.5%) | 66.5% |
| regime schedule · WERNER | 66.2% | 26.8% (34.4%) | 66.5% |
| ten-month SMA | 100% | 40.5% | 66.5% |
| 12-1 momentum | 100% | 40.5% | 66.5% |
| volatility targeting 10% | 86.1% | 34.8% · on the book's own volatility 21.2% | 66.5% |
| volatility targeting 15% | 100% | 40.5% · on the book's own volatility 31.9% | 66.5% |

## 4. Deviation

None beyond the order's own allowance (reorganisation, not new computation).
