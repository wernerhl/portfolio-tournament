// node --test scheduler/worker/test/
import { test } from "node:test";
import assert from "node:assert/strict";
import { due, dispatch, etParts, ROUTES } from "../src/index.js";

const at = iso => new Date(iso);
const wf = jobs => jobs.map(j => `${j.workflow} ${j.inputs.trigger}`);

test("15:40/15:46/15:52 ET dispatch the options snapshot under daylight time (UTC-4)", () => {
  assert.deepEqual(wf(due(at("2026-10-06T19:40:00Z"))), ["options_snapshot.yml external 15:40 ET"]);
  assert.deepEqual(wf(due(at("2026-10-06T19:46:00Z"))), ["options_snapshot.yml external 15:46 ET"]);
  assert.deepEqual(wf(due(at("2026-10-06T19:52:00Z"))), ["options_snapshot.yml external 15:52 ET"]);
});

test("the same Eastern times under standard time (UTC-5), and nothing an hour off", () => {
  assert.deepEqual(wf(due(at("2026-11-03T20:40:00Z"))), ["options_snapshot.yml external 15:40 ET"]);
  assert.deepEqual(due(at("2026-11-03T19:40:00Z")), []);          // 14:40 EST
  assert.deepEqual(due(at("2026-10-06T20:40:00Z")), []);          // 16:40 EDT
});

test("16:05 ET decides the day (the options snapshot check), in both seasons", () => {
  assert.deepEqual(wf(due(at("2026-10-06T20:05:00Z"))), ["options_snapshot_check.yml external 16:05 ET"]);
  assert.deepEqual(wf(due(at("2026-12-07T21:05:00Z"))), ["options_snapshot_check.yml external 16:05 ET"]);
});

test("weekends dispatch nothing", () => {
  assert.deepEqual(due(at("2026-10-10T19:40:00Z")), []);          // Saturday
  assert.deepEqual(due(at("2026-10-11T19:46:00Z")), []);          // Sunday
});

test("every route minute is reachable by the wrangler cron (minutes 0,5,30,40,46,52; UTC hours 13-21)", () => {
  const minutes = new Set([0, 5, 30, 40, 46, 52]);
  for (const r of ROUTES) for (const hm of r.et) {
    const [h, m] = hm.split(":").map(Number);
    assert.ok(minutes.has(m), `${r.workflow} ${hm}: minute ${m} not in the cron`);
    for (const off of [4, 5]) assert.ok(h + off >= 13 && h + off <= 21, `${r.workflow} ${hm}: UTC hour ${h + off} outside 13-21`);
  }
});

test("double-dispatch test date: two 15:40 options dispatches, only on that date", () => {
  const env = { DOUBLE_DISPATCH_ON: "2026-10-07" };
  assert.equal(due(at("2026-10-07T19:40:00Z"), ROUTES, env).length, 2);
  assert.equal(due(at("2026-10-07T19:46:00Z"), ROUTES, env).length, 1);
  assert.equal(due(at("2026-10-08T19:40:00Z"), ROUTES, env).length, 1);
});

test("etParts reads Eastern time", () => {
  assert.deepEqual(etParts(at("2026-10-06T19:40:00Z")), { date: "2026-10-06", hm: "15:40", weekday: "Tue" });
  assert.deepEqual(etParts(at("2026-10-07T04:05:00Z")), { date: "2026-10-07", hm: "00:05", weekday: "Wed" });
});

test("dispatch posts to the workflow's dispatches endpoint and retries only on 5xx", async () => {
  const calls = [];
  const mk = statuses => async (url, init) => { calls.push({ url, init }); const s = statuses.shift(); return { status: s, text: async () => "x" }; };
  const env = { GH_TOKEN: "test-token-not-real" };
  let r = await dispatch(env, "options_snapshot.yml", { trigger: "t" }, mk([204]), async () => {});
  assert.equal(r.ok, true);
  assert.equal(calls[0].url, "https://api.github.com/repos/wernerhl/portfolio-tournament/actions/workflows/options_snapshot.yml/dispatches");
  assert.deepEqual(JSON.parse(calls[0].init.body), { ref: "main", inputs: { trigger: "t" } });
  calls.length = 0;
  r = await dispatch(env, "options_snapshot.yml", { trigger: "t" }, mk([502, 503, 204]), async () => {});
  assert.equal(r.ok, true); assert.equal(r.attempt, 3);
  calls.length = 0;
  r = await dispatch(env, "options_snapshot.yml", { trigger: "t" }, mk([422]), async () => {});
  assert.equal(r.ok, false); assert.equal(calls.length, 1);
});

test("forced-miss test date: the 16:05 check carries force_miss_date, only on that date", () => {
  const env = { FORCE_MISS_ON: "2026-10-07" };
  assert.deepEqual(due(at("2026-10-07T20:05:00Z"), ROUTES, env)[0].inputs, { trigger: "external 16:05 ET", force_miss_date: "2026-10-07" });
  assert.deepEqual(due(at("2026-10-08T20:05:00Z"), ROUTES, env)[0].inputs, { trigger: "external 16:05 ET" });
  assert.deepEqual(due(at("2026-10-07T19:40:00Z"), ROUTES, env)[0].inputs, { trigger: "external 15:40 ET" });
});
