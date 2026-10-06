"use strict";
// common.js — the common data loader and the navigation strip shared by every page (order 16-Sept-2026, 6.3).
// Loaded after charts.js/app.js (which define S and the render functions) and before pages.js / screen.js.
// Each page declares the files it renders (pages.js PAGES[page].loads); nothing else is fetched.

async function loadJSON(path){ try { const r = await fetch(path + "?" + Date.now()); if (r.ok) return await r.json(); } catch (e) {} return null; }
async function loadText(path){ try { const r = await fetch(path + "?" + Date.now()); if (r.ok) return await r.text(); } catch (e) {} return null; }
async function loadCSV(path){
  try { const r = await fetch(path + "?" + Date.now()); if (!r.ok) return null;
    return Papa.parse(await r.text(), {header:true, dynamicTyping:true, skipEmptyLines:true}).data;
  } catch(e){ return null; }
}
async function loadJSONL(path){
  const t = await loadText(path); if (t == null) return [];
  return t.split("\n").filter(l => l.trim()).map(l => { try { return JSON.parse(l); } catch (e) { return null; } }).filter(Boolean);
}

// state key → [served file, kind]. The page's load list names keys; the loader fills S[key].
const FILES = {
  config:["config.json","json"], tournament:["data/tournament.json","json"], holdings:["data/tier_holdings.json","json"],
  tickers:["data/ticker_indicators.json","json"], metrics:["data/backtest_metrics.json","json"], regime:["data/regime_indicators.json","json"],
  status:["data/status.json","json"], regimeDaily:["data/regime_daily.csv","csv"], indicatorSeries:["data/indicator_series.json","json"],
  signals:["data/ticker_signals.json","json"], regimeV4:["data/regime_v4_daily.csv","csv"], v4Cal:["data/v4_calibration.json","json"],
  c2:["data/c2_vintage_comparison.json","json"], c3:["data/c3_results.json","json"], backtestDD:["data/backtest_drawdown.json","json"],
  comparators:["data/comparators.json","json"], c3Paths:["data/c3_drawdown_paths.json","json"], provLedger:["data/provisional_ledger.json","json"],
  factors:["data/factor_exposure.json","json"], holdingsFile:["data/holdings.json","json"], book:["data/book.json","json"],
  actions:["data/actions.jsonl","jsonl"], intraday:["data/intraday.json","json"], volRegime:["data/vol_regime.json","json"],
  condScores:["data/regime_conditional_scores.json","json"], eventCal:["data/event_calendar.json","json"], regimePub:["data/regime_daily_published.csv","csv"],
  thesis:["data/thesis_daily.json","json"], thesisReg:["data/thesis_registry.json","json"], thesisClaims:["data/thesis_claims.json","json"],
  thesisBT:["data/thesis_backtest.json","json"], v4Attr:["data/v4_delta_attribution.json","json"], regProposals:["data/registry_proposals.json","json"],
  backtest:["data/backtest_equity_curves.csv","csv-rows"], universeMeta:["data/universe_meta.json","json"],
  screen:["data/screen/scores.json","json"], screenStatus:["data/screen/status.json","json"],
  visReg:["data/screen/visibility_registry.json","json"], reconciliation:["data/screen/reconciliation.json","json"],
  auditLast:["reports/audit_last.txt","text"],
  // fixed-income module (order 16-Sept-2026)
  bondsStates:["data/bonds/states.json","json"], bondsMetrics:["data/bonds/sleeve_metrics.json","json"],
  bondsUniverse:["data/bonds/sleeve_universe.json","json"],
  // options lens (order 26-Sept-2026)
  optionsLens:["data/options/lens.json","json"], optionsHedges:["data/options/hedges.json","json"],
  earningsRx:["data/options/earnings_reactions.json","json"],
  // the daily brief, news, goals, gains and ownership (order 30-Sept-2026)
  dailyLog:["data/daily_log.jsonl","jsonl"], briefFacts:["data/brief_facts.json","json"], briefRules:["data/brief_rules.json","json"],
  news:["data/news.json","json"], goals:["data/goals.json","json"], claimsReg:["data/claims_register.json","json"],
  gains:["data/realized_gains.json","json"], insiders:["data/ownership/insiders.json","json"], holders13f:["data/ownership/holders_13f.json","json"],
  // the tournament audit, the mistakes ledger, the twins and their logs, the reviews (audit order 30-Sept-2026)
  mistakes:["data/mistakes.jsonl","jsonl"], tournamentAudit:["data/tournament/audit.json","json"], twins:["data/tournament/twins.json","json"],
  trades:["data/tournament/trades.jsonl","jsonl"], spells:["data/tournament/spells.jsonl","jsonl"], reviews:["data/tournament/reviews.jsonl","jsonl"],
  c6Power:["data/tournament/c6_power_check.json","json"],
  // the entry-state indicator (order 2-Oct-2026)
  entryState:["data/entry_state.json","json"], globalRates:["data/rates/global_rates.json","json"], globalRatesHome:["data/rates/global_rates_home.json","json"], reviewNames:["data/review_names.json","json"], providerFlags:["data/provider_flags.json","json"],
};
async function loadFiles(keys, into){
  const target = into || S;
  await Promise.all(keys.map(async k => {
    const spec = FILES[k]; if (!spec) { console.warn("unknown file key", k); return; }
    const [path, kind] = spec;
    let v = null;
    if (kind === "json") v = await loadJSON(path);
    else if (kind === "csv") v = await loadCSV(path);
    else if (kind === "csv-rows") { const rows = await loadCSV(path); v = rows ? {rows} : null; }
    else if (kind === "jsonl") v = await loadJSONL(path);
    else if (kind === "text") v = await loadText(path);
    target[k] = v;
  }));
  return target;
}

