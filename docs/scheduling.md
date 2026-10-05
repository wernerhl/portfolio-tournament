# Scheduling: what triggers each workflow, and how to keep it working

Execution Order: Make the Daily Options Snapshot Reliable (5 October 2026), item 2.1.

## Why there is an external scheduler

GitHub delivers this repository's scheduled (`cron`) runs minutes to hours late, and some never arrive. On 28 and 29 September and on 5 October no options-snapshot cron arrived before the 15:30–16:00 ET window, so no option-chain vintage was written for those days. A workflow whose purpose is a time window cannot depend on GitHub's cron.

The primary trigger is a **Cloudflare Worker** (`scheduler/worker/`). Its cron trigger fires within a minute of schedule, and it calls GitHub's `workflow_dispatch` endpoint for the workflow that is due. The GitHub crons that remain are backups.

## The schedule (Eastern time, weekdays)

| ET | workflow | purpose |
|---|---|---|
| 15:40, 15:46, 15:52 | `options_snapshot.yml` | the daily option-chain vintage; the first run to start writes it, the others exit with "already written" |
| 16:05 | `options_snapshot_check.yml` | decides the day: `data/options/vintages/_index.json` records it captured or missing (with the reason); a miss opens a GitHub issue |
| 10:00 | `market_open.yml` | the market-open snapshot (live VIX/SPX/SKEW, shock and complacency, live card values) |
| 10:10, 12:10, 14:10, 16:10 | `intraday_analytics.yml` | the book and bond panels recomputed on the live tape |
| 09:50, then every 30 min at :20 and :50 until 15:50 | `intraday.yml` | the intraday refresh (shock watch) |

The last three deploy GitHub Pages through one shared concurrency group. That group keeps a single pending deploy and cancels the rest, so the routes are staggered: no two deploying dispatches fall within 10 minutes of each other. A test enforces it.

The routes live in `scheduler/worker/src/index.js` (`ROUTES`) and are written in Eastern time. The Worker converts its scheduled UTC time to America/New_York, so nothing changes at the daylight-saving switches. Its single cron trigger (`wrangler.toml`) is `0,5,10,20,40,46,50,52 13-21 * * mon-fri` UTC. That wakes it on every minute a route can fall on. A new route must use one of those minutes, and a test in `scheduler/worker/test/` fails if it does not. Market holidays are not in the Worker: the workflows exit on a closed market.

**GitHub backup crons:** `market_open.yml`, `intraday.yml` and `intraday_analytics.yml` keep their crons as a backup. A gate job (`scripts/ops/backup_cron_gate.py`) lets a cron run proceed only when no successful run already covers its slot: since 09:30 ET for the market open, within 25 minutes for the intraday refresh, within 100 minutes for the analytics. Before the Worker exists, nothing else has run, and the crons behave as before. `options_snapshot_check.yml` has `30 21 * * 1-5` (17:30 EDT / 16:30 EST); a late check still records and reports the day, and the nightly rebuilds the same index. `options_snapshot.yml` keeps `0 13 * * 1-5` and `0 17 * * 1-5` (UTC). A backup run that lands before the window sleeps until 15:44 ET; one that lands after it exits. The 13:00 UTC cron only helps when GitHub delivers it at least about 1.2 hours late, because a job may sleep at most 5.6 hours.

## Setting it up (the operator; about 15 minutes)

The agent wrote the Worker and these instructions. The operator creates the token and the Cloudflare account; the agent never handles either.

### 1. The GitHub token

1. GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token.
2. Name: `portfolio-tournament-scheduler`. Expiration: 90 days (put the expiry date in the calendar; see Rotation).
3. Resource owner: `wernerhl`. Repository access: **Only select repositories** → `portfolio-tournament`.
4. Repository permissions: **Actions → Read and write**. Leave everything else at No access; Metadata (read-only) is added automatically and is required.
5. Generate, and copy the token straight into step 2.4 below. Do not save it in a file, a note or this repository.

### 2. The Cloudflare Worker

1. Create a free Cloudflare account (dash.cloudflare.com).
2. On the Mac: `npm install -g wrangler`, then `wrangler login` (opens the browser).
3. `cd scheduler/worker && wrangler deploy`. Wrangler prints the Worker name and the cron trigger.
4. `wrangler secret put GH_TOKEN` and paste the token at the prompt. The secret is stored encrypted in Cloudflare; it is not in `wrangler.toml` and not in git.
5. In the Cloudflare dashboard → Workers → `portfolio-tournament-scheduler` → Settings → Triggers, check that the cron reads `0,5,10,20,40,46,50,52 13-21 * * mon-fri`.

