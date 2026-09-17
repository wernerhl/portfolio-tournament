# Fixed-income module — Phase 4 (book integration, the module's distinctive output)

Order 16 September 2026. Commits [B4.1] correlation to the equity book, [B4.2] the
conditional message, [B4.3] the whole-portfolio view. Plus [B] the nightly pipeline wiring.

## Referee, before and after

**20 findings, 0 CRITICAL** (`reports/audit_2026-09-16_bonds_B4_after.txt`). All bond checks
pass clean.

## Numeric checks (through the 2026-09-16 book and the 2026-09-15 FRED close)

**4.1 Correlation to the equity book.** The sleeve menu is sorted by correlation to the book
ascending, because a sleeve's value to this book is its correlation with what is already
held, not its standalone yield. Order: SHV (−0.02), TLT (0.24), FLOT (0.26), TIP (0.27), SHY
(0.28), GOVT (0.29) … high yield last (HYG/JNK ~0.52). Same 126-session computation as the
book panel. Acceptance §9.5 (the menu sorts by correlation) holds.

**4.2 The conditional message.** The top name (MU) is **57%** of the book's variance, above
the 40% threshold, so the message fires with measured numbers (acceptance §9.5): adding 10%
of NAV ($22,218) in an intermediate Treasury (IEF, ~0 equity beta, funded from cash) leaves
the SPY −20% stress loss at **−32.9%** of NAV essentially unchanged and moves book volatility
from **31.5%** to **31.5%**; halving MU to cash instead takes the SPY −20% loss to **−25.4%**
of NAV (a 7.4-point move). The computation reproduces `book.json`'s `vol_ann_with_cash`
(0.3149). A per-sleeve marginal table (Δvol, SPY beta, Δstress) accompanies it. The honest
first message — fixed-income diversification has limited effect until the equity concentration
is reduced — is shown, not buried.

**4.3 The whole-portfolio view.** One combined panel (acceptance §9.6): the equity stress
scenarios (SMH −30 −18.6% NAV, SPY −20 −32.9%, SPY −34 −55.8%, AI-infra −30, memory −40,
BMNR→0) alongside the fixed-income sleeves' rate shock (±100bp via duration: TLT ±16.5%, IEF
±7.3%) and spread shock (index OAS widened to its 90th percentile: IG 80→123 bp, HY 271→397
bp; LQD −3.6%, HYG −4.0%, EMB −8.8%, MUB −2.7%). The book holds no bonds, so the fixed-income
rows are per-sleeve sensitivities shown beside the equity book. Descriptive.

## Pipeline

`update_daily.py` now runs `bonds/fetch_sleeves.py` → `bonds/build_sleeve_metrics.py` →
`bonds/compute_bonds.py` after the comparators. The module reads the same `holdings.json` and
shares the same referee. No deviations in this phase.