// ── Sessions and freshness (moved from app.js 1-Oct-2026; shared by every page incl. the screen) ──
// SEPT AUDIT [5.2]: holiday-aware — mirrors scripts/trading_calendar.py
// NYSE_HOLIDAYS (2025-2027; keep in sync). Without this, the day after a
// holiday badged every current panel STALE (Labor Day 2026-09-07).
const NYSE_HOLIDAYS = new Set([
  "2025-01-01","2025-01-09","2025-01-20","2025-02-17","2025-04-18","2025-05-26",
  "2025-06-19","2025-07-04","2025-09-01","2025-11-27","2025-12-25",
  "2026-01-01","2026-01-19","2026-02-16","2026-04-03","2026-05-25",
  "2026-06-19","2026-07-03","2026-09-07","2026-11-26","2026-12-25",
  "2027-01-01","2027-01-18","2027-02-15","2027-03-26","2027-05-31",
  "2027-06-18","2027-07-05","2027-09-06","2027-11-25","2027-12-24"]);
// New York wall-clock parts (exact across daylight-saving changes; the old UTC−4 shortcut slipped an hour in winter)
function _etParts(d){
  const o = {};
  new Intl.DateTimeFormat("en-CA", {timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false}).formatToParts(d).forEach(x => { o[x.type] = x.value; });
  return {date: `${o.year}-${o.month}-${o.day}`, h: (+o.hour) % 24, m: +o.minute};
}
function _etDateISO(d){ return _etParts(d).date; }
function _isSession(iso){ const d = new Date(iso + "T12:00:00Z"); return ![0,6].includes(d.getUTCDay()) && !NYSE_HOLIDAYS.has(iso); }
function _dayBefore(iso){ const d = new Date(iso + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() - 1); return d.toISOString().slice(0,10); }
// The last session whose 16:00 ET close has happened, as of `now`.
function lastTradingSessionISO(now){
  const et = _etParts(now || new Date());
  let d = et.h < 16 ? _dayBefore(et.date) : et.date;
  while (!_isSession(d)) d = _dayBefore(d);
  return d;
}
// The session `n` sessions before `iso`.
function prevSessionISO(iso, n){
  let d = iso;
  for (let k = 0; k < (n || 0); k++){ d = _dayBefore(d); while (!_isSession(d)) d = _dayBefore(d); }
  return d;
}
// The last session whose close the nightly should have published by now. A close is processed
// overnight (the evening run, the late retry, the 04:00 ET morning run), so it falls due at
// 09:30 ET on the next day; until then the previous session is current and the new close is
// pending, not stale. 16:00 → 09:30 next day is 17.5 hours.
function dueSessionISO(now){ return lastTradingSessionISO(new Date((now || new Date()).getTime() - 17.5 * 3600e3)); }
// opt.lag: sessions a source legitimately trails (FRED series publish the next business day).
// opt.cadence: "static" (a result of record — never stale), "monthly" (35 days), "weekly" (9 days).
function freshnessOf(dateStr, opt){
  opt = opt || {};
  if (!dateStr) return "stale";
  const d = String(dateStr).slice(0,10);
  if (opt.cadence === "static") return "fresh";
  if (opt.cadence === "monthly" || opt.cadence === "weekly"){
    const days = (Date.now() - new Date(d + "T12:00:00Z").getTime()) / 864e5;
    return days > (opt.cadence === "monthly" ? 35 : 9) ? "stale" : "fresh";
  }
  const last = lastTradingSessionISO(), due = prevSessionISO(dueSessionISO(), opt.lag || 0);
  if (d >= prevSessionISO(last, opt.lag || 0)) return "fresh";
  return d >= due ? "pending" : "stale";
}
function isStaleAsOf(dateStr, opt){ return freshnessOf(dateStr, opt) === "stale"; }
// Small chip rendered next to panel titles: grey when current, grey with "close pending" between
// the close and the next morning's publish, amber STALE only once the publish was due and missed.
function asOfBadge(dateStr, opt){
  const d = dateStr ? String(dateStr).slice(0,10) : "—";
  const f = freshnessOf(dateStr, opt);
  if (f === "stale")
    return `<span class="asof asof-stale mono t1 w6 r1 c-warn ml2 x2" title="older than the last session the nightly should have published (${prevSessionISO(dueSessionISO(), (opt && opt.lag) || 0)})">STALE · as of ${d}</span>`;
  if (f === "pending")
    return `<span class="asof mono t1 w5 c-3 ml2" title="the ${lastTradingSessionISO()} close is processed overnight and due by 09:30 ET">as of ${d} · ${lastTradingSessionISO().slice(5)} close pending</span>`;
  return `<span class="asof mono t1 w5 c-3 ml2"${opt && opt.lag ? ` title="this source publishes ${opt.lag} session${opt.lag > 1 ? "s" : ""} after the close"` : ""}>as of ${d}</span>`;
}

