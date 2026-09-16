"use strict";
// pages.js — page compositions for the multi-page site (order 16-Sept-2026, 6.3). Every panel is an
// existing render function of app.js; each page loads only the files it renders (common.js FILES).

function d3(title, html){
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 820px)").matches;
  return html ? `<details class="t3-panel"${isMobile ? "" : " open"}><summary>${title}</summary>${html}</details>` : "";
}
function liveRow(){ const h = S.tournament && S.tournament.history; return h && h.length ? h[h.length - 1] : null; }
function updatedStr(){
  return S.tournament && S.tournament.last_updated
    ? new Date(S.tournament.last_updated).toLocaleString("en-US",{timeZone:"America/New_York",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"}) : "—";
}

// ── 6.3: small panels that existed only as text before the split ─────────────────────────
function renderVintageCard(){   // C2 vintage comparison (evidence page)
  const c = S.c2; if (!c || !c.drawdown_reduction) return "";
  const rows = Object.entries(c.drawdown_reduction).map(([tid, v]) => { const t = tierSpec(tid) || {}; if (!v || !v.rev || !v.pit) return "";
    return `<tr><td class="${cc(t.color)}">${t.short || tid}</td><td class="num">${(v.rev.max_dd * 100).toFixed(1)}%</td><td class="num">${(v.pit.max_dd * 100).toFixed(1)}%</td><td class="num">${(v.rev.dd_reduction_vs_spy * 100).toFixed(1)}%</td><td class="num c-1 w6">${(v.pit.dd_reduction_vs_spy * 100).toFixed(1)}%</td></tr>`; }).join("");
  return `<div class="rcc-card"><h3>VINTAGE COMPARISON (C2) · <span class="c-3 w5">the regime index rebuilt on ALFRED point-in-time inputs against the revised inputs, same engine</span>${asOfBadge(c.as_of)}</h3>
    <div class="tbl-scroll"><table class="th-table"><tr><th>TIER</th><th>MAX DD · REVISED</th><th>MAX DD · POINT-IN-TIME</th><th>DD REDUCTION vs SPY · REVISED</th><th>DD REDUCTION · POINT-IN-TIME</th></tr>${rows}</table></div>
    <div class="chart-meta">${c.summary || c.note || "revisions are the dominant channel; release lag accounts for almost none of the difference"} · report: reports/retirement_test_C2_input_vintages.md</div></div>`;
}
function renderProvisionalLedger(){   // register page
  const L = S.provLedger; if (!L || !L.entries) return "";
  const es = Object.entries(L.entries).sort((a, b) => String(a[1].first_proposed || "").localeCompare(String(b[1].first_proposed || "")));
  if (!es.length) return `<div class="rcc-card"><h3>PROVISIONAL LEDGER</h3><div class="mono t1 c-3">empty</div></div>`;
  const rows = es.map(([tk, e]) => `<tr><td class="mono t2 c-1 w6">${tk}</td><td class="c-2">${Object.entries(e.proposed || {}).map(([k, w]) => `${thesisLabel(k)} ${(+w).toFixed(2)}`).join(", ")}</td><td class="${e.status === "provisional" ? "c-warn" : e.status === "approved" ? "c-pos" : "c-3"}">${e.status}</td><td class="c-3 t1">${e.first_proposed || ""} → ${e.expires || ""}${e.resolved ? " · resolved " + e.resolved : ""}</td><td class="c-3 t1">${e.source || ""}</td><td class="c-3 t1">${(e.rationale || "").slice(0, 90)}</td></tr>`).join("");
  return `<div class="rcc-card"><h3>PROVISIONAL LEDGER · <span class="c-3 w5">agent-proposed name mappings: applied immediately, tagged, expiring after ${(L.policy && L.policy.expiry_days) || 30} days unless approved</span>${asOfBadge(L.as_of)}</h3>
    <div class="tbl-scroll"><table class="th-table"><tr><th>NAME</th><th>PROPOSED MAPPING</th><th>STATUS</th><th>CLOCK</th><th>SOURCE</th><th>RATIONALE</th></tr>${rows}</table></div>
    <div class="chart-meta">${(L.policy && L.policy.rule) || ""}</div></div>`;
}
function renderProposals(){   // register page
  const P = S.regProposals; if (!P || !P.proposals) return "";
  const rows = P.proposals.map(p => p.ticker
    ? `<tr><td class="mono t2 c-1 w6">${p.ticker}</td><td class="c-2">${Object.entries(p.proposed || {}).map(([k, w]) => `${thesisLabel(k)} ${(+w).toFixed(2)}`).join(", ") || "—"}</td><td class="${p.status === "provisional" ? "c-warn" : "c-3"}">${p.status || ""}</td><td class="c-3 t1">${p.source || ""}</td><td class="c-3 t1">${p.rationale || ""}</td></tr>`
    : `<tr><td class="mono t2 c-1 w6">${p.thesis_id || "—"}</td><td class="c-2">${p.type || ""} · ${p.label || ""}${p.proposed_members ? " · " + Object.keys(p.proposed_members).join(", ") : ""}</td><td class="c-3">${p.status || ""}</td><td class="c-3 t1">structural</td><td class="c-3 t1">${p.rationale || ""}${p.provisional_note ? " · " + p.provisional_note : ""}</td></tr>`).join("");
  return `<div class="rcc-card"><h3>REGISTRY PROPOSALS · <span class="c-3 w5">regenerated nightly · the agent never auto-merges; Werner approves with a version bump</span>${asOfBadge(P.as_of)}</h3>
    <div class="tbl-scroll"><table class="th-table"><tr><th>NAME / THESIS</th><th>PROPOSED</th><th>STATUS</th><th>SOURCE</th><th>RATIONALE</th></tr>${rows}</table></div>
    <div class="chart-meta">${P.note || ""} · registry v${P.registry_version_current}${P.registry_frozen ? " frozen" : " pending"} · holdings changed today: ${(P.holdings_changed_today || []).join(", ") || "none"}</div></div>`;
}
function renderSystemPanel(){   // system page: pipeline status · audit · no-publish count
  const st = S.status || {}; const a = st.audit || {};
  const pub = Array.isArray(S.regimePub) ? S.regimePub : [];
  const np = pub.filter(r => r && r.date && (r.R_t_published == null || r.R_t_published === "" || isNaN(+r.R_t_published)));
  const cell = (k, v, s, cls) => `<div class="so-cell"><div class="k">${k}</div><div class="v ${cls || "c-1"}">${v}</div><div class="s">${s || ""}</div></div>`;
  const audit = S.auditLast ? `<details class="mt2"><summary class="mono t1 w5 c-3 ptr ls05">last referee output (reports/audit_last.txt)</summary><pre class="audit-pre mono t1 c-2">${String(S.auditLast).replace(/</g, "&lt;")}</pre></details>` : "";
  return `<div class="rcc-card"><h3>PIPELINE AND REFEREE · <span class="c-3 w5">status.json · the nightly's last attempt and success, the referee's last sweep, the published vintage's no-publish sessions</span>${asOfBadge(st.session_date)}</h3>
    <div class="so-strip">
      ${cell("LAST NIGHTLY", st.failure_reason ? "rejected" : "published", `attempt ${String(st.last_attempt || "").slice(0, 16)} · last success ${String(st.last_success || "").slice(0, 16)}${st.failure_reason ? " · " + st.failure_reason : ""}${st.forced_publish_reason ? " · forced: " + st.forced_publish_reason : ""}`, st.failure_reason ? "c-neg" : "c-pos")}
      ${cell("REFEREE", `${a.n_findings != null ? a.n_findings + " findings" : "—"} · ${(a.critical || []).length} CRITICAL`, `${(a.high || []).length} HIGH · scope ${a.scope || "—"} · ${String(a.ran_at || "").slice(0, 16)}${(a.critical || []).length ? " · " + a.critical.join(", ") : ""}`, (a.critical || []).length ? "c-neg" : "c-pos")}
      ${cell("NO-PUBLISH SESSIONS", `${np.length} of ${pub.length}`, np.length ? np.map(r => String(r.date).slice(0, 10)).join(", ") + " (reasons in regime_daily_published.csv)" : "every session since inception published", np.length ? "c-warn" : "c-pos")}
      ${cell("HOLDINGS", S.holdingsFile && S.holdingsFile.as_of ? S.holdingsFile.as_of : "—", S.holdingsFile ? `${S.holdingsFile.source || ""}${S.holdingsFile.input_sha256 ? " · export " + String(S.holdingsFile.input_sha256).slice(0, 12) : ""}` : "holdings.json not loaded")}
    </div>
    ${(a.high || []).length ? `<div class="mono t1 c-3 mt2">HIGH: ${a.high.join(" · ")}</div>` : ""}
    ${audit}
  </div>`;
}
function renderPositionsList(){   // book page: the held names' position readings (1.7)
  const b = S.book; if (!b || !S.signals || !S.signals.signals) return "";
  const names = (b.positions || []).filter(p => p.value != null).sort((x, y) => y.value - x.value).map(p => p.ticker);
  const boxes = names.map(tk => { const sig = S.signals.signals[tk]; if (!sig) return `<div class="mono t1 c-3">${tk}: no signal record yet (written by the nightly)</div>`;
    return `<div class="pos-box"><div class="mono t2 w7 c-1 mb1">${tk}</div>${renderTwoScore(tk)}${renderSignalBox(tk)}</div>`; }).join("");
  return `<div class="rcc-card"><h3>POSITION READINGS · <span class="c-3 w5">each held name against the rulebook's levels — observations, not instructions · ${S.signals.label || "mechanical rulebook; expectancy not validated"}</span>${asOfBadge(S.signals.session_date)}</h3><div class="pos-grid">${boxes}</div></div>`;
}
function renderUniverseCard(){   // system page: the one universe (6.2)
  const u = S.universeMeta; if (!u) return "";
  return `<div class="rcc-card"><h3>THE UNIVERSE · <span class="c-3 w5">one union, built nightly, consumed by both scoring views</span>${asOfBadge(u.as_of)}</h3>
    <div class="mono t1 c-2">union <strong class="c-1">${u.union_size}</strong> tickers = tournament canonical ${u.sizes && u.sizes.tournament_canonical} ∪ screen universe ${u.sizes && u.sizes.screener_universe} ∪ midcap additions ${u.sizes && u.sizes.midcap_additions} ∪ held ${u.sizes && u.sizes.held}</div>
    <div class="mono t1 c-3 mt1">only in the tournament universe: ${(u.only_tournament || []).join(", ") || "none"} · only in the screen universe or the midcap list: ${(u.only_screener_or_midcap || []).join(", ") || "none"} · held names added: ${(u.held_added || []).join(", ") || "none"}</div></div>`;
}

// ── the pages ────────────────────────────────────────────────────────────────────────────
const PAGES = {
  home: {
    title: "PORTFOLIO TOURNAMENT", sub: () => `${updatedStr()} · the regime index and the book's drawdown · 4 algo tiers + Werner`,
    loads: ["config","tournament","regime","regimeDaily","regimePub","regimeV4","v4Cal","v4Attr","status","holdingsFile","intraday","volRegime","book","backtestDD","c3","comparators","eventCal","indicatorSeries"],
    compose(){
      const live = liveRow(); const R = live ? live.R_t : null;
      const rv = renderRegimeCommandCenter(R); const strip = renderStatusStrip();
      let h = renderTopBanner();
      h += `<div class="tier tier-1"><h2 class="tier-title">REGIME</h2>${strip ? `<div class="only-mobile">${strip}</div>` : ""}<div class="tier1-grid">${rv.gauge}${renderDrawdownCard()}</div></div>`;
      h += `<div class="tier tier-2"><h2 class="tier-title">CONTEXT</h2><div class="tier2-grid">${renderRegimeOverlayPanel()}<div>${rv.timeline}${rv.deployment}</div></div></div>`;
      h += `<div class="tier tier-3"><h2 class="tier-title">READINGS</h2><div class="only-desktop">${strip}</div>${d3("INDICATOR READINGS", rv.indicators)}${d3("CALENDAR", renderCalendarCard())}</div>`;
      return h;
    },
  },
  book: {
    title: "THE BOOK", sub: () => `${S.book ? "analytics through " + S.book.as_of : ""} · positions from data/holdings.json, the only holdings source · every panel descriptive`,
    loads: ["config","tournament","book","comparators","thesis","thesisReg","factors","signals","holdingsFile","status","provLedger"],
    compose(){
      const strip = renderStatusStrip();
      let h = `<div class="tier tier-1"><h2 class="tier-title">THE BOOK</h2>${strip}${renderBookPanel()}</div>`;
      h += `<div class="tier tier-2"><h2 class="tier-title">SIZING, STRESS AND SLEEVES</h2>${renderPostureCard()}<div class="rcc-card">${renderStressPanel()}</div>${renderSleevesPanel()}</div>`;
      h += `<div class="tier tier-3"><h2 class="tier-title">POSITIONS</h2>${renderPositionsList()}</div>`;
      return h;
    },
  },
  tournament: {
    title: "THE TOURNAMENT", sub: () => `${updatedStr()} · 4 algorithmic tiers + Werner · monthly rescore + regime overlay · net of costs`,
    loads: ["config","tournament","holdings","tickers","metrics","backtest","condScores","volRegime","thesis","thesisReg","thesisBT","provLedger","c2","signals","regimeDaily","status","regime"],
    compose(){
      const lb = renderLeaderboardBlock(); this._allSeries = lb.allSeries;
      let h = `<div class="tier tier-1"><h2 class="tier-title">LEADERBOARD</h2>${lb.html}</div>`;
      h += `<div class="tier tier-2"><h2 class="tier-title">THESES</h2>${renderTreemapCard()}${renderThesisExposure()}${renderThesisAttribution()}</div>`;
      h += `<div class="tier tier-3"><h2 class="tier-title">SIGNALS</h2>${d3("SCANNER", renderScanner())}</div>`;
      return h;
    },
  },
  evidence: {
    title: "EVIDENCE", sub: () => "the retirement tests with both registrations · the calibration of the graduated model · the point-in-time vintage comparison",
    loads: ["config","c3","c3Paths","comparators","v4Cal","c2","regimeV4","regime","regimePub","v4Attr","status","tournament","metrics"],
    compose(){
      const live = liveRow(); const rv = renderRegimeCommandCenter(live ? live.R_t : null);
      let h = `<div class="tier tier-1"><h2 class="tier-title">RETIREMENT TESTS</h2>${renderRetirementPanel()}</div>`;
      h += `<div class="tier tier-2"><h2 class="tier-title">CALIBRATION AND VINTAGES</h2>${renderCalibrationPanel()}${renderVintageCard()}</div>`;
      h += `<div class="tier tier-3"><h2 class="tier-title">THE GRADUATED MODEL</h2>${d3("V4 RANKING PANEL", rv.v4)}</div>`;
      return h;
    },
  },
  register: {
    title: "THE REGISTER", sub: () => `registry v${(S.thesisReg && S.thesisReg.version) || "—"} · claims, disconfirmers and kill criteria · the provisional ledger · proposals`,
    loads: ["config","thesis","thesisReg","thesisClaims","provLedger","regProposals","status"],
    compose(){
      let h = `<div class="tier tier-1"><h2 class="tier-title">THESES</h2>${renderRegistryBanner()}${renderThesisRegister()}</div>`;
      h += `<div class="tier tier-2"><h2 class="tier-title">LEDGER AND PROPOSALS</h2>${renderProvisionalLedger()}${renderProposals()}</div>`;
      return h;
    },
  },
  system: {
    title: "SYSTEM", sub: () => "audit history · no-publish count · the action log · the universe",
    loads: ["config","status","actions","regimePub","eventCal","tournament","holdingsFile","regime","universeMeta","auditLast"],
    compose(){
      let h = `<div class="tier tier-1"><h2 class="tier-title">PIPELINE</h2>${renderStatusStrip()}${renderSystemPanel()}</div>`;
      h += `<div class="tier tier-2"><h2 class="tier-title">RECORDS</h2>${renderActionLog()}${renderUniverseCard()}</div>`;
      return h;
    },
  },
};

let PAGE = null;
function render(){
  const a = document.getElementById("app"); if (!PAGE) return;
  if (!S.config) { a.innerHTML = '<div class="ld">config.json missing</div>'; return; }
  a.innerHTML = renderNav(PAGE.key) + pageHeader(PAGE.title, PAGE.sub()) + PAGE.compose();
  applyTweens();
  bindEvents();
  drawCharts(PAGE._allSeries || null);
}
async function boot(){
  const key = document.body.dataset.page || "home";
  PAGE = Object.assign({key}, PAGES[key]);
  await loadFiles(PAGE.loads);
  if (!S.config) { document.getElementById("app").innerHTML = '<div class="ld">config.json not found</div>'; return; }
  render();
}
boot();
// re-render when the viewport crosses the mobile breakpoint (disclosure state, chart ticks)
(() => {
  const mq = window.matchMedia ? window.matchMedia("(max-width: 820px)") : null; if (!mq) return;
  let was = mq.matches, timer = null;
  window.addEventListener("resize", () => { clearTimeout(timer); timer = setTimeout(() => { if (mq.matches !== was) { was = mq.matches; if (S.config) render(); } }, 150); });
})();