### 3. Check that it works

- After 15:52 ET on the next trading day: `gh run list --repo wernerhl/portfolio-tournament --workflow options_snapshot.yml --event workflow_dispatch --limit 5`. Expect three runs titled `Options snapshot · external 15:40 ET`, `… 15:46 ET` and `… 15:52 ET`. The first writes the vintage; the other two end with the notice "already written".
- Live log: `cd scheduler/worker && wrangler tail` while a route is due. Each dispatch prints one JSON line with `"ok": true, "status": 204`.
- A `"status": 401` or `403` means the token is wrong, expired, or lacks Actions write. A `404` means the token cannot see the repository. A `422` means the workflow does not declare the `trigger` input on `main`.

### Acceptance test 2 (the double dispatch)

Set `DOUBLE_DISPATCH_ON = "YYYY-MM-DD"` (a coming trading day) in `wrangler.toml` and run `wrangler deploy`. At 15:40 ET that day the Worker dispatches the options snapshot twice. Expect one vintage, one push, and one run ending "already written". Then set it back to `""` and deploy again.

### Acceptance test 5 (a forced miss)

Set `FORCE_MISS_ON = "YYYY-MM-DD"` (a coming trading day) in `wrangler.toml` and run `wrangler deploy`. At 16:05 ET that day the check opens an issue titled `[TEST] Options snapshot missed: YYYY-MM-DD`, labelled `options-snapshot-missed`; the index is not changed. The next trading day's vintage closes it. Then set the variable back to `""` and deploy again. Without the Worker the same test is a manual dispatch: `gh workflow run options_snapshot_check.yml -f force_miss_date=YYYY-MM-DD`.

## Missed snapshots

A trading day with no vintage at 16:05 ET is recorded as missing in `data/options/vintages/_index.json`, with the reason (`no_run_in_window`, `runner_failure`, `provider_error` or `push_conflict`), and opens one GitHub issue labelled `options-snapshot-missed`. The issue closes itself when the next day's vintage is written. The day is never filled with after-hours data, and the IV rank uses captured days only.

## Rotation (every 90 days, or at once if the token may have leaked)

1. Create a new fine-grained token exactly as in step 1.
2. `cd scheduler/worker && wrangler secret put GH_TOKEN` and paste the new token. This replaces the old secret; no redeploy is needed.
3. GitHub → Settings → Developer settings → Fine-grained tokens → delete the old token.
4. Check the next dispatch (`wrangler tail` or `gh run list … --event workflow_dispatch`).

If the token expires unnoticed, the Worker's dispatches fail with 401. The GitHub backup crons still run, the missed-snapshot issue opens (item 2.4), and the referee reports the captured share.

## Measuring the delays

`python scripts/ops/schedule_delays.py --start YYYY-MM-DD --end YYYY-MM-DDTHH:MM` reports, per scheduled workflow, how late GitHub delivered each cron and how many never ran (reports/schedule_delays_2026-10-05.md). Since 5 October every scheduled workflow's run title (`run-name`) carries the cron that fired it, so later measurements are exact.

## Fallback if Cloudflare Workers is not available: cron-job.org

1. Create an account at cron-job.org. Create one job per route time: 15:40, 15:46 and 15:52.
2. For each job:
   - URL: `https://api.github.com/repos/wernerhl/portfolio-tournament/actions/workflows/options_snapshot.yml/dispatches`
   - Method: POST.
   - Headers: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, `Content-Type: application/json`.
   - Body: `{"ref":"main","inputs":{"trigger":"cron-job.org 15:40 ET"}}`, with the time adjusted per job.
   - Schedule: Monday–Friday at the route time, **time zone America/New_York**.
   - Success is HTTP 204.
3. The token sits in cron-job.org's job settings. Rotate it there the same way (replace the header in each job, then delete the old token).

## What not to do

- Do not commit the token, put it in `wrangler.toml`, or paste it into an issue or commit message.
- Do not widen the token's permissions or repository access. It needs Actions write on this one repository and nothing else.
- Do not add a `concurrency` block to `options_snapshot.yml`. GitHub keeps one pending run per group and cancels the rest, which produced the 2-October cancellation emails. One writer per day is enforced by the guard in `scripts/options/snapshot_chains.py` (item 2.2).
