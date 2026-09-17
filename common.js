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

// The navigation strip: seven pages and the guide; the current page marked.
const NAV = [["index.html","Home"],["book.html","Book"],["bonds.html","Bonds"],["screen.html","Screen"],["tournament.html","Tournament"],
             ["evidence.html","Evidence"],["register.html","Register"],["system.html","System"],["guide.html","Guide"]];
function renderNav(page){
  return `<nav class="site-nav" aria-label="Pages">${NAV.map(([href, label]) => {
    const key = href.replace(".html", "").replace("index", "home");
    return `<a href="${href}" class="${key === page ? "on" : ""}"${key === page ? ' aria-current="page"' : ""}>${label}</a>`; }).join("")}</nav>`;
}
function pageHeader(title, sub){
  return `<div class="hd2"><div><span class="hd-dot"></span><h1 class="inl">${title}</h1><span class="mono t1 c-3 ml2">v3.0</span><div class="hd2-sub">${sub || ""}</div></div></div>`;
}
