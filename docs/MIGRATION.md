# Moving to MarketMonitoring: the cutover

From three repositories (`portfolio-tournament`, `portfolio-screener`, `crypto-monitor`) to one
(`MarketMonitoring`), one site and one issue tracker. Built and rehearsed on 2026-11-05; the steps
below switch production over. Nothing is deleted at any point: the old repositories are archived,
which is free and reversible, and keep their full history.

Who does what: **[owner]** needs your GitHub or Cloudflare account; **[Claude]** can be done from
a Claude Code session with push access to the repositories.

## 1. Create the repository — [owner], 2 minutes
1. https://github.com/new → owner `wernerhl`, name `MarketMonitoring`, **Public** (GitHub Pages on a
   free plan needs a public repository), **no** README, .gitignore or licence (it must be empty).
2. Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Settings → Actions → General → Workflow permissions: **Read and write**.

## 2. Push the code — [Claude]
Rebase the restructure onto the latest `portfolio-tournament/main` (its bots keep committing data
until step 5) and push `main` with its full history (~570 MB).

## 3. Secrets — [owner], Settings → Secrets and variables → Actions
Copy the values from the old repositories (GitHub never shows a saved secret; use the original
source, e.g. the provider's dashboard):

| Secret | Used by | Was in |
|---|---|---|
| `FRED_API_KEY` | nightly, vintage_rebuild, crypto-daily, crypto-manual | both |
| `SEC_USER_AGENT` | nightly, intraday_analytics, options_snapshot | portfolio-tournament |
| `ANTHROPIC_API_KEY` | nightly (the brief's sentence; template when unset) | portfolio-tournament |
| `CLAUDE_CODE_OAUTH_TOKEN` | nightly (preferred over the API key) | portfolio-tournament |
| `COINGECKO_DEMO_KEY` | every crypto job | crypto-monitor |
| `BEACONCHAIN_API_KEY`, `COINGLASS_API_KEY`, `GLASSNODE_API_KEY`, `TALLY_API_KEY` | crypto-daily (optional sources) | crypto-monitor |

## 4. External schedulers and the Mac — [owner]
- **Cloudflare Worker** (`scheduler/worker`, docs/scheduling.md): create a fine-grained token for
  `wernerhl/MarketMonitoring` only (Actions: read and write), then
  `cd scheduler/worker && wrangler deploy && wrangler secret put GH_TOKEN`. Its code already names
  the new repository; until this is done the GitHub backup crons run the portfolio's intraday jobs.
- **Mac collector** (only if you restart it; it has been silent since 2026-09-17): clone
  MarketMonitoring outside `~/Documents`, `cd MarketMonitoring/crypto && uv sync && bash
  scripts/install_collector_macos.sh` — it also unloads the old crypto-monitor agents.

## 5. Switch over — [Claude], after 1–3
1. Disable the scheduled workflows of `portfolio-tournament` and `crypto-monitor` (reversible:
   Actions → workflow → Enable), so neither old repository keeps writing data or opening issues.
2. Rebase once more onto the final `portfolio-tournament/main` and push.
3. Seed the crypto data: `bash crypto/scripts/seed_state_from_crypto_monitor.sh <crypto-monitor clone>`
   (the final crypto-monitor data → the first `crypto-state` snapshot).
4. Run by hand and check each: `crypto-daily`, `crypto-hourly`, `crypto-weekly` (rebuilds the
   weekly tables and moves old raw files into the `crypto-raw-*` releases), `nightly`, `crypto-ci`.
   The site: https://wernerhl.github.io/MarketMonitoring/ and `/crypto/`.

## 6. Retire the old repositories — [owner approves, Claude prepares]
1. Point the old sites to the new one: a redirect `index.html` in each old repository's Pages
   (as portfolio-screener did on 2026-09-16).
2. After a week of clean runs here: Settings → Archive this repository, for all three. Archived
   repositories are read-only and run nothing; their history, issues and the crypto raw archive
   (`crypto-monitor`'s `data-archive` branch, up to 2026-09) stay available.
3. Deleting them is possible later, but is permanent: it removes `crypto-monitor`'s 6.8 GB of
   history and its pre-November raw archive, and the old addresses stop redirecting.

## What changed for the crypto monitor
- Generated data lives on `crypto-state` (one snapshot, replaced each run), not on `main`; the raw
  archive is in releases, not a git branch. Work locally with `bash crypto/scripts/state.sh restore`.
- Workflows are `crypto-*.yml` at the repository root and run in `crypto/`. The hourly job runs at
  minute 35 (was 7), clear of the portfolio's Pages deploys.
- Issues carry the label `crypto-alert` and "[crypto alert]" titles; open issues in crypto-monitor
  are not moved (they close themselves when the condition clears, or with the archive).