// Order 5-Oct-2026, 2.5: every options panel names the chain vintage it was computed from. When that
// date is older than the last trading day (the last session whose 16:00 close has passed), the badge is
// amber, "options data from {date}" (the 30-Sept defect, a 25-Sept spot shown on 30 Sept, made visible).
function optionsAgeBadge(vintageDate){
  const d = vintageDate ? String(vintageDate).slice(0, 10) : null;
  const last = lastTradingSessionISO();
  if (!d) return `<span class="asof asof-stale mono t1 w6 r1 c-warn ml2 x2" title="no chain vintage on record">options data: no vintage</span>`;
  if (d < last) return `<span class="asof asof-stale mono t1 w6 r1 c-warn ml2 x2" title="the options figures come from the ${d} chain snapshot; the last trading day is ${last} (captured and missed days: data/options/vintages/_index.json)">options data from ${d}</span>`;
  return `<span class="asof mono t1 w5 c-3 ml2" title="computed from the ${d} chain snapshot (15:30–16:00 ET)">options as of ${d}</span>`;
}

// Phone pass (1-Oct-2026): a table wider than its box gets a one-line "swipe" hint under it, and
// the navigation row is scrolled so the current page's tab is visible.
function phoneTidy(){
  // Record tables (one row per item) stack into labelled cards on phones: each cell carries its
  // column header as data-label, which styles.css prints before the value.
  document.querySelectorAll("table.stack-m").forEach(t => {
    const head = t.querySelector("tr"); if (!head || !head.querySelector("th")) return;
    head.classList.add("stack-head");
    const labels = [...head.children].map(th => th.textContent.trim());
    [...t.querySelectorAll("tr")].slice(1).forEach(tr => {
      let i = 0;
      [...tr.children].forEach(td => {
        const span = +(td.getAttribute("colspan") || 1);
        if (span > 1) td.classList.add("stack-full"); else if (!td.dataset.label) td.dataset.label = labels[i] || "";
        // one value box per cell, so the label and the value sit side by side (flex) and the row
        // grows to the taller of the two; harmless on desktop (a single block inside the cell)
        if (span === 1 && !(td.firstElementChild && td.firstElementChild.classList.contains("cv")) && td.childNodes.length) {
          const cv = document.createElement("div"); cv.className = "cv";
          while (td.firstChild) cv.appendChild(td.firstChild);
          td.appendChild(cv);
        }
        i += span;
      });
    });
  });
  // On phones the table itself is the scroller (styles.css: .tier table{display:block;overflow-x:auto});
  // elsewhere its .tbl-scroll wrapper is. Either way the hint goes after the outermost box.
  document.querySelectorAll(".tbl-scroll, .tier table, .lbtable").forEach(el => {
    if (el.matches(".news-table, .events-table") || el.querySelector(".news-table, .events-table")) return;
    if ((el.textContent || "").trim().length < 4 || el.scrollWidth <= el.clientWidth + 4) return;
    const host = (el.tagName === "TABLE" && el.closest(".tbl-scroll")) || el;
    host.classList.add("scrolls");
    const nx = host.nextElementSibling;
    if (!(nx && nx.classList.contains("scroll-hint")))
      host.insertAdjacentHTML("afterend", '<div class="scroll-hint">⟷ swipe the table sideways for more columns</div>');
  });
  const nav = document.querySelector(".site-nav"), on = nav && nav.querySelector("a.on");
  if (nav && on && nav.scrollWidth > nav.clientWidth) nav.scrollLeft = Math.max(0, on.offsetLeft - nav.offsetLeft - 24);
}

// The navigation strip: seven pages and the guide; the current page marked.
const NAV = [["index.html","Home"],["book.html","Book"],["bonds.html","Bonds"],["screen.html","Screen"],["tournament.html","Tournament"],
             ["evidence.html","Evidence"],["register.html","Register"],["mistakes.html","Mistakes"],["system.html","System"],["guide.html","Guide"]];
function renderNav(page){
  return `<nav class="site-nav" aria-label="Pages">${NAV.map(([href, label]) => {
    const key = href.replace(".html", "").replace("index", "home");
    return `<a href="${href}" class="${key === page ? "on" : ""}"${key === page ? ' aria-current="page"' : ""}>${label}</a>`; }).join("")}</nav>`;
}
function pageHeader(title, sub){
  return `<div class="hd2"><div><span class="hd-dot"></span><h1 class="inl">${title}</h1><span class="mono t1 c-3 ml2">v3.0</span><div class="hd2-sub">${sub || ""}</div></div></div>`;
}
