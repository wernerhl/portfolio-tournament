# Execution Order: Global Rates Panels on the Bonds Page (6 October 2026) — report

All items are committed as [G1]–[G9]. The panels sit in a new GLOBAL RATES tier on `bonds.html`, the strip under the regime gauge on the home page, and the facts in the daily log. Every number is descriptive.

## Acceptance

| # | criterion | result |
|---|---|---|
| 1 | referee before and after, zero CRITICAL | Before (`reports/audit_2026-10-06_G_before.txt`, the committed tree and referee): 30 findings, 0 CRITICAL. After (`…_G_after.txt`): 30 findings, 0 CRITICAL, the same findings by check. |
| 2 | Panel B from FRED: 10-year 5.28% (2 Oct), real 2.92%, breakeven 2.36% (5 Oct), Kim-Wright 1.02% (25 Sept); twelve-month changes +1.18, +1.16, +0.03, +0.51; history line 29 April 2010 | Exact: 5.28 (2026-10-02), 2.92 (2026-10-02), 2.36 (2026-10-05), 1.0203 (2026-09-25); twelve-month changes +1.18, +1.16, +0.03, +0.51. "The Kim-Wright term premium, 1.02% on 2026-09-25, was last at or above this level before 2026 on 2010-04-29." |
| 3 | Panel A, August 2026 averages US 4.68, DE 3.18, GB 4.99, JP 2.94, FR 4.00, IT 3.99, CA 3.67; 36-month average pairwise correlation 0.73 | Exact (Canada's FRED value is 3.675, shown 3.67). Average pairwise correlation 0.7289 → 0.73; with the U.S.: Canada 0.88, UK 0.77, France 0.67, Germany 0.65, Italy 0.64, Japan 0.57, the order's figures. |
| 4 | daily series for Germany, the UK, Japan and Canada with the source named; Japan's MoF 10-year above 3.0% on 24 Sept | Germany: Bundesbank statistics API, through 6 Oct. UK: Bank of England database (zero-coupon), through 2 Oct. Japan: Ministry of Finance JGB files, through 5 Oct. Canada: Bank of Canada Valet, through 2 Oct. Each row names its source. Japan 10-year on 24 Sept 2026: **3.073%**. |
| 5 | Panel C: the last 12 auctions with the comparison to the prior six of each maturity; the next refunding date | 12 note and bond auctions (13 Aug–24 Sept), each against the average of its maturity's prior six. The weak labels (7-year 24 Sept, 5-year 23 Sept, 20-year 15 Sept) are all on the indirect share. The announced 3-, 10- and 30-year auctions of 6–8 Oct are listed, and the next quarterly refunding is **4 November**. |
| 6 | Panel E: each rule with its measured value and threshold | Five worsening and three reversal rules, each with its measured value, threshold and date. Present now: the term premium (+18.6 bp), Japan (3.085%), weak auctions (3 of 5) and Brent spot (+27.0%). |
| 7 | the home strip and the daily-log facts carry the new values with their dates | Home: U.S. 10-year, real, breakeven, term premium, Japan 10-year and Brent front-month, each with its one-day change and date. Facts: `global_rates` in the brief's payload (the 10-year with its daily change, the real yield, the breakeven, the term premium with its date, Japan, Brent, and any weak auction that day). |
| 8 | no panel states a forecast or a recommendation | Each panel heading says so where relevant. The referee's `rates:language` check scans for forecast and recommendation wording, alongside the standing edge/alpha scan. |

## Decisions, stated

1. **FRED is read through its public CSV download (no key),** both locally and in CI. The FRED API key stays where it is, unused by this module.
2. **Brent.** Spot (EIA, via FRED) is the primary series; the provider's front-month future is the same-day value, labelled as such. In September spot traded $11–25 above the front month, so the two are shown side by side, never spliced.
   - The Brent signals read spot ("official sources first") and show the front month's change beside it. Spot is up 27.0% over a month to 29 Sept; the front month is up 2.1% to 6 Oct.
   - The home strip's one-day change uses the front month.
3. **Lags.** Brent spot and yen per dollar (H.10, weekly) cannot meet a one-business-day lag. Their configured lag is six business days, and the referee judges them by it.
4. **The vintage.** Each day's file holds each series' last 30 observations with its source, URL, retrieval time and as-of date. It is written once (the ET date), and its sha256 is recorded. The full history lives in `data/source/rates_daily.parquet`, overlaid each night.
5. **UK 30-year.** It comes from the BoE nominal spot curve (the yield-curve spreadsheets), since the BoE database has no 30-year code. History is seeded once from the archive (2025 on) and kept from then on.
6. **Indirect share** is measured against the competitive accepted amount, as Treasury reports it. Reopenings map to their maturity (for example, 9-year 11-month to the 10-year); TIPS and floating-rate notes are excluded.
7. **Panel A's level** is the latest daily official value where one exists (France and Italy use the monthly average, marked). The latest OECD monthly average sits beside it, which is where the August figures appear.

## Files

- **Scripts:** `scripts/rates/fetch_global_rates.py` and `scripts/rates/build_global_rates.py` (nightly, after the bonds module).
- **Configuration:** `data/rates/global_rates_config.json` (series and thresholds).
- **Outputs:**
  - `data/rates/global_rates.json` (the panels, 270 KB);
  - `data/rates/global_rates_home.json` (the strip and the facts);
  - `data/rates/series_meta.json`;
  - `data/rates/auctions.json`;
  - `data/rates/vintages/`.
