// portfolio-tournament scheduler — a Cloudflare Worker that dispatches GitHub workflows at fixed
// Eastern times (Execution Order: Make the Daily Options Snapshot Reliable, 5 October 2026, item 2.1).
//
// GitHub delivers this repository's scheduled runs minutes to hours late, or not at all; a workflow
// whose purpose is a time window cannot depend on them. Cloudflare cron triggers fire within a
// minute of schedule. One cron trigger (UTC, see wrangler.toml) wakes the Worker on the minutes
// that matter; the routing below converts the scheduled time to America/New_York, so the table is
// written in Eastern time and survives the daylight-saving changes without edits.
//
// Secret: GH_TOKEN, a fine-grained personal access token for wernerhl/portfolio-tournament only,
// with Actions read-and-write and nothing else (docs/scheduling.md). Never committed.
// Optional var: DOUBLE_DISPATCH_ON = "YYYY-MM-DD" dispatches the 15:40 options run twice on that
// date (acceptance test 2: one vintage, one push, one "already written" exit).

export const REPO = "wernerhl/portfolio-tournament";

// Eastern time → workflow file. Weekdays only; the workflows themselves exit on market holidays.
export const ROUTES = [
  // 2.1: the options snapshot inside 15:30–16:00 ET; the first run to start writes, the rest exit
  { workflow: "options_snapshot.yml", et: ["15:40", "15:46", "15:52"] },
];

const pad = n => String(n).padStart(2, "0");

export function etParts(when) {
  const f = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", hour12: false, weekday: "short",
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
  const p = Object.fromEntries(f.formatToParts(when).map(x => [x.type, x.value]));
  const hour = p.hour === "24" ? "00" : p.hour;
  return { date: `${p.year}-${p.month}-${p.day}`, hm: `${pad(hour)}:${pad(p.minute)}`, weekday: p.weekday };
}

// The dispatches due at a scheduled instant.
export function due(when, routes = ROUTES, env = {}) {
  const { date, hm, weekday } = etParts(when);
  if (weekday === "Sat" || weekday === "Sun") return [];
  const jobs = routes.filter(r => r.et.includes(hm)).map(r => ({ workflow: r.workflow, inputs: { trigger: `external ${hm} ET` } }));
  if (env.DOUBLE_DISPATCH_ON && env.DOUBLE_DISPATCH_ON === date && hm === "15:40") {
    for (const j of jobs.filter(j => j.workflow === "options_snapshot.yml")) {
      jobs.push({ workflow: j.workflow, inputs: { trigger: `external ${hm} ET (double-dispatch test)` } });
    }
  }
  return jobs;
}

export async function dispatch(env, workflow, inputs, fetchImpl = fetch, sleep = ms => new Promise(r => setTimeout(r, ms))) {
  const url = `https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`;
  let last = null;
  for (let attempt = 1; attempt <= 3; attempt++) {
    const res = await fetchImpl(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "portfolio-tournament-scheduler",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs }),
    });
    if (res.status === 204) return { ok: true, status: 204, attempt };
    last = { ok: false, status: res.status, attempt, body: (await res.text()).slice(0, 300) };
    if (res.status < 500 && res.status !== 429) return last;      // a 4xx will not improve on retry
    await sleep(4000 * attempt);                                   // GitHub 5xx / rate limit: back off
  }
  return last;
}

export default {
  async scheduled(controller, env, ctx) {
    const when = new Date(controller.scheduledTime);
    const jobs = due(when, ROUTES, env);
    for (const j of jobs) {
      const r = await dispatch(env, j.workflow, j.inputs);
      console.log(JSON.stringify({ scheduled: when.toISOString(), et: etParts(when), workflow: j.workflow, inputs: j.inputs, ...r }));
    }
  },
};
