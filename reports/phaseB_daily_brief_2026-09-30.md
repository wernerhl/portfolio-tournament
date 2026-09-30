# Phase B report — The daily brief, the news, the events board

Execution Order of 30 September 2026, items B1–B5. Executed 30 September 2026.

| commit | item |
|---|---|
| 61d06d2 | [B1] The colour by pre-registered rule, never by the model |
| 1203d3b | [B2] The narrative, constrained; template on rejection |
| 95633ae | [B3] The cumulative log, seeded with the 29-Sept YELLOW entry; referee checks |
| (see the front-end commit) | [B3] the strip on the home page and the full history on the system page; [B5] the events board |
| (see [B4]) | [B4] News, primary sources first |

## B1 — The colour

`data/brief_rules.json` freezes the order's thirteen rules with their parameters (frozen 2026-09-30; the log records the rules file's hash each entry, and the referee flags a changed rules file until it is re-registered). Definitions the order left to the implementation, stated in the file:

- **Chandelier level**: the 22-session high minus 3 × ATR(22) on the provider's OHLC bars (close-to-close range when OHLC is unavailable, flagged). The repository had no Chandelier level of its own; the rulebook's trailing level (peak × (1 − bracket)) is recorded beside it and is not the Chandelier level. On 29 September every held name closed above its Chandelier level, so R6 does not fire under either reading of "closes below … on the same day" (state or fresh break); the state reading is registered.
- **Book change**: Σ shares × Δclose over the prior session's NAV, on the current holdings with cash unchanged.
- **Regime streak**: the continuous revised series `regime_daily.csv`; the published vintage's R beside it.
- **Flags**: intraday.json when it is reconciled to the session, else recomputed by its own rules from the canonical closes.
- **Next events**: the next three calendar events of impact high or medium (held-name earnings only among earnings).

`scripts/daily_brief.py` builds the facts payload from served data only, evaluates the rules and stores every rule that fired with its evidence. Tests (`tests/test_daily_brief.py`, 14 passed): each of the thirteen rules fires on a constructed payload and clears otherwise; R6 needs both levels; RED beats YELLOW; the 29-September construction reads YELLOW.

## B2 — The narrative

The model (claude-sonnet-5-5 by configuration; the key read from `ANTHROPIC_API_KEY`, never printed) writes one sentence of at most 40 words from the payload. The validator rejects: any number absent from the payload at the decimals the text shows (index names and tenors such as "10-year" carry no figure; strings in the payload supply no figures — only numeric fields count); a forecast verb; a security not in the payload (checked against the union universe, allowed when its symbol appears anywhere in the payload); more than 40 words; a directive; the prohibited vocabulary. On rejection the template sentence is used and the rejection is logged.

Forced test (acceptance §8.4), verbatim:

```
$ daily_brief.py --session 2026-09-29 --validate-text "2026-09-29: S&P 500 -0.17%, VIX 16.04, SKEW 144.6; regime LOW RISK; the book gained 2.75% on the day."
[daily_brief] validator: REJECTED — number not in the payload: 2.75
[daily_brief] template replacement: 2026-09-29: S&P 500 -0.17%, VIX 16.04 (-0.2%), SKEW 144.6; regime LOW RISK (R 0.2796); 10-year 5.24%; book +0.13% (GEV +1.34%); next: GDP 2026-09-30.
```

The same path is exercised in the tests with a model double returning an unpayloaded number: the entry's text is the template and the rejection carries the model's sentence and reason. Without a key (this environment and, until the secret is added, the nightly) the template is used and the entry says so.

## B3 — The log

`data/daily_log.jsonl`, append-only. Entry fields: entry_id, session, logged_at, color, rules_fired (id, text, evidence), rules_evaluated, rules_sha256, text, words, text_source (model | template), model, rejections, payload_sha256, supersedes, correction_reason, entry_sha256. A correction is a new entry that references the old (`--correct ENTRY_ID --reason`); the referee raises CRITICAL when any entry's content no longer matches its recorded hash. `data/brief_facts.json` carries the payload behind the latest sentence.

The seed entry for the 29-September session, computed from the served data:

```
2026-09-29: YELLOW · rules ['Y1', 'Y2', 'Y3', 'Y4', 'Y6'] · text from the template (23 words)
  Y1 SKEW 145 > 140 (canonical close (2026-09-29)) and VIX 16.0 < 17 — tail priced, spot fear absent — market complacent
  Y2 PCE 2026-09-30
  Y3 regime index up 5 sessions in a row
  Y4 10-year 5.24% (2026-09-28)
  Y6 GOOG +0.1%
  2026-09-29: S&P 500 -0.17%, VIX 16.04 (-0.2%), SKEW 144.6; regime LOW RISK (R 0.2796); 10-year 5.24%; book +0.13% (GEV +1.34%); next: GDP 2026-09-30.
```

The order's three reasons (complacency on with SKEW 144.6 and VIX 16.0; PCE within two sessions; 10-year above 5 percent) all fire; two more do by the same rules — the regime index rose five sessions in a row (09-23 through 09-29) and GOOG closed 0.1 percent from its 200-day average. YELLOW either way. No red rule fires (S&P −0.17%, VIX −0.2%, book +0.13% on the current holdings, credit normal, no name below both levels).

Displayed on the home page as a vertical strip, newest first (each entry a coloured bar with its sentence and the rules that fired), with the full history on the system page. The page states that the colour describes the state and is not a forecast.

## B4 — News

See the [B4] commit and `data/news_sources.json`. Tier 1 (primary): the Federal Reserve's press-release and speeches feeds; the BEA, Census and DOL feeds; BLS release-day items constructed from the calendar (BLS returns 403 to automated clients); SEC EDGAR filings for the held names and the top-40 board, only when the SEC's required declared contact is configured (`SEC_USER_AGENT`, a secret; skipped and recorded otherwise); company investor-relations feeds (NVIDIA press releases, GE Vernova, Broadcom; Alphabet and BitMine publish no feed). Tier 2 (secondary, labeled): the provider's per-ticker headlines. Stored per item: headline, source, URL, timestamp, tickers, topics, a system-written one-line summary — never the feed's description or a body. Items carrying the prohibited vocabulary or a directive are withheld and counted. The registry cites the newsroom's founding principle (La Linterna, February 2026: every story from primary sources; traditional media a reference layer, headlines only, never rewritten).

First live run (30 September, 04:27 ET): 37 items stored (16 Tier 1, 21 Tier 2), 20 inside the 24-hour window; one withheld by the directive rule. The home panel shows the last 24 hours, Tier 1 first; each held name's card shows its last five items. The 2-hourly intraday workflow refreshes the file (EDGAR only on the nightly). Tests: 18 passed.

## B5 — The events board

Home page, below the log: the next 45 days grouped by week, each event with its impact level; held-name earnings with the options lens's implied move in percent and in dollars on the position (board-name earnings collapsed to one line per week); the A2 clusters highlighted with their macro and earnings names. The first rows today: GDP and PCE at 08:30 ET.
