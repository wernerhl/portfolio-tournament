"use strict";
const S = {tournament:null, backtest:null, holdings:null, config:null, tickers:null, metrics:null,
           regime:null, regimeDaily:null,
           period:"ALL", expanded:null, expandedTicker:null,
           chart:null, tickerChart:null, regimeChart:null, tickerChartPeriod:"6M",
           expandedIndicator:null, indPeriod:"1Y",
           scannerSort:"quad", scannerSortDir:"desc", scannerFilter:"all",
           leaderboardCondMode:false};   // tournament conditional/unconditional toggle

const fmt   = n => (typeof n === "number") ? n.toLocaleString("en-US",{minimumFractionDigits:0,maximumFractionDigits:0}) : "—";
const fmt2  = n => (typeof n === "number") ? n.toFixed(2) : "—";
const fmtP  = n => (typeof n === "number") ? ((n>=0?"+":"") + n.toFixed(2) + "%") : "—";
const fmtP1 = n => (typeof n === "number") ? ((n>=0?"+":"") + n.toFixed(1) + "%") : "—";
const pnlc  = n => (n>0 ? "pos" : (n<0 ? "neg" : "neut"));

// ── P1.2: colour → token-bound class. Every value-driven colour in the markup goes through
//    cc(); only geometry (bar widths, offsets, heat cells, treemap fills) stays inline.
//    Unknown colours resolve to the neutral text level: the palette does not grow.
const CC_MAP = {
  "var(--g)":"pos","var(--pos)":"pos","#4ade80":"pos","#22c55e":"pos","#5fb98e":"pos","#16a34a":"pos",
  "var(--r)":"neg","var(--neg)":"neg","#f87171":"neg","#ef4444":"neg","#dc2626":"neg","#e0664e":"neg","#fb923c":"neg","#e6914a":"neg","var(--o)":"neg","#fca5a5":"neg",
  "var(--y)":"warn","var(--warn)":"warn","#facc15":"warn","#fde68a":"warn","#fbbf24":"warn","#eab308":"warn","#dba23e":"warn",
  "var(--b)":"info","var(--info)":"info","#60a5fa":"info","#6b9bea":"info","#c084fc":"info","#a88fe5":"info","#a78bfa":"info","var(--p)":"info","#93c5fd":"info","#ddd6fe":"info","#a855f7":"info",
  "var(--accent)":"accent","#c9a86a":"accent",
  "var(--t1)":"1","var(--text-1)":"1","var(--t2)":"2","var(--text-2)":"2","var(--t3)":"3","var(--t4)":"3","var(--t5)":"3","var(--text-3)":"3","#737373":"3","#a3a3a3":"3","#9ca3af":"3","#5e5648":"3",
  "var(--hairline-hi)":"hair","var(--hairline)":"hair","#2c2820":"hair","#3a352b":"hair","transparent":"none",
  "var(--cat1)":"cat-1","var(--cat2)":"cat-2","var(--cat3)":"cat-3","var(--cat4)":"cat-4","var(--cat5)":"cat-5","var(--cat6)":"cat-6","var(--cat7)":"cat-7","var(--cat8)":"cat-8",
};
let TIER_HEX = null;
function cc(color, kind){
  const k = String(color == null ? "" : color).trim().toLowerCase();
  if (!k) return "";
  let key = CC_MAP[k];
  if (!key) {
    if (!TIER_HEX && S.config) {
      TIER_HEX = {};
      Object.entries(S.config.tier_specs || {}).forEach(([tid, sp]) => { if (sp && sp.color) TIER_HEX[String(sp.color).toLowerCase()] = tid; });
      if (S.config.werner_picks && S.config.werner_picks.color) TIER_HEX[String(S.config.werner_picks.color).toLowerCase()] = "5_werner";
    }
    const tid = TIER_HEX && TIER_HEX[k]; if (tid) key = "tier-" + tid;
  }
  if (!key) key = "2";
  if (key === "none") return kind === "bg" ? "bg-none" : "";
  const pre = kind === "bg" ? "bg-" : kind === "bl" ? "bl-" : kind === "bd" ? "bd-" : "c-";
  return pre + key;
}

const TIER_ORDER = ["1_cap_pres","2_balanced","3_aggressive","4_tactical","5_werner"];
const BENCH_FOR_TIER = {"1_cap_pres":"60_40", "2_balanced":"spy", "3_aggressive":"qqq", "4_tactical":"sso", "5_werner":"spy"};

function tierSpec(tid){ if (tid === "5_werner") return S.config.werner_picks; return (S.config.tier_specs || {})[tid]; }
function regimeLabel(R){ return R<0.3?"Low risk":R<0.5?"Elevated":R<0.7?"High risk":"Crisis"; }
function regimeColor(R){ return R<0.3?"var(--g)":R<0.5?"var(--y)":R<0.7?"var(--o)":"var(--r)"; }
// P1.3: chart segment colours from the palette (orange retired: HIGH RISK is a warn/neg mix)
function regimeHex(R){ const c = CHARTS.colors(); return R<0.3 ? c.pos : R<0.5 ? c.warn : R<0.7 ? `color-mix(in srgb, ${c.neg} 60%, ${c.warn})` : c.neg; }
function statusHex(s){ return ({safe:"#4ade80",neutral:"#60a5fa",elevated:"#facc15",crisis:"#f87171"})[s] || "#737373"; }
// Order 1-Oct-2026 [R1.4]: the "crisis" status is extreme only against the trailing 252 sessions; the key,
// the colours and n_crisis are unchanged, the displayed word says what the bucket measures.
function statusLabel(s){ return ({safe:"Safe",neutral:"Neutral",elevated:"Caution",crisis:"Extreme (1y)"})[s] || s; }

// SVG semicircle gauge: 0 → 1 mapped to -90° → +90°.
// Returns inline SVG markup.
function gaugeSVG(R){
  if (R == null) R = 0;
  const cx = 110, cy = 110, r = 90, arc_w = 18;
  // Build 4 colored arcs over [-90°, +90°] (i.e. top half)
  const segs = [
    {from:0.00, to:0.30, color:"#4ade80"}, // safe
    {from:0.30, to:0.50, color:"#facc15"}, // elevated
    {from:0.50, to:0.70, color:"#fb923c"}, // high
    {from:0.70, to:1.00, color:"#f87171"}, // crisis
  ];
  const toXY = t => {
    // t ∈ [0,1] → angle ∈ [180°, 360°] in standard math coords (top semicircle)
    const ang = Math.PI * (1 + t);
    return [cx + r * Math.cos(ang), cy + r * Math.sin(ang)];
  };
  const arcs = segs.map(s => {
    const [x0,y0] = toXY(s.from);
    const [x1,y1] = toXY(s.to);
    const large = (s.to - s.from) > 0.5 ? 1 : 0;
    return `<path d="M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}"
                  fill="none" stroke="${s.color}" stroke-width="${arc_w}" stroke-linecap="butt"/>`;
  }).join("");
  // Needle
  const [nx, ny] = toXY(Math.max(0, Math.min(1, R)));
  const needle = `<line x1="${cx}" y1="${cy}" x2="${nx.toFixed(2)}" y2="${ny.toFixed(2)}"
                       stroke="#d4d4d4" stroke-width="3" stroke-linecap="round"/>
                  <circle cx="${cx}" cy="${cy}" r="6" fill="#d4d4d4"/>`;
  // Labels
  const labels = `<text x="14" y="135" font-family="IBM Plex Mono" font-size="10" fill="#737373">safe</text>
                  <text x="186" y="135" font-family="IBM Plex Mono" font-size="10" fill="#737373" text-anchor="end">danger</text>`;
  return `<svg class="gauge-svg" viewBox="0 0 220 145" xmlns="http://www.w3.org/2000/svg">
            ${arcs}${needle}${labels}
          </svg>`;
}

// Renders the indicator cards grouped by tier (A/B/C). If S.expandedIndicator is
// set, the detail panel is inlined immediately after the tier grid that owns
// the expanded card (was previously appended at the bottom of the rcc-card,
// which put the panel ~3 sections off-screen for a Tier A click).
function renderIndicators(){
  if (!S.regime || !S.regime.indicators) return "";
  const all = S.regime.indicators;
  const hasTiers = all.some(i => i.tier);
  if (!hasTiers) {
    return `<div class="ind-grid">${all.map(renderIndCard).join("")}</div>`
         + (S.expandedIndicator ? renderIndicatorDetail() : "") + IND_LEGEND;
  }
  const tiers = {
    A: {label:"TIER A — FORWARD-LOOKING",  desc:"what markets expect (weight 2.0)", items:[]},
    B: {label:"TIER B — CONTEMPORANEOUS",  desc:"what's happening now (weight 1.0)", items:[]},
    C: {label:"TIER C — CONFIRMING",       desc:"what already happened (weight 0.5)", items:[]},
  };
  all.forEach(i => { if (tiers[i.tier]) tiers[i.tier].items.push(i); });
  return Object.entries(tiers).map(([k, t]) => {
    if (t.items.length === 0) return "";
    const ownsExpanded = S.expandedIndicator && t.items.some(i => i.key === S.expandedIndicator);
    return `
    <div class="ind-tier-head">
      <span><span class="tier-pill ${k}">${k}</span>${t.label.replace(/^TIER [ABC] — /, "")}</span>
      <span class="desc">${t.desc} · ${t.items.length} channel${t.items.length>1?"s":""}</span>
    </div>
    <div class="ind-grid">${t.items.map(renderIndCard).join("")}</div>
    ${ownsExpanded ? renderIndicatorDetail() : ""}`;
  }).join("") + IND_LEGEND + renderRatesStressStrip();
}
// [R1.4] one legend line under the cards
const IND_LEGEND = `<div class="ind-legend mono t1 c-3 mt2">Statuses rank each reading against its own past 252 sessions; the 10-year percentile is shown for scale.</div>`;
// Order 1-Oct-2026 [R5.2]: the rates-stress strip under the regime cards — DIAGNOSTIC, not in R; nothing
// that sizes, labels or colours reads it (referee bond:rates_stress_gate)
function _ord(n){ n = Math.round(n); const t = n % 100, u = n % 10; return n + ((t >= 11 && t <= 13) ? "th" : u === 1 ? "st" : u === 2 ? "nd" : u === 3 ? "rd" : "th"); }
function ratesStressParts(rs){
  const m = rs.move || {}, r = rs.real_10y || {}, n = rs.nominal_10y || {};
  const sgn = v => (v >= 0 ? "+" : "") + v;
  return [
    m.level != null ? `MOVE ${m.level.toFixed(2)}${m.pctile_1y != null ? `, ${_ord(m.pctile_1y)} percentile of the past year` : ""}${m.pctile_10y != null ? `, ${_ord(m.pctile_10y)} of ten years` : ""}${m.change_60 != null ? `; ${sgn(m.change_60.toFixed(1))} over 60 sessions` : ""}` : `MOVE unavailable (${m.reason || "no bar"})`,
    r.level_pct != null ? `10-year real yield (DFII10) ${r.level_pct.toFixed(2)}%${r.pctile_10y != null ? `, ${_ord(r.pctile_10y)} percentile of ten years` : ""}${r.change_60_bp != null ? `; ${sgn(r.change_60_bp.toFixed(0))}bp over 60 sessions` : ""}` : "10-year real yield unavailable",
    n.level_pct != null ? `10-year (DGS10) ${n.level_pct.toFixed(2)}%${n.pctile_10y != null ? `, ${_ord(n.pctile_10y)} percentile of ten years` : ""}${n.change_60_bp != null ? `; ${sgn(n.change_60_bp.toFixed(0))}bp over 60 sessions` : ""}` : "10-year unavailable",
    rs.real_share_of_nominal_change != null ? `the real yield is ${Math.round(rs.real_share_of_nominal_change * 100)}% of that 60-session rise (the rest is the breakeven)` : null,
  ].filter(Boolean);
}
function renderRatesStressStrip(){
  const rs = S.bondsStates && S.bondsStates.rates_stress; if (!rs) return "";
  return `<div class="strip strip-2 mt2"><span class="w6 c-1">Rates stress (DIAGNOSTIC, not in R)</span> · ${ratesStressParts(rs).join(" · ")} <span class="c-3">· as of ${(rs.move && rs.move.date) || "—"} (MOVE), ${(rs.nominal_10y && rs.nominal_10y.date) || "—"} (FRED) · on the Bonds page</span></div>`;
}
function renderBondsRatesStress(){
  const rs = S.bondsStates && S.bondsStates.rates_stress; if (!rs) return "";
  return `<div class="rcc-card"><h3>RATES STRESS <span class="mono t1 w6 r1 x2 c-warn ls06">DIAGNOSTIC</span> · <span class="c-3 w5">Treasury implied volatility and the 10-year real and nominal yields against their own history; not in R</span>${asOfBadge(rs.move && rs.move.date)}</h3>
    ${ratesStressParts(rs).map(p => `<div class="mono t1 c-2 lh16">${p}</div>`).join("")}
    <div class="chart-meta c-warn">${rs.gate || ""}</div>
    <div class="chart-meta">MOVE: the ICE BofA index of one-month implied volatility on Treasury options (yfinance ^MOVE; ICE publishes no free official close, so a session without a bar is unavailable, never substituted) · yields: FRED DFII10 and DGS10 · percentiles: the share of the trailing window below today's value</div></div>`;
}
// AUDIT FIX 2: prefer the intraday-snapshot value when it covers the same
// instrument and is fresher than the EOD payload. Card and banner now agree
// on VIX/VVIX/VIX3M/DXY/SKEW etc. The z-score / phi / status are KEPT from
// the EOD regime computation — those need historical context the intraday
// snapshot lacks.
//
// Mapping: regime-indicator key → intraday.prices[*] key.
const INTRADAY_KEY_MAP = {
  vix: "vix", vvix: "vvix", skew: "skew", dxy: "dxy",
  // vix_term = vix - vix3m; recompute if both legs present.
  vix_term: "_vix_term",
  // SPX (used by spx_drawdown, spx_ret_60d, realized_vol) intentionally
  // NOT overridden — those are derived series, not the raw SPX level.
};
function intradayValueFor(key){
  const id = S.intraday;
  if (!id || !id.prices) return null;
  // Staleness gate: if snapshot is > 90 min old, don't override.
  if (id.timestamp){
    const ageMin = (Date.now() - new Date(id.timestamp + "Z").getTime()) / 60000;
    if (ageMin > 90) return null;
  }
  const mapped = INTRADAY_KEY_MAP[key];
  if (!mapped) return null;
  if (mapped === "_vix_term"){
    const v = id.prices.vix?.last, t = id.prices.vix3m?.last;
    return (v != null && t != null) ? +(v - t).toFixed(2) : null;
  }
  return id.prices[mapped]?.last ?? null;
}
function formatIndicatorValue(key, val, fallbackStr, unit){
  if (val == null) return fallbackStr || "—";
  // Match the precision of the EOD value_str roughly per indicator family; [R1.1] the unit travels too.
  const u = unit ? (unit === "pts" ? " pts" : unit === "$M" ? "M" : unit) : "";
  if (key === "skew" || key === "mfg_new_orders") return val.toFixed(0) + u;
  if (key === "vvix" || key === "vix") return val.toFixed(2) + u;
  if (key === "dxy") return val.toFixed(1) + u;
  if (key === "vix_term") return (val >= 0 ? "+" : "") + val.toFixed(2) + u;
  return ((typeof val === "number") ? val.toFixed(2) : String(val)) + u;
}
// [R1.3] scale line: z against the 252-session window (in the value's own direction, so it reads the same
// way as the narrative) and the ten-year percentile of the same series
function indScaleLine(i){
  if (i.z == null && i.pctile_10y == null) return "";
  const zv = i.z == null ? null : (i.direction === "lower" ? -i.z : i.z);
  const parts = [];
  if (zv != null) parts.push(`z ${zv >= 0 ? "+" : ""}${zv.toFixed(2)} vs past year`);
  if (i.pctile_10y != null) {
    const yrs = i.pctile_window_years, from = i.pctile_window_from;
    const short = yrs != null && yrs < 9.5 && from;
    const mon = short ? new Date(from + "T12:00:00Z").toLocaleDateString("en-US", {month: "short", year: "numeric", timeZone: "UTC"}) : "";
    parts.push(short ? `percentile ${Math.round(i.pctile_10y)} since ${mon} (${yrs} years on record)` : `10-year percentile ${Math.round(i.pctile_10y)}`);
  }
  return `<div class="ind-scale mono t1 c-3">${parts.join(" · ")}</div>`;
}

function renderIndCard(i){
  const c = statusHex(i.status);
  const open = (S.expandedIndicator === i.key);
  const intradayVal = intradayValueFor(i.key);
  const displayedStr = intradayVal != null
    ? formatIndicatorValue(i.key, intradayVal, i.value_str, i.unit)
    : (i.value_str || "—");
  const liveBadge = intradayVal != null
    ? ` <span title="Intraday snapshot" class="mono t1 w6 c-accent ls1 x1">·LIVE</span>`
    : "";
  return `<div class="ind-card ${i.status} ${open?"expanded":""}" data-ind="${i.key}">
    <div class="ind-lbl ${i.status}">${i.label}${liveBadge}</div>
    <div class="ind-val">${displayedStr}</div>
    <div class="ind-narr">${i.narrative || ""}${intradayVal != null ? ' <span class="c-3">(at the close)</span>' : ""}</div>
    ${indScaleLine(i)}
    <div class="ind-bar"><div class="fill ${cc(c,'bg')}" style="width:${(i.phi*100).toFixed(0)}%"></div></div>
  </div>`;
}

// -------- Indicator detail panel --------
function renderIndicatorDetail(){
  if (!S.expandedIndicator || !S.indicatorSeries) return "";
  const key = S.expandedIndicator;
  const ind = S.indicatorSeries.indicators[key];
  if (!ind) return "";
  const c = ind.current || {};
  const st = ind.stats || {};
  const tierColor = ({A:"#f87171", B:"#60a5fa", C:"#a3a3a3"})[ind.tier] || "#737373";
  const stat = (k, v) => `<div class="id-stat-row"><span class="k">${k}</span><span class="v">${v}</span></div>`;

  // Build interpretation text
  const dirWord = ind.direction === "higher" ? "higher = more risk" : "lower = more risk";
  const phi = c.phi != null ? c.phi.toFixed(3) : "—";
  const z = c.z != null ? c.z.toFixed(2) : "—";
  const pct = c.percentile_1y != null ? c.percentile_1y.toFixed(0) : "—";
  let interp = "";
  if (c.phi != null) {
    if (c.phi < 0.40) interp = `Below historical risk threshold. Z-score ${z} (${pct}th 1-year percentile). Not contributing to elevated regime.`;
    else if (c.phi < 0.60) interp = `Near neutral. Z-score ${z} (${pct}th percentile). Mild signal.`;
    else if (c.phi < 0.80) interp = `Elevated risk reading. Z-score ${z} (${pct}th percentile). Contributing to ${ind.tier === "A" ? "early warning" : "regime"} signal.`;
    else interp = `Extreme against its own past 252 sessions. Z-score ${z} (${pct}th 1-year percentile). Strong contribution to the risk score.`;
    const regI = ((S.regime && S.regime.indicators) || []).find(x => x.key === key) || {};
    if (regI.pctile_10y != null) interp += ` Ten-year percentile ${Math.round(regI.pctile_10y)} (scale only; the status uses the 252-session window).`;
  }

  return `<div class="ind-detail">
    <div class="ind-detail-head">
      <div class="ind-detail-title">
        <h3 class="${cc(tierColor)}">${ind.label} <small class="c-3 t1">· ${ind.display_name}</small></h3>
        <div class="sub">TIER ${ind.tier} · WEIGHT ${ind.weight} · ${dirWord.toUpperCase()} · ${ind.source_label}</div>
        <div class="ind-detail-desc">${ind.description || ""}</div>
      </div>
      <button class="ind-detail-close" data-close-ind="1">CLOSE ✕</button>
    </div>

    <div class="id-charts">
      <div class="id-chart-wrap">
        <div class="id-chart-head">
          <div class="id-chart-title">RAW VALUE · DASHED = ±1σ · DOTTED = ±2σ FROM 1Y MEAN</div>
          <div class="id-periods">
            ${["1Y","2Y","5Y","ALL"].map(p => `<button class="id-period-btn ${S.indPeriod===p?"on":""}" data-indp="${p}">${p}</button>`).join("")}
          </div>
        </div>
        <div class="id-chart-canvas"><canvas id="ind-raw-chart"></canvas></div>
      </div>
      <div class="id-chart-wrap">
        <div class="id-chart-head">
          <div class="id-chart-title">Z-SCORE · GREEN BELOW 0 · RED ABOVE 0  (already direction-flipped)</div>
          <div></div>
        </div>
        <div class="id-chart-canvas"><canvas id="ind-z-chart"></canvas></div>
      </div>
    </div>

    <div class="id-stats">
      <div class="id-stat-block">
        <div class="head">CURRENT STATE  ·  ${c.date || "—"}</div>
        ${stat("Value",      c.value_str || "—")}
        ${stat("Z-score",    z)}
        ${stat("Risk score (Φ)", phi)}
        ${stat("Status",     `<span class="${cc(statusHex(c.status||''))}">${(c.status||'—').toUpperCase()}</span>`)}
        ${stat("1Y percentile", pct + "th")}
      </div>
      <div class="id-stat-block">
        <div class="head">STATISTICS  ·  ${st.n_obs || "—"} obs from ${st.start || "—"}</div>
        ${stat("1Y mean",    (st.mean_1y!=null?st.mean_1y:"—"))}
        ${stat("1Y std",     (st.std_1y !=null?st.std_1y :"—"))}
        ${stat("1Y range",   `${st.min_1y} → ${st.max_1y}`)}
        ${stat("All-time range", `${st.min_all} → ${st.max_all}`)}
      </div>
    </div>

    <div class="id-interp"><span class="k">INTERPRETATION</span>${interp}</div>
  </div>`;
}

// Apply a 1Y / 2Y / 5Y / ALL window to a [{d, v}] series
function indFilterPeriod(arr, period){
  if (!arr || !arr.length || period === "ALL") return arr;
  // Default to 1Y when period is undefined. Without this, switch hits no case,
  // `start` stays at the LAST data point's date, and the filter keeps only
  // that single point. A 1-point line has no horizontal extent → Y-axis
  // labels render but no blue line shows (the "empty graphs" bug).
  const p = period || "1Y";
  const last = new Date(arr[arr.length-1].d);
  const start = new Date(last);
  switch(p){
    case "1Y": start.setFullYear(start.getFullYear()-1); break;
    case "2Y": start.setFullYear(start.getFullYear()-2); break;
    case "5Y": start.setFullYear(start.getFullYear()-5); break;
    default:   start.setFullYear(start.getFullYear()-1); break;
  }
  return arr.filter(p => new Date(p.d) >= start);
}

function renderIndicatorCharts(){
  if (!S.expandedIndicator || !S.indicatorSeries) return;
  // Wait one rAF so the parent .id-chart-canvas has non-zero clientWidth/Height
  // before Chart.js measures it. Without this, Chart.js can construct at 0×0
  // and render nothing visible even though no error is thrown.
  requestAnimationFrame(() => _doRenderIndicatorCharts());
}

function _doRenderIndicatorCharts(){
  if (!S.expandedIndicator || !S.indicatorSeries) return;
  const ind = S.indicatorSeries.indicators[S.expandedIndicator];
  if (!ind) return;
  // Use the data-point INDEX as x (linear scale). This sidesteps the
  // chartjs-adapter-date-fns parsing pipeline entirely — earlier attempts with
  // type:"time" (both string dates and ms timestamps) resulted in only the
  // most recent few points being plotted, regardless of data length. The date
  // string is preserved as a 'd' field for tooltip + tick callbacks.
  const toIdx = arr => arr.map((p, i) => ({x: i, y: p.v, d: p.d}))
                           .filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
  const raw = toIdx(indFilterPeriod(ind.chart, S.indPeriod));
  const zs  = toIdx(indFilterPeriod(ind.z_chart, S.indPeriod));
  // Hand-tick ~6 evenly-spaced x labels from the date strings
  const xTickCb = arr => v => {
    const i = Math.round(v);
    return (i >= 0 && i < arr.length && arr[i] && arr[i].d) ? arr[i].d.slice(0, 7) : "";
  };
  const xStep = arr => Math.max(1, Math.floor(arr.length / 6));

  // ---- Raw value chart ----
  const rawCtx = document.getElementById("ind-raw-chart");
  if (rawCtx && raw.length) {
    if (S.indRawChart) { try { S.indRawChart.destroy(); } catch(e){} }
    const m  = (ind.stats && Number.isFinite(ind.stats.mean_1y)) ? ind.stats.mean_1y : null;
    const sd = (ind.stats && Number.isFinite(ind.stats.std_1y))  ? ind.stats.std_1y  : null;
    // Horizon lines now only need 2 points (start + end of x range)
    const CC = CHARTS.colors();
    const horizon = (yval, color, dash, lbl) => ({
      label: lbl, role: "benchmark",
      data: [{x: 0, y: yval}, {x: Math.max(0, raw.length - 1), y: yval}],
      borderColor: color, borderDash: dash, pointRadius: 0, fill: false, tension: 0, showLine: true,
    });
    const datasets = [
      {label: ind.label, data: raw, role: "headline", borderColor: CC.info, tension: 0.1, fill: false},
    ];
    if (m != null && sd != null) {
      datasets.push(horizon(m,        CC.n2,   [4,4], "mean (1y)"));
      datasets.push(horizon(m + sd,   CC.warn, [3,3], "+1σ"));
      datasets.push(horizon(m - sd,   CC.warn, [3,3], "-1σ"));
      datasets.push(horizon(m + 2*sd, CC.neg,  [2,3], "+2σ"));
      datasets.push(horizon(m - 2*sd, CC.neg,  [2,3], "-2σ"));
    }
    try {
      S.indRawChart = CHARTS.make(rawCtx, {
        type: "line",
        data: {datasets},
        options: {
          // No parsing:false — Chart.js 4 default parser handles {x,y} fine on a
          // linear scale, and parsing:false combined with segment/tooltip
          // callbacks reading ctx.parsed.y throws silently and kills the render.
          scales: {
            x: {type:"linear", min: 0, max: Math.max(0, raw.length - 1),
                ticks:{stepSize: xStep(raw), callback: xTickCb(raw)}},
          },
          plugins:{tooltip:{callbacks:{
                              title: items => (items[0] && raw[items[0].dataIndex] && raw[items[0].dataIndex].d) || "",
                              label: ctx => ` ${ctx.dataset.label || ind.label}: ${ctx.parsed.y}`,
                            }}},
        },
      });
    } catch (e) {
      console.error("[ind-raw-chart] Chart.js failed:", e);
    }
  }

  // ---- Z-score chart ----
  const zCtx = document.getElementById("ind-z-chart");
  if (zCtx && zs.length) {
    if (S.indZChart) { try { S.indZChart.destroy(); } catch(e){} }
    try {
    const CZ = CHARTS.colors();
    S.indZChart = CHARTS.make(zCtx, {
      type: "line",
      data: {datasets: [
        {label: "z", data: zs, role: "headline",
         borderColor: CZ.info, tension: 0.1,
         // Defensive: ctx.p1.parsed may be missing in some Chart.js paths.
         // Fall back to ctx.p1.raw which is always the original data point.
         segment: {borderColor: ctx => {
           const y = (ctx.p1 && ctx.p1.parsed && ctx.p1.parsed.y != null)
             ? ctx.p1.parsed.y
             : (ctx.p1 && ctx.p1.raw && ctx.p1.raw.y != null) ? ctx.p1.raw.y : 0;
           return y > 0 ? CZ.neg : CZ.pos;
         }},
         fill: {target: "origin",
                above: CHARTS.alpha(CZ.neg, 0.15),
                below: CHARTS.alpha(CZ.pos, 0.10)}},
      ]},
      options: {
        // (See raw chart above) — no parsing:false; Chart.js 4 handles {x,y}.
        scales: {
          x: {type:"linear", min: 0, max: Math.max(0, zs.length - 1),
              ticks:{stepSize: xStep(zs), callback: xTickCb(zs)}},
        },
        plugins: {tooltip:{callbacks:{
                             title: items => (items[0] && zs[items[0].dataIndex] && zs[items[0].dataIndex].d) || "",
                             label: ctx => ` z = ${ctx.parsed.y.toFixed(2)} (${ctx.parsed.y > 0 ? "above" : "below"} avg)`,
                           }}},
      },
    });
    } catch (e) {
      console.error("[ind-z-chart] Chart.js failed:", e);
    }
  }
}

// Renders the deployment cards for all 5 tiers
function renderDeployment(R){
  return `<div class="deploy-grid">${TIER_ORDER.map(tid => {
    const sp = tierSpec(tid); if (!sp) return "";
    const cashFloor = sp.cash_floor ?? 0;
    const cashSlope = sp.cash_slope ?? 0.7;
    const cashMax   = sp.cash_max   ?? 1.0;
    const cashPct   = R != null ? Math.max(cashFloor, Math.min(cashMax, cashFloor + R * cashSlope)) : cashFloor;
    const deployPct = (1 - cashPct) * 100;
    // Status: based on deployed share
    let status = "Full"; let scolor = "var(--g)";
    if (deployPct < 30)      { status = "Defensive"; scolor = "var(--r)"; }
    else if (deployPct < 60) { status = "Cautious";  scolor = "var(--y)"; }
    else if (deployPct < 85) { status = "Standard";  scolor = "var(--b)"; }
    return `<div class="deploy-card">
      <div class="deploy-lbl ${cc(sp.color)}">${sp.short}</div>
      <div class="deploy-pct ${cc(sp.color)}">${deployPct.toFixed(0)}%</div>
      <div class="deploy-status ${cc(scolor)}">${status}</div>
      <div class="deploy-bar"><div class="fill ${cc(sp.color,'bg')}" style="width:${deployPct}%"></div></div>
      <div class="deploy-sub">${(cashPct*100).toFixed(0)}% cash</div>
    </div>`;
  }).join("")}</div>`;
}

// Renders the regime timeline chart from regime_daily.csv (Chart.js)
function renderRegimeTimeline(){
  const ctx = document.getElementById("regime-timeline");
  if (!ctx || !S.regimeDaily) return;
  if (S.regimeChart) S.regimeChart.destroy();
  // AUDIT FIX 4: chart the PUBLISHED vintage where it exists (live period
  // since inception 2026-05-20); revised recompute elsewhere. Published =
  // what the system actually printed that night; inputs revise afterwards.
  const pubMap = {};
  (S.regimePub || []).forEach(r => {
    if (r && r.date && r.R_t_published != null && !isNaN(r.R_t_published))
      pubMap[String(r.date).slice(0,10)] = +r.R_t_published;
  });
  const points = S.regimeDaily
    .filter(r => r.date && r.R_t != null && !isNaN(r.R_t))
    .map(r => {
      const d = String(r.date).slice(0,10);
      return {x: r.date, y: (d in pubMap) ? pubMap[d] : +r.R_t};
    });
  if (!points.length) return;
  const CR = CHARTS.colors();
  S.regimeChart = CHARTS.make(ctx, {
    type: "line",
    data: {datasets: [{
      label: "R_t", role: "headline",
      data: points,
      tension: 0.05,
      fill: true,
      // Color each segment + fill by Y value
      segment: {
        borderColor: ctx => regimeHex(ctx.p1.parsed.y),
      },
      backgroundColor: (ctx) => {
        const chart = ctx.chart;
        const {ctx: c2d, chartArea} = chart;
        if (!chartArea) return CHARTS.alpha(CR.pos, 0.10);
        const g = c2d.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
        g.addColorStop(0,    CHARTS.alpha(CR.neg, 0.25));   // top  = crisis
        g.addColorStop(0.30, CHARTS.alpha(CR.neg, 0.12));
        g.addColorStop(0.55, CHARTS.alpha(CR.warn, 0.12));
        g.addColorStop(1,    CHARTS.alpha(CR.pos, 0.10));   // bottom = safe
        return g;
      },
    }]},
    options: {
      scales: {
        x: {type:"time", time:{unit:"year"}},
        y: {min:0, max:1,
            ticks:{callback:v => v===0?"safe":(v===0.5?"elevated":(v===1?"crisis":""))}},
      },
      plugins: {
        tooltip: {callbacks:{ label: ctx => ` R_t = ${ctx.parsed.y.toFixed(3)}  (${regimeLabel(ctx.parsed.y)})` }},
      },
    },
  });
}

// Word color for the three classification labels
function ewColor(label){
  return ({"CLEAR":"var(--g)","WATCH":"var(--y)","WARNING":"var(--o)","DANGER":"var(--r)",
           "LOW RISK":"var(--g)","ELEVATED":"var(--y)","HIGH RISK":"var(--o)","CRISIS":"var(--r)",
           "CONSISTENT":"var(--t2)","LEADING RISK":"var(--r)","RECOVERY":"var(--g)"}[label]) || "var(--t2)";
}

// The full Regime Command Center section — built fresh on each render()
// v4 graduated regime: color + action verb for the 4 bands
function v4RegimeColor(reg){
  return ({DEPLOY:"var(--g)",CAUTIOUS:"var(--y)",DEFENSIVE:"var(--o)",CRISIS:"var(--r)"})[reg] || "var(--t3)";
}
function v4RegimeAction(reg){
  return ({
    DEPLOY:    "graduated reading: low drawdown probability; the schedules sit at their cash floors.",
    CAUTIOUS:  "graduated reading: elevated drawdown probability; the schedules move partway toward their cash maxima.",
    DEFENSIVE: "graduated reading: high drawdown probability; the schedules sit near their cash maxima.",
    CRISIS:    "Full Portfolio OS crisis mode.",
  })[reg] || "—";
}

// ──────────────────────────────────────────────────────────────────
// Top banner: intraday SHOCK (red) or staleness (amber).
// Renders ABOVE everything so the user never reads a calm gauge
// without first seeing that the tape has cracked.
// ──────────────────────────────────────────────────────────────────
// ---- Session/staleness helpers (AUDIT FIX 2c + 5) -----------------
// Approximate ET as UTC−4. A DST-precise conversion isn't needed for
// badge logic; worst case the boundary slips one hour twice a year.
// The session and freshness helpers (NYSE_HOLIDAYS, lastTradingSessionISO, dueSessionISO, freshnessOf,
// asOfBadge) live in common.js since 1-Oct-2026, so the screen page shares the same rule.
// Intraday-aware chip: a green "live · HH:MM ET" when the served file is an intraday
// snapshot, else the ordinary as-of badge on its session date. Used by the panels the
// 2-hourly intraday refresh recomputes (the book, and the bonds book-integration).
function intradayBadge(o){
  if (o && o.intraday && o.intraday_as_of){
    const t = String(o.intraday_as_of).slice(11,16);
    return `<span class="mono t1 w6 ls06 c-pos ml2" title="live intraday snapshot at ${o.intraday_as_of}; risk windows are the last settled close">live · ${t} ET</span>`;
  }
  return asOfBadge(o && (o.session_date || o.as_of));
}
function _fmtSnapTime(snap){
  if (!snap) return "—";
  return snap.toLocaleString("en-US", {timeZone:"America/New_York",
    month:"short", day:"numeric", hour:"2-digit", minute:"2-digit"}) + " ET";
}

// Order item 6: status strip — the pipeline's last outcome and the nightly
// audit sweep. CRITICAL (red) means the served artifacts are the last good
// board; HIGH (grey) is logged, never blocking; nothing renders when clean.
function renderStatusStrip(){
  const st = S.status;
  if (!st) return "";
  const parts = [];
  // P1.2: semantic kinds (styles.css .strip-*) — the palette does not grow
  const strip = (kind, txt) => `<div class="strip strip-${kind}">${txt}</div>`;
  const a = st.audit || {};
  // The pipeline's own words stay available under a disclosure; the strip leads with a plain sentence.
  const raw = txt => `<details class="mt1"><summary class="ptr c-3">pipeline detail</summary><div class="c-3 mt1">${escText30(txt)}</div></details>`;
  const servedSess = (() => { const t = S.tournament && S.tournament.history; return t && t.length ? String(t[t.length - 1].date).slice(0, 10) : null; })();
  if (a.critical && a.critical.length)
    parts.push(strip("neg",
      `✗ The referee blocked the ${st.session_date || "last"} publish (CRITICAL: ${a.critical.join(", ")}). The pages show the last good board${servedSess ? ", session " + servedSess : ""}.`));
  else if (st.failure_reason) {
    const fr = String(st.failure_reason);
    const noBar = /PRICE_STORE_SESSION|bar_session_mismatch|max date \S+ < last session/.test(fr);
    const caughtUp = servedSess && st.session_date && servedSess >= st.session_date;
    if (!caughtUp)
      parts.push(strip(freshnessOf(servedSess) === "stale" ? "warn" : "2",
        (noBar
          ? `◷ The ${st.session_date} close is not published yet: the price provider had not posted it when the nightly ran (${String(st.last_attempt || "").slice(11, 16)} ET). The pages show ${servedSess || "the last good session"}; the late retry and the 04:00 ET morning run publish it.`
          : `⚠ The ${st.session_date} publish was rejected by the pipeline's checks. The pages show ${servedSess || "the last good board"} (last success ${String(st.last_success || "").slice(0, 16)}).`)
        + raw(fr)));
  }
  // The non-blocking lines fold into one disclosure (1-Oct-2026: three technical boxes topped every
  // page on a phone); its summary keeps the finding count and the holdings date always visible.
  const info = [];
  if (a.high && a.high.length)
    info.push(`Referee: ${a.high.length} non-blocking finding${a.high.length > 1 ? "s" : ""} logged at ${String(a.ran_at || "").slice(0, 16).replace("T", " ")} UTC: ${a.high.join(", ")}`);
  // B3: cross-file findings are reported in both repositories' strips and block neither;
  // the other repository's CRITICALs are shown but never block this deploy.
  if (a.xfile && a.xfile.length)
    info.push(`cross-file: ${a.xfile.join(", ")} <span class="c-3">(reported in both repositories; blocks neither)</span>`);
  if (a.critical_other_repo && a.critical_other_repo.length)
    info.push(`other repository CRITICAL: ${a.critical_other_repo.join(", ")} <span class="c-3">(does not block this deploy)</span>`);
  // 16-Sept 2.3: the holdings date, always shown (in the summary line)
  const hf = S.holdingsFile;
  if (hf && hf.as_of)
    info.push(`book: holdings.json as of <strong class="c-1">${hf.as_of}</strong> · ${hf.source || "source not stated"}${hf.input_sha256 ? ` · export ${String(hf.input_sha256).slice(0, 12)}` : ""}${hf.exported_at ? ` · exported ${String(hf.exported_at).slice(0, 16)}` : ""}`);
  if (info.length) {
    const nH = (a.high || []).length;
    const sum = [nH ? `referee: ${nH} non-blocking finding${nH > 1 ? "s" : ""}` : "referee: clean",
                 hf && hf.as_of ? `holdings as of <strong class="c-1">${hf.as_of}</strong>${/^brokerage export/i.test(String(hf.source || "")) ? "" : " (manual)"}` : ""].filter(Boolean).join(" · ");
    parts.push(`<details class="strip strip-2 strip-info-fold"><summary class="ptr">${sum}</summary>${info.map(x => `<div class="mt1">${x}</div>`).join("")}</details>`);
  }
  return parts.join("");
}

function renderTopBanner(){
  const id = S.intraday;
  if (!id) return "";
  const now = new Date();
  const snap = id.timestamp ? new Date(id.timestamp + "Z") : null;
  const ageMin = snap ? (now - snap) / 60000 : 9999;
  const snapStr = _fmtSnapTime(snap);

  // Market hours (rough UTC envelope covering EST + EDT)
  const utcH = now.getUTCHours(), utcMin = now.getUTCMinutes();
  const dow = now.getUTCDay();
  const marketOpen = dow >= 1 && dow <= 5 &&
    ((utcH > 13 || (utcH === 13 && utcMin >= 30)) && utcH < 21);
  // AUDIT FIX 5: session scoping — a snapshot from a previous ET calendar
  // day describes the PRIOR session, not live conditions.
  const snapIsCurrentSession = snap && _etDateISO(snap) === _etDateISO(now);
  const shockIsLive = id.shock_active && marketOpen && snapIsCurrentSession;

  const spxStr = (id.spx_change_pct >= 0 ? "+" : "") + (id.spx_change_pct ?? 0) + "%";
  const vixStr = (id.vix_change_pct >= 0 ? "+" : "") + (id.vix_change_pct ?? 0) + "%";

  // 1) LIVE SHOCK — red, only when it is happening NOW
  if (shockIsLive) {
    const reasons = (id.shock_reasons || []).join(" · ");
    return `<div class="r2 mb3 x4">
      <div class="mono t2 w8 c-neg ls1">
        ⚠ INTRADAY STRESS — ACUTE RISK IN CURRENT SESSION</div>
      <div class="serif t1 mt2 lh155 x5">
        ${reasons}. SPX <strong>${spxStr}</strong> intraday, VIX
        <strong>${id.vix_now}</strong> (<strong>${vixStr}</strong>).
        The end-of-day regime below is <strong>STALE</strong> and does not reflect this move;
        it re-reads at the close.
        <span class="x6">snapshot ${snapStr} · ${Math.round(ageMin)} min ago</span></div>
    </div>`;
  }

  // 1b) PRIOR-SESSION SHOCK — amber. Red means happening now; amber means
  // happened, market closed (or the cron hasn't caught up to a new session).
  if (id.shock_active && !shockIsLive) {
    return `<div class="r2 mb3 x7">
      <div class="mono t1 w7 c-warn ls08">
        ◷ PRIOR SESSION WAS A SHOCK DAY</div>
      <div class="serif t1 c-warn mt1 lh155">
        SPX <strong>${spxStr}</strong>, VIX <strong>${id.vix_now}</strong> (<strong>${vixStr}</strong>)
        in the last session. Market ${marketOpen ? "is open but the intraday snapshot hasn't refreshed yet" : "is closed"};
        this banner reflects the prior session, not live conditions.
        <span class="c-warn">snapshot ${snapStr}</span></div>
    </div>`;
  }

  // 2) STALENESS — amber when market open and either old or moved
  const spxMoved = Math.abs(id.spx_change_pct || 0) > 1.0;
  if (marketOpen && (ageMin > 60 || spxMoved)) {
    return `<div class="r2 mb3 x8">
      <div class="mono t1 w7 c-warn ls08">
        ⚠ REGIME SNAPSHOT IS STALE</div>
      <div class="serif t1 c-warn mt1 lh155">
        Regime computed on prior close. SPX <strong>${spxStr}</strong> since,
        VIX now <strong>${id.vix_now}</strong>. The DEPLOY/CAUTIOUS call below
        does NOT reflect the current session.
        <span class="c-warn">snapshot ${snapStr}</span></div>
    </div>`;
  }

  // 3) COMPLACENCY — active chip (purple) or IMPAIRED chip (amber).
  // JULY AUDIT FIX 2: a safety check with missing input must render
  // IMPAIRED, never silently read as calm.
  if (id.complacency_active === "impaired") {
    return `<div class="r2 mb3 x9">
      <div class="mono t1 w7 c-warn ls08">
        ⚠ COMPLACENCY CHECK IMPAIRED</div>
      <div class="serif t1 c-warn mt1 lh155">
        ${id.complacency_reason}. The check did NOT evaluate — this is not an all-clear.
        <span class="c-warn">snapshot ${snapStr}</span></div>
    </div>`;
  }
  if (id.complacency_active === true) {
    return `<div class="r2 mb3 x10">
      <div class="mono t1 w7 c-info ls08">
        COMPLACENCY FLAG</div>
      <div class="serif t1 mt1 lh155 x11">
        ${id.complacency_reason}. <span class="x12">snapshot ${snapStr}</span></div>
    </div>`;
  }
  return "";
}

// JULY AUDIT FIX 1a — governance banner: registry unapproved or coverage hole.
function renderRegistryBanner(){
  const td = S.thesis;
  if (!td) return "";
  const holes = Object.entries(td.tiers || {})
    .filter(([_, t]) => (t.unclassified_share || 0) > 0.15);
  const unfrozen = !td.registry_frozen;
  const prov = td.provisional || {};
  if (!holes.length && !unfrozen && !(prov.count > 0)) return "";
  const nNames = new Set(holes.flatMap(([_, t]) => t.unclassified_names || [])).size;
  const parts = [];
  if (unfrozen) parts.push(`registry v${td.registry_version} unapproved`);
  // A1: provisional mappings count toward coverage but are never silently permanent
  if (prov.count > 0) parts.push(`<span class="c-warn mono t1 w6 r1 x13">PROVISIONAL</span> ${prov.count} agent-proposed mapping${prov.count > 1 ? "s" : ""} applied — they expire back to unclassified from ${prov.expires_earliest || "?"} unless approved into the registry`);
  // 1-Oct-2026: with no wholly unclassified name, the share comes from partial memberships — say so
  // (the banner read "0 names unclassified across 1 tier (WERNER 17%)")
  const holeTxt = holes.map(([tid, t]) => `${(tierSpec(tid)||{}).short || tid} ${(t.unclassified_share*100).toFixed(0)}%`).join(" · ");
  if (holes.length) parts.push(nNames
    ? `${nNames} name${nNames > 1 ? "s" : ""} unclassified across ${holes.length} tier${holes.length > 1 ? "s" : ""} (${holeTxt} of invested value)`
    : `${holeTxt} of invested value unclassified, from names only partly mapped to a theme (no name is wholly unmapped)`);
  return `<div class="r2 mb3 x14">
    <div class="mono t1 w7 c-warn ls08">
      ⚠ THESIS REGISTRY NEEDS ATTENTION</div>
    <div class="serif t1 c-warn mt1 lh155">
      ${parts.join(" · ")}. Review <span class="mono">data/registry_proposals.json</span>
      and approve into the registry with a version bump — the agent never auto-merges.</div>
  </div>`;
}

// ──────────────────────────────────────────────────────────────────
// headlineVerdict — show the WORST of all signals, never the calmest.
// Ranks v2 regime, v4 graduated regime, crisis-channel count,
// complacency flag, and intraday shock. Returns {label, color, action}.
// ──────────────────────────────────────────────────────────────────
function headlineVerdict(){
  const reg = S.regime || {};
  const v4Last = (S.regimeV4 && S.regimeV4.length)
    ? S.regimeV4.filter(r => r && r.p_5_40_calibrated != null && !isNaN(r.p_5_40_calibrated)).slice(-1)[0]
    : null;
  // AUDIT FIX 2c: a stale calm signal must never be able to vote. If the
  // v4 series hasn't been computed for the last trading session, exclude
  // it from the worst-of ranking and annotate the exclusion.
  const v4AsOf  = v4Last ? String(v4Last.date || "").slice(0,10) : null;
  const v4Stale = isStaleAsOf(v4AsOf);
  const v4reg = (v4Last && !v4Stale) ? v4Last.graduated_regime : null;

  // Severity rankings (higher = more cautious)
  const rank = {
    "DEPLOY": 0, "LOW RISK": 0, "CLEAR": 0,
    "CAUTIOUS": 1, "ELEVATED": 1, "WATCH": 1,
    "DEFENSIVE": 2, "HIGH RISK": 2, "WARNING": 2,
    "CRISIS": 3, "DANGER": 3,
  };
  const colorMap = {
    "DEPLOY":"#4ade80", "CAUTIOUS":"#facc15", "DEFENSIVE":"#fb923c", "CRISIS":"#f87171",
    "INTRADAY STRESS":"#dc2626", "COMPLACENT":"#c084fc",
  };
  const actionMap = {
    "DEPLOY":     "the regime schedules sit at their cash floors (full deployment for every tier).",
    "CAUTIOUS":   "the regime schedules hold roughly three quarters of full deployment.",
    "DEFENSIVE":  "the regime schedules hold roughly half of full deployment.",
    "CRISIS":     "the regime schedules sit at their cash maxima.",
    "INTRADAY STRESS": "the end-of-day reading below is stale for this session; it re-reads at the close.",
    "COMPLACENT": "the complacency flag is active: implied protection is cheap by the flag's definition.",
  };

  let worst = "DEPLOY";
  let worstRank = 0;
  const consider = (label) => {
    if (!label) return;
    const r = rank[label];
    if (r != null && r > worstRank) { worstRank = r; worst = label; }
  };

  consider(reg.regime);
  consider(reg.early_warning);
  // Decision Memo 9-Sept-2026 §5: v4's calibrated probability has no out-of-fold
  // skill over the base rate (Brier 0.1989 vs 0.1918, B2). It no longer votes in
  // the headline; the headline is the regime index whose value C3 measured. v4
  // stays on the panel as a RANKING signal (AUC ≈ 0.64) with its numbers beside it.
  if ((reg.n_crisis || 0) >= 1) consider("DEFENSIVE");
  if ((reg.n_crisis || 0) >= 4) consider("CRISIS");
  // Complacency: NEVER show DEPLOY when SKEW>140 + VIX<17
  const complacent = !!(reg.complacency_flag || (S.intraday && S.intraday.complacency_active));
  if (complacent && worstRank < 1) { worst = "COMPLACENT"; worstRank = 1; }
  // Shock overrides everything — but ONLY a live one. A prior-session shock
  // is already baked into the EOD v2 regime; letting yesterday's snapshot
  // keep shouting INTRADAY STRESS pre-open is the mirror image of the
  // stale-calm bug. (AUDIT FIX 5 applied to the headline too.)
  const _snap = (S.intraday && S.intraday.timestamp) ? new Date(S.intraday.timestamp + "Z") : null;
  const _now = new Date();
  const _utcH = _now.getUTCHours(), _utcMin = _now.getUTCMinutes(), _dow = _now.getUTCDay();
  const _mktOpen = _dow >= 1 && _dow <= 5 && ((_utcH > 13 || (_utcH === 13 && _utcMin >= 30)) && _utcH < 21);
  const shockLive = !!(S.intraday && S.intraday.shock_active && _mktOpen
                        && _snap && _etDateISO(_snap) === _etDateISO(_now));
  if (shockLive) { worst = "INTRADAY STRESS"; worstRank = 99; }

  // Map v2 → action vocabulary
  if (worst === "LOW RISK")  worst = "DEPLOY";
  if (worst === "ELEVATED")  worst = "CAUTIOUS";
  if (worst === "HIGH RISK") worst = "DEFENSIVE";
  if (worst === "WATCH")     worst = "CAUTIOUS";
  if (worst === "WARNING")   worst = "DEFENSIVE";
  if (worst === "DANGER")    worst = "CRISIS";

  return {
    label:  worst,
    color:  colorMap[worst] || "#a3a3a3",
    action: actionMap[worst] || "",
    inputs: {
      v2_regime: reg.regime, v2_ew: reg.early_warning,
      v4_regime: v4reg,
      v4_excluded: "no out-of-fold skill over the base rate; ranking only (memo 9-Sept-2026 §5)",
      v4_stale: v4Stale, v4_as_of: v4AsOf,
      n_crisis: reg.n_crisis || 0,
      complacent: complacent,
      shock: shockLive,
      shock_prior_session: !!(S.intraday && S.intraday.shock_active && !shockLive),
    },
  };
}

// Decision Memo 9-Sept-2026 §1: the C3 verdict of record under v1 is never removed
// from the dashboard; the amendment paragraph travels with the v2 verdict.
function c3VerdictLine(){
  const r = S.c3; if (!r || !r.decision) return "";
  const d1 = r.decision, d2 = r.decision_v2;
  const ci = d2 && d2.paired_diff_return_per_vol_ci90;
  const sg = x => (x >= 0 ? "+" : "") + (+x).toFixed(3);
  const yrs = r.window ? `${String(r.window[0]).slice(0,4)}–${String(r.window[1]).slice(2,4)}` : "2010–26";
  return `<div class="mono t1 c-3 mt1" title="Pre-registered test C3 (reports/retirement_test_C3_regime_vs_rules.md). v1 rule: the regime's return-per-volatility margin over the best one-line rule had to exceed the half-width of the regime's own 90% bootstrap interval — a bar no monthly overlay on this window could clear (the rules' own half-widths are 0.44–0.45). v2 (registration amended 9-Sept-2026 AFTER the v1 result, disclosed in reports/c3_registration_v2.md): the paired 90% interval must lie above zero. Both verdicts stay on record.">C3 regime vs one-line rules (${yrs}, tier-4 overlay, net of costs): <span class="c-neg">v1 verdict FAIL</span> (margin ${d1.margin != null ? sg(d1.margin) : "—"} vs required ${d1.half_width_regime_ci90 != null ? (+d1.half_width_regime_ci90).toFixed(3) : "—"})${d2 ? ` · <span class="${cc(d2.regime_passes ? "var(--g)" : "var(--r)")}">v2 verdict ${d2.regime_passes ? "PASS" : "FAIL"}</span> (paired interval [${ci ? sg(ci[0]) + ", " + sg(ci[1]) : "—"}]; drawdown reduction ${(d2.dd_reduction_regime*100).toFixed(1)}% vs ${(d2.dd_reduction_best_rule*100).toFixed(1)}%)` : ""} · amendment made after the v1 result, disclosed.</div>`;
}

function renderRegimeCommandCenter(R){
  const reg = S.regime || {};
  const total = reg.n_indicators || 12;
  const safe  = reg.n_safe || 0;
  const neu   = reg.n_neutral || 0;       // AUDIT FIX 3: separate bucket
  const ele   = reg.n_elevated || 0;
  const cri   = reg.n_crisis || 0;

  // v2 fields: R_lead / R_full / divergence + their classifications
  const R_lead = reg.R_lead;
  const R_full = reg.R_full != null ? reg.R_full : (reg.R_t != null ? reg.R_t : R);
  const divv   = reg.divergence;
  const ew     = reg.early_warning;
  const rgm    = reg.regime;
  const divlab = reg.divergence_alert;
  const v2 = (R_lead != null && R_full != null);

  // v4 fields: latest row of regime_v4_daily.csv — with freshness check.
  // AUDIT FIX 2c: stale v4 still DISPLAYS (with an amber as-of badge) but
  // never votes in the headline (handled in headlineVerdict).
  const v4Last = (S.regimeV4 && S.regimeV4.length)
    ? S.regimeV4.filter(r => r && r.p_5_40_calibrated != null && !isNaN(r.p_5_40_calibrated)).slice(-1)[0]
    : null;
  const v4AsOfCC  = v4Last ? String(v4Last.date || "").slice(0,10) : null;
  const v4StaleCC = isStaleAsOf(v4AsOfCC);
  const p5_40 = v4Last ? +v4Last.p_5_40_calibrated : null;
  const p3_20 = v4Last && v4Last.p_3_20_equal_weight != null ? +v4Last.p_3_20_equal_weight : null;
  const p10_60 = v4Last && v4Last.p_10_60_equal_weight != null ? +v4Last.p_10_60_equal_weight : null;
  const p7_40 = v4Last && v4Last.p_7_40_equal_weight != null ? +v4Last.p_7_40_equal_weight : null;
  const v4reg = v4Last ? v4Last.graduated_regime : null;
  const v4color = v4RegimeColor(v4reg);

  // Headline = WORST of v2 / v4 / crisis-count / complacency / shock
  const headline = headlineVerdict();
  const lbl = headline.label;
  const lblColor = headline.color;
  const rDisp = R_full != null ? R_full.toFixed(3) : "—";

  // Verdict prefers headline action; surface the per-source inputs so the user sees WHY
  const inputs = headline.inputs;
  const inputLine = [
    inputs.v2_regime ? `v2 ${inputs.v2_regime}` : null,
    inputs.v4_regime ? `v4 ${inputs.v4_regime} <span class="c-3" title="${inputs.v4_excluded || ""}">(ranking only, not voting)</span>` : null,
    inputs.v4_stale ? `<span class="c-warn">v4: stale (as of ${inputs.v4_as_of || "?"})</span>` : null,
    inputs.n_crisis > 0 ? `${inputs.n_crisis} channel${inputs.n_crisis > 1 ? "s" : ""} ${statusLabel("crisis").toLowerCase()}` : null,
    inputs.complacent ? `complacent` : null,
    inputs.shock ? `intraday shock` : null,
    inputs.shock_prior_session ? `prior-session shock (not voting)` : null,
  ].filter(Boolean).join(" · ");
  const verdict = `<strong class="${cc(lblColor)}">${headline.label}.</strong> ${headline.action}
    <div class="mt2 mono t1 c-3">${inputLine}</div>
    ${eventTodayBadge()}
    ${nextEventLine()}`;

  // ---- New score row: graduated probabilities (v4) + v2 R_full as backup ----
  const probCell = (label, p, action) => {
    if (p == null) return `<div class="score-cell">
        <div class="k">${label}</div><div class="v c-3">—</div></div>`;
    const pctText = (p * 100).toFixed(0) + "%";
    let cellColor = "var(--g)";
    if (p > 0.45) cellColor = "var(--o)";
    else if (p > 0.25) cellColor = "var(--y)";
    if (p > 0.65) cellColor = "var(--r)";
    return `<div class="score-cell">
        <div class="k">${label}</div>
        <div class="v ${cc(cellColor)}">${pctText}</div>
        ${action ? `<div class="s ${cc(cellColor)}">${action}</div>` : ""}
      </div>`;
  };
  const scoreRow = v4Last ? `${v4StaleCC ? `<div class="mt2 tac">
      <span class="mono t1 w6 ls08 r1 c-warn x15">
        ⚠ v4 STALE · as of ${v4AsOfCC}</span>
    </div>` : ""}<div class="score-row ${v4StaleCC ? 'dim' : ''}">
      ${probCell("≥3% over NEXT 20D", p3_20, "")}
      ${probCell("≥5% over NEXT 40D · CAL", p5_40, v4reg)}
      ${probCell("≥10% over NEXT 60D", p10_60, "")}
    </div>
    ${(() => {
      // JULY AUDIT FIX 4a: render the delta attribution under the probability
      const a = S.v4Attr;
      if (!a || !a.top3 || a.as_of !== v4AsOfCC) return "";
      const movers = a.top3.map(c => `${c.feature} ${c.contribution_pp >= 0 ? "+" : ""}${c.contribution_pp}pp`).join(" · ");
      return `<div class="mt1 mono t1 c-3 tac lh15">
        Δ ${a.delta_pp >= 0 ? "+" : ""}${a.delta_pp}pp vs ${a.prev} — moved by: ${movers}
        <span class="c-3">(contributions approximate; residual ${a.residual_pp >= 0 ? "+" : ""}${a.residual_pp}pp)</span>
      </div>`;
    })()}
    <div class="mt2 mono t1 c-3 tac lh14">
      Multi-week drawdown probabilities (cumulative over the horizon). Does NOT protect against
      single-day gaps — see the intraday banner at the top for same-session risk.
    </div>` : (v2 ? `<div class="score-row">
      <div class="score-cell">
        <div class="k">EARLY WARNING</div>
        <div class="v">${R_lead.toFixed(3)}</div>
        <div class="s ${cc(ewColor(ew))}">${ew}</div>
      </div>
      <div class="score-cell">
        <div class="k">CURRENT REGIME</div>
        <div class="v">${R_full.toFixed(3)}</div>
        <div class="s ${cc(ewColor(rgm))}">${rgm}</div>
      </div>
      <div class="score-cell">
        <div class="k">DIVERGENCE</div>
        <div class="v">${divv >= 0 ? "+" : ""}${divv.toFixed(3)}</div>
        <div class="s ${cc(ewColor(divlab))}">${divlab}</div>
      </div>
    </div>` : "");

  // Compact v2 footnote: R_full / R_lead / divergence on one line
  const v2Foot = v2 ? `<div class="mt2 pt2 mono t1 c-3 tac lh16 x16">
      <span class="c-3">v2:</span>
      R<sub>full</sub> <strong class="${cc(ewColor(rgm))}">${R_full.toFixed(3)} ${rgm}</strong>
      &middot; R<sub>lead</sub> <strong class="${cc(ewColor(ew))}">${R_lead.toFixed(3)} ${ew}</strong>
      &middot; div <strong class="${cc(ewColor(divlab))}">${divv >= 0 ? "+" : ""}${divv.toFixed(3)} ${divlab}</strong>
      <div class="mt1 serif t1 it c-3">
        Regime label uses ±0.02 hysteresis at band boundaries (enter ELEVATED ≥ 0.32, exit &lt; 0.28)
        to stop flapping at the boundaries; R values themselves are untouched.</div>
    </div>` : "";

  // AUDIT FIX 3: 4-bucket count matches card colors (green / blue / amber / red)
  const tierCounts = `<span class="mono t1 c-3 ls0 x17">
    <span class="c-pos">${safe} safe</span> ·
    <span class="c-info">${neu} neutral</span> ·
    <span class="c-warn">${ele} elevated</span> ·
    <span class="c-neg">${cri} ${statusLabel("crisis").toLowerCase()}</span></span>`;

  // P1.4: the command centre is returned as tier fragments; render() places them:
  //   gauge → tier one · timeline + deployment → tier two · indicators + v4 → tier three
  const gauge = `<div class="rcc-card gauge-card">
        <h3>CYCLE POSITION · <span class="c-3 w5" title="Decision Memo 9-Sept-2026 §5: the headline is the regime index whose value C3 measured; v4 no longer votes">regime index</span>${asOfBadge(reg.as_of)}</h3>
        ${gaugeSVG(R_full)}
        <div class="gauge-lbl ${cc(lblColor)}">${lbl}</div>
        <div class="gauge-rt">R<sub>full</sub> = <span class="r-num" data-tween="rfull" data-val="${R_full != null ? R_full : ""}" data-fmt="n3">${rDisp}</span></div>
        ${renderMovedByLine()}
        ${c3VerdictLine()}
        <div class="verdict">${verdict}</div>
        ${v2Foot}
      </div>`;
  const v4 = v4Last ? `<div class="rcc-card v4-card">
        <h3>V4 GRADUATED PROBABILITY · <span class="c-3 w5">ranking signal, not a forecast</span>${asOfBadge(v4AsOfCC)}</h3>
        ${v4Last.raw_score != null && !isNaN(v4Last.raw_score) ? `<div class="mono t1 w5 c-3 mt1">raw score <span class="c-1">${(+v4Last.raw_score).toFixed(3)}</span> <span class="c-3">(pre-calibration)</span></div>
        <div class="serif t1 it c-3 mt1">calibrated probability moves in steps; the raw score moves continuously.</div>
        ${(() => { // order 9-Sept B1.2: model-change note, shown for 30 sessions after the change, with OUT-OF-FOLD numbers (B2)
          const rows = Array.isArray(S.regimeV4) ? S.regimeV4.filter(r => r && r.date && String(r.date) > "2026-09-07") : [];
          return rows.length < 30 ? `<div class="mono t1 w5 c-warn mt1" title="model_version ${v4Last.model_version || ""} · out-of-fold = leave-one-crisis-out folds, isotonic fitted on training predictions only">model changed 2026-09-07: equal-weight replaces logistic; out-of-fold Brier 0.1989 vs 0.2145 (logistic) — base rate 0.1918: no out-of-fold skill over the base rate on Brier; in-sample 0.1835 was the isotonic fit.</div>` : ``; })()}` : ``}
        ${scoreRow}
        ${(() => { // Decision Memo 9-Sept-2026 §5: standing note — v4 is a ranking signal, not a forecast
          const c = S.v4Cal || {}; const m = (c.methods && c.methods[c.winning_method || "equal_weight"]) || {};
          const oof = m.brier_out_of_fold, base = c.base_rate_brier;
          return `<div class="mono t1 w5 c-3 mt1 r1 x18" title="out-of-fold = 15 leave-one-crisis-out folds, isotonic fitted on training predictions only (B2); the underlying index retains ranking skill (AUC ≈ 0.64, C2). No in-sample reliability figure is shown: isotonic fitting makes it look perfect by construction.">v4 graduated probability — <strong class="c-1">ranking signal, not a forecast</strong>: out-of-fold Brier <strong class="c-1">${oof != null ? (+oof).toFixed(4) : "—"}</strong> vs base rate <strong class="c-1">${base != null ? (+base).toFixed(4) : "—"}</strong> — does not beat the base rate out of fold; use as a ranking, not a forecast. Not a headline input.</div>`; })()}
      </div>` : (scoreRow ? `<div class="rcc-card v4-card"><h3>REGIME SCORES</h3>${scoreRow}</div>` : "");
  const indicators = `<div class="rcc-card">
        <h3 class="flx x19">INDICATOR READINGS — ${total} CHANNELS ${tierCounts}</h3>
        ${renderIndicators()}
      </div>`;
  const deployment = `<div class="rcc-card">
      <h3>DEPLOYMENT SIGNAL PER TIER</h3>
      ${renderDeployment(R_full)}
    </div>`;
  const timeline = `<div class="rcc-card">
      <h3>REGIME TIMELINE — R<sub>full</sub> with regime bands (safe → elevated → crisis)</h3>
      <div class="timeline-wrap"><canvas id="regime-timeline"></canvas></div>
      <div class="mt2 serif t1 it c-3 lh145">
        Vintages: indicator inputs revise after the fact (several FRED series publish T+1 or weekly).
        Since inception 2026-05-20 this chart shows the <strong class="fs-n">as-published</strong>
        values — what the system printed that night — preserved in regime_daily_published.csv.
        Earlier history is the revised recompute. Real-time performance claims must use the published vintage.
        ${(() => { const rows = Array.isArray(S.regimePub) ? S.regimePub : []; const np = rows.filter(r => r && r.date && (r.R_t_published == null || r.R_t_published === "" || isNaN(+r.R_t_published))); return rows.length ? `<div class="mt1 fs-n c-3">Reliability: <strong>${np.length}</strong> no-publish session${np.length === 1 ? "" : "s"} of ${rows.length} since inception${np.length ? " — " + np.map(r => String(r.date).slice(0,10)).join(", ") + " (reasons in regime_daily_published.csv)" : ""}</div>` : ``; })()}
      </div>
    </div>`;
  return {gauge, v4, indicators, deployment, timeline};
}
function rankColor(pct){ return pct>=70?"var(--g)":pct>=40?"var(--y)":"var(--r)"; }
function corrColor(c){ const a=Math.abs(c); return a>=0.7?"var(--r)":a>=0.4?"var(--y)":"var(--g)"; }

// -------- Build unified series per tier (backtest + live, rebased at seam) --------
function buildSeries(){
  const series = {};                   // tier_id → [{date, nav}]
  const benchSeries = {spy:[], qqq:[], "60_40":[], sso:[]};

  if (S.backtest && S.backtest.rows) {
    const rows = S.backtest.rows;
    TIER_ORDER.forEach(tid => {
      series[tid] = rows.filter(r => r[tid] != null && !isNaN(r[tid]))
                        .map(r => ({date:r.date, nav:+r[tid]}));
    });
    Object.keys(benchSeries).forEach(b => {
      benchSeries[b] = rows.filter(r => r[b] != null && !isNaN(r[b]))
                            .map(r => ({date:r.date, nav:+r[b]}));
    });
  }

  if (S.tournament && S.tournament.history && S.tournament.history.length > 0) {
    TIER_ORDER.forEach(tid => {
      const liveDays = S.tournament.history.filter(h => h.tiers && h.tiers[tid] && h.tiers[tid].nav > 0);
      if (liveDays.length === 0) return;
      series[tid] = series[tid] || [];
      const btDates = new Set(series[tid].map(r => r.date));
      const btLastDate = series[tid].length > 0 ? series[tid][series[tid].length-1].date : null;
      // Find a live entry whose date OVERLAPS with backtest — use that pair for rebasing
      // so that live[seam] · k = backtest[seam].
      let k = 1.0;
      if (tid !== "5_werner") {
        const overlap = liveDays.find(d => btDates.has(d.date));
        if (overlap) {
          const btMatch = series[tid].find(r => r.date === overlap.date);
          if (btMatch && overlap.tiers[tid].nav > 0) k = btMatch.nav / overlap.tiers[tid].nav;
        } else if (series[tid].length > 0) {
          // No overlap — fall back to ratio of last backtest vs first live
          k = series[tid][series[tid].length-1].nav / liveDays[0].tiers[tid].nav;
        }
      }
      // Append ONLY live entries whose date is strictly AFTER the backtest endpoint.
      liveDays.forEach(d => {
        if (!btLastDate || d.date > btLastDate) {
          series[tid].push({date:d.date, nav:d.tiers[tid].nav * k, live:true});
        }
      });
      series[tid].sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : 0);
    });
    // Benchmarks: same rules
    Object.keys(benchSeries).forEach(b => {
      const live = S.tournament.history
        .filter(h => h.benchmarks && h.benchmarks[b] && h.benchmarks[b].nav != null)
        .map(h => ({date:h.date, nav:h.benchmarks[b].nav}));
      if (live.length === 0) return;
      const btDates = new Set(benchSeries[b].map(r => r.date));
      const btLastDate = benchSeries[b].length > 0 ? benchSeries[b][benchSeries[b].length-1].date : null;
      let k = 1.0;
      const overlap = live.find(d => btDates.has(d.date));
      if (overlap) {
        const btMatch = benchSeries[b].find(r => r.date === overlap.date);
        if (btMatch && overlap.nav > 0) k = btMatch.nav / overlap.nav;
      } else if (benchSeries[b].length > 0) {
        k = benchSeries[b][benchSeries[b].length-1].nav / live[0].nav;
      }
      live.forEach(d => {
        if (!btLastDate || d.date > btLastDate) benchSeries[b].push({date:d.date, nav:d.nav * k});
      });
      benchSeries[b].sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : 0);
    });
  }
  return {tiers:series, bench:benchSeries};
}

function applyPeriod(series, period){
  if (!series.length) return series;
  if (period === "ALL") return series;
  const lastDate = new Date(series[series.length-1].date);
  let start = new Date(lastDate);
  switch(period){
    case "1M": start.setMonth(start.getMonth()-1); break;
    case "3M": start.setMonth(start.getMonth()-3); break;
    case "6M": start.setMonth(start.getMonth()-6); break;
    case "YTD": start = new Date(lastDate.getFullYear(), 0, 1); break;
    case "1Y": start.setFullYear(start.getFullYear()-1); break;
    case "5Y": start.setFullYear(start.getFullYear()-5); break;
    default: return series;
  }
  return series.filter(r => new Date(r.date) >= start);
}

function rebase(series){
  if (!series.length) return series;
  const base = series[0].nav;
  return series.map(r => ({...r, nav: r.nav / base}));
}

function tierMetrics(series, benchSeries){
  if (!series || series.length < 2) return null;
  const first = series[0].nav, last = series[series.length-1].nav;
  const total = (last/first - 1) * 100;
  const lastDate = new Date(series[series.length-1].date);
  const wAgo = new Date(lastDate); wAgo.setDate(wAgo.getDate()-7);
  const mAgo = new Date(lastDate); mAgo.setMonth(mAgo.getMonth()-1);
  const findPrior = d => { for (let i = series.length-1; i >= 0; i--) if (new Date(series[i].date) <= d) return series[i].nav; return null; };
  const w1 = (() => { const p = findPrior(wAgo); return p ? (last/p - 1) * 100 : null; })();
  const m1 = (() => { const p = findPrior(mAgo); return p ? (last/p - 1) * 100 : null; })();

  const rets = [];
  let runMax = first, maxDD = 0;
  for (let i = 1; i < series.length; i++){
    rets.push(series[i].nav / series[i-1].nav - 1);
    runMax = Math.max(runMax, series[i].nav);
    maxDD  = Math.min(maxDD, series[i].nav / runMax - 1);
  }
  const mean = rets.reduce((a,b)=>a+b,0) / rets.length;
  const sd = Math.sqrt(rets.reduce((s,r)=>s+(r-mean)**2,0) / rets.length);
  const sharpe = sd > 0 ? (mean * 252) / (sd * Math.sqrt(252)) : 0;

  let alpha = null;
  if (benchSeries && benchSeries.length >= 2){
    const bRet = (benchSeries[benchSeries.length-1].nav / benchSeries[0].nav - 1) * 100;
    alpha = total - bRet;
  }
  return {total, w1, m1, sharpe, maxDD:maxDD*100, alpha};
}

// -------- Race chart --------
function renderChart(allSeries, period){
  const ctx = document.getElementById("race-chart");
  if (!ctx) return;
  if (S.chart) S.chart.destroy();
  const CC = CHARTS.colors();
  const datasets = [];
  TIER_ORDER.forEach(tid => {
    const t = tierSpec(tid);
    const ser = allSeries.tiers[tid];
    if (!t || !ser || ser.length === 0) return;
    const periodSer = applyPeriod(ser, period);
    const rebased = rebase(periodSer);
    datasets.push({
      label: t.short, role: tid === "4_tactical" ? "headline" : "series",
      data: rebased.map(r => ({x:r.date, y:r.nav})),
      borderColor: CC.tier[tid],
      backgroundColor: CHARTS.alpha(CC.tier[tid], 0.13),
      tension: 0.05,
    });
  });
  // SPY benchmark
  const spy = applyPeriod(allSeries.bench.spy, period);
  if (spy.length > 0){
    const reb = rebase(spy);
    datasets.push({
      label: "SPY", role: "benchmark",
      data: reb.map(r => ({x:r.date, y:r.nav})),
      borderColor: CC.bench.spy, backgroundColor: "transparent",
      borderDash: [4, 3], tension: 0.05,
    });
  }
  S.chart = CHARTS.make(ctx, {
    type: "line", data: {datasets},
    options: {
      scales: {
        x: { type:"time",
             time:{ unit: period==="1M"||period==="3M"?"week":(period==="6M"||period==="YTD"||period==="1Y"?"month":"year") } },
        y: { type:"logarithmic", ticks:{callback: v => v.toFixed(2)} },
      },
      plugins: {
        tooltip:{callbacks:{ label: ctx => ` ${ctx.dataset.label}: ${ctx.parsed.y.toFixed(3)}× (${((ctx.parsed.y-1)*100>=0?"+":"")}${((ctx.parsed.y-1)*100).toFixed(1)}%)` }},
      },
    },
  });
}

// -------- Ticker drill-down --------
function renderTickerChart(tk){
  const tdata = S.tickers[tk];
  if (!tdata || !tdata.chart) return;
  const period = S.tickerChartPeriod;
  const days = {"3M":63, "6M":126, "1Y":252}[period] || 126;
  const chart = tdata.chart.slice(-days);
  const ctx = document.getElementById("ticker-chart");
  if (!ctx) return;
  if (S.tickerChart) S.tickerChart.destroy();

  // Pull annotation lines from ticker_signals.json (branch on mode)
  const sig = S.signals && S.signals.signals && S.signals.signals[tk];
  const CT = CHARTS.colors();
  const hline = (yval, color, label, dash=[4,4]) => ({
    type: "line", yMin: yval, yMax: yval,
    borderColor: color, borderWidth: 1, borderDash: dash,
    label: { content: label, display: true, position: "start",
             font: {family: CHARTS.tok("mono"), size: CHARTS.px("t1")},
             color: color, backgroundColor: "transparent" },
  });
  const annotations = {};
  if (sig && sig.mode === "position") {
    if (sig.position?.cost_basis)  annotations.cost  = hline(sig.position.cost_basis, CT.info, `Cost $${sig.position.cost_basis.toFixed(2)}`);
    if (sig.stops?.active_stop)    annotations.stop  = hline(sig.stops.active_stop,   CT.neg, `${sig.stops.active_stop_type === "trailing" ? "Trail" : "Stop"} $${sig.stops.active_stop.toFixed(2)}`);
    if (sig.trim?.trigger_price)   annotations.trim  = hline(sig.trim.trigger_price,  CT.warn, `Trim ${sig.trim.trim_pct}% at $${sig.trim.trigger_price.toFixed(2)}`, [2,4]);
    if (sig.hedge?.type === "covered_call" && sig.hedge.strike) {
      annotations.cc = hline(sig.hedge.strike, CT.n1, `CC $${sig.hedge.strike}`, [3,3]);
    }
  } else if (sig) {
    if (sig.entry?.primary)  annotations.entry  = hline(sig.entry.primary,  CT.info, `Entry $${sig.entry.primary.toFixed(2)}`);
    if (sig.stop?.price)     annotations.stop   = hline(sig.stop.price,     CT.neg, `Stop $${sig.stop.price.toFixed(2)}`);
    if (sig.target?.base)    annotations.target = hline(sig.target.base,    CT.pos, `Target $${sig.target.base.toFixed(2)}`);
  }

  S.tickerChart = CHARTS.make(ctx, {
    type: "line",
    data: {
      datasets: [
        {label:"Price",  role:"headline",  data: chart.map(c => ({x:c.d, y:c.c})),  borderColor:CT.info},
        {label:"MA50",   role:"benchmark", data: chart.map(c => ({x:c.d, y:c.m50})), borderColor:CT.warn, borderDash:[3,2]},
        {label:"MA200",  role:"benchmark", data: chart.map(c => ({x:c.d, y:c.m200})),borderColor:CT.n2,   borderDash:[3,2]},
      ],
    },
    options: {
      scales: {
        x: {type:"time", time:{unit: period==="3M"?"week":"month"}},
        y: {ticks:{callback: v => "$"+v.toFixed(0)}},
      },
      plugins: {
        tooltip:{callbacks:{ label: ctx => ` ${ctx.dataset.label}: $${ctx.parsed.y.toFixed(2)}` }},
        annotation: {annotations},
      },
    },
  });
}

// ──────────────────────────────────────────────────────────────────────
// Two-Score system: Business Quality (0-50) vs Trade Now (0-100).
// They answer DIFFERENT questions; the divergence between them is the
// actionable insight (great business + bad entry = pullback watch-list).
// Used by the detail header and the universe scanner list.
// ──────────────────────────────────────────────────────────────────────
function qualityColor(q){          // 0-50 scale
  if (q >= 38) return "#4ade80";
  if (q >= 25) return "#facc15";
  return "#f87171";
}
function tradeColor(t){            // 0-100 scale
  if (t >= 70) return "#4ade80";
  if (t >= 40) return "#facc15";
  return "#f87171";
}
function divergenceState(quality, qPct, trade, sig){
  // Signal-aware short-circuits: a SELL or position-management signal must
  // never get flagged as "↗ momo (momentum trade)" — the strength score in
  // those modes means "definitely act," not "good entry." Buy quadrants only
  // apply when the signal is actually BUY or STRONG BUY.
  const S = (sig || "").toUpperCase();
  if (arguments.length > 4 && arguments[4] === "position") {   // 16-Sept 1.7: observations, no quadrant
    const st = arguments[5] || "";
    if (st === "below_stop_from_cost" || st === "thesis_flags") return {cls:"exit", color:"#f87171", icon:"▽", text:"Below the rulebook stop from cost (observation)."};
    if (st === "below_trailing_level") return {cls:"trim", color:"#facc15", icon:"◇", text:"Below the trailing level (observation)."};
    if (st === "past_trim_level") return {cls:"trim", color:"#facc15", icon:"◆", text:"Past a trim level of the schedule (observation)."};
    if (st === "hedge_condition") return {cls:"hedge", color:"#a78bfa", icon:"◈", text:"Hedge condition of the rulebook met (observation)."};
    if (st === "insufficient_history" || st === "no_price_history") return {cls:"hold", color:"#737373", icon:"·", text:"No signal — insufficient history."};
    return {cls:"hold", color:"#737373", icon:"○", text:"Within the rulebook's levels."};
  }
  if (S.startsWith("SELL"))            return {cls:"exit",   color:"#f87171", icon:"▼",
                                                text:"Caution flags of the rulebook (observation)."};
  if (S.startsWith("TRIM"))            return {cls:"trim",   color:"#facc15", icon:"✂",
                                                text:"Past a trim level of the schedule (observation)."};
  if (S.includes("HEDGE"))             return {cls:"hedge",  color:"#a78bfa", icon:"🛡",
                                                text:"Hedge condition of the rulebook met (observation)."};
  if (S.includes("MONITOR"))           return {cls:"monitor",color:"#94a3b8", icon:"—",
                                                text:"Several yellow flags (observation)."};
  if (S.startsWith("HOLD"))            return {cls:"hold",   color:"#737373", icon:"—",
                                                text:"Few rulebook setup conditions met."};
  if (S.startsWith("WAIT") || S.startsWith("WATCH"))
                                       return {cls:"wait",   color:"#facc15", icon:"⏸",
                                                text:"Extended above its mean-reversion reference (not an entry signal)."};
  // BUY / STRONG BUY → 4-quadrant divergence
  const hiQ = quality >= 38;
  const hiT = trade >= 70;
  if ( hiQ &&  hiT) return {cls:"clean", color:"#4ade80", icon:"★",
                            text:"High quality score and the rulebook's setup conditions met (descriptive; not an entry signal: the entry state reads timing)."};
  if ( hiQ && !hiT) return {cls:"watch", color:"#facc15", icon:"⚠",
                            text:"High quality score; the rulebook's setup conditions not met."};
  if (!hiQ &&  hiT) return {cls:"momo",  color:"#60a5fa", icon:"↗",
                            text:"Setup conditions met on a middling quality score (not an entry signal)."};
  return                    {cls:"avoid", color:"#737373", icon:"·",
                            text:"Neither the quality score nor the setup conditions."};
}
function tradeContext(s){
  // One short phrase that summarises the trade-now reading using existing data.
  if (!s) return "";
  if (s.mode === "position"){
    return s.observation || "";
  }
  const d = s.data || {};
  const bits = [];
  if (d.rsi != null) {
    if (d.rsi < 35) bits.push(`RSI ${d.rsi.toFixed(0)} (oversold)`);
    else if (d.rsi > 65) bits.push(`RSI ${d.rsi.toFixed(0)} (overbought)`);
    else bits.push(`RSI ${d.rsi.toFixed(0)}`);
  }
  if (s.extended) bits.push("extended");
  if (d.ma200_dist != null && Math.abs(d.ma200_dist) < 5) bits.push("at 200-DMA");
  return bits.join(" · ");
}
// ── Order 2-Oct-2026 [E2], rules version 3 (6-Oct-2026, revised): the entry state on every stock card ──
// A rule output (trend gate → size modifiers → ceiling cap; a defined stop and a risk-budget size), shown
// DIAGNOSTIC until the registered validation reports. Entry timing is information only (no WAIT state).
// It states what the rule reads, not an instruction.
const esD2 = v => v == null ? "—" : Number(v).toFixed(2);
const esPct = (v, d) => v == null ? "—" : (v * 100).toFixed(d == null ? 1 : d) + "%";
const ENTRY_CLS = {AVOID: "c-neg", WATCH: "c-warn", READY: "c-pos", "READY-HALF": "c-pos"};
function entryRec(tk){ return (S.entryState && S.entryState.names && S.entryState.names[String(tk).toUpperCase()]) || null; }
function entryLabel(){ return (S.entryState && S.entryState.label) || "DIAGNOSTIC"; }
// Order 6-Oct-2026 (rules version 3): the flags a card carries, each of which can change a state, a size or an exit.
function entryFlags(e){
  const out = [];
  if (!e) return out;
  if (e.trend && e.trend.below_200d && e.trend.pass) out.push({k: "below_200d", cls: "c-warn", t: "below the 200-day average", tip: `close $${esD2(e.close)} under the 200-day $${esD2(e.trend.ma200)} with 12-month momentum ${esPct(e.trend.mom_12_1)}: size halved`});
  if (e.ceiling_flag) { const c = (e.long_range || {}).ceiling || {}; out.push({k: "ceiling", cls: "c-warn", t: `ceiling $${esD2(c.level)}`, tip: `a multi-year ceiling ${esPct(-(e.long_range || {}).dist_ceiling)} above the close caps the state at WATCH until a close above it`}); }
  if (e.heavily_shorted) { const s = e.short_interest || {}; out.push({k: "shorted", cls: "c-warn", t: "heavily shorted", tip: `days-to-cover ${s.days_to_cover != null ? s.days_to_cover : "—"} · short interest ${s.short_pct_float != null ? (s.short_pct_float * 100).toFixed(1) + "% of the float" : "—"} (set by ${(e.heavily_shorted_by || []).join(" and ") || "—"}; 7 days or 20% of the float): size halved`}); }
  const ec = e.earnings || {};
  if (ec.conflict) out.push({k: "earn_conflict", cls: "c-warn", t: "earnings date conflict", tip: ec.conflict_text || "sources disagree on the next earnings date"});
  if ((e.provider_flags || []).length) out.push({k: "provider", cls: "c-neg", t: "provider data suspect", tip: e.provider_flags.map(f => `${f.field}: ${f.reason}`).join("; ")});
  return out;
}
function entryBadge(tk){
  const e = entryRec(tk);
  if (!e || !e.state) return `<span class="es-badge c-3" title="${escText30((e && e.reason) || "no entry state computed")}">—</span>`;
  const fl = entryFlags(e).map(f => f.t).join(" · ");
  const tip = `${e.state} · stop $${esD2(e.stop)}${e.size_factor != null && e.size_factor < 1 ? " · size ×" + e.size_factor : ""}${fl ? " · " + fl : ""} · ${entryLabel()}`;
  return `<span class="es-badge ${ENTRY_CLS[e.state] || "c-3"}" title="${escText30(tip)}">${e.state}</span>`;
}
function entryEarnText(e){
  if (!e) return "—";
  const ec = e.earnings || {};
  const base = e.sessions_to_earnings == null ? (e.earnings_known ? "no earnings date ahead" : "earnings date unknown")
    : `earnings in ${e.sessions_to_earnings} session${e.sessions_to_earnings === 1 ? "" : "s"} (${e.next_earnings}${ec.time_of_day ? ", " + String(ec.time_of_day).replace("_", " ") : ""})`;
  return base + (ec.decided_by ? ` · date from ${escText30(ec.decided_by)}` : "") + (ec.conflict ? ` · <span class="c-warn">conflict: ${escText30(ec.conflict_text || "")}</span>` : "");
}
function entrySizeText(e){
  const z = e && e.size;
  if (!z) return "—";
  if (z.shares == null) return escText30(z.reason || "no entry defined");
  const mods = (e.modifiers || []).map(m => m.name.replace("_", " ") + " ×½").join(", ");
  return `${z.shares} shares (≈${fmtMoney(z.value)}) · risk ${fmtMoney(z.risk_dollars)} = ${(z.risk_budget * 100).toFixed(3).replace(/0+$/, "")}% of ${fmtMoney(z.account_value)}` +
    (mods ? ` · ${mods} → ${z.size_factor === 0.25 ? "a quarter" : z.size_factor === 0.5 ? "half" : "×" + z.size_factor} of the base ${z.base_shares} shares` : "") + (z.capped_by ? " · capped by " + z.capped_by : "");
}
function entryStateText(e){
  if (!e || !e.state) return "—";
  const t = e.trend || {};
  if (e.state === "AVOID") return `trend gate fails: close $${esD2(e.close)} below the 200-day $${esD2(t.ma200)} and 12-month momentum ${esPct(t.mom_12_1)}`;
  if (e.state === "WATCH") return escText30(e.watch_reason || "watch");
  return "a passing trend gate (extended or pulling back alike)" + (e.state === "READY-HALF" ? " · earnings within 20 sessions: half size" : "");
}
function renderEntryState(tk){
  const e = entryRec(tk);
  if (!e) return "";
  if (!e.state) return `<div class="es-block mono t1 c-3">ENTRY STATE — ${escText30(e.reason || "not computed")}</div>`;
  const set = e.setup || {}, t = e.trend || {}, cf = e.confirmation || {}, lr = e.long_range, si = e.short_interest;
  const sgn = v => v == null ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(2);
  const setupTxt = `close ${sgn(set.dist_ma20_atr)} ATR from the 20-day average $${esD2(e.ma20)} · RSI(14) ${set.rsi != null ? set.rsi : "—"} · ${set.range_pos != null ? Math.round(set.range_pos * 100) + "% of the way up" : "—"} the 40-session range ($${esD2(e.range_lo)}–$${esD2(e.range_hi)})`;
  const z = e.size || {}; const a = z.book_after || {}, b = z.book_before || {};
  const noEntry = !String(e.state).startsWith("READY");
  const flags = entryFlags(e).map(f => `<span class="es-badge ${f.cls}" title="${escText30(f.tip)}">${f.t}</span>`).join(" ");
  const eff = (z.shares && a.vol_nav_ann != null) ? `<div class="c-3">after entry: book volatility ${esPct(b.vol_nav_ann)} → ${esPct(a.vol_nav_ann)} · beta ${b.beta_spy != null ? b.beta_spy.toFixed(2) : "—"} → ${a.beta_spy != null ? a.beta_spy.toFixed(2) : "—"} · largest risk share ${a.largest_risk_name || "—"} ${esPct(a.largest_risk_share)} (this name ${esPct(a.risk_share_name)})</div>` : "";
  const conf = `confirmation (information, not required): ${cf.close_above_prior_high ? `closed above the prior high $${esD2(cf.prior_high)}` : `no close above the prior high $${esD2(cf.prior_high)}`}${cf.failed_breakdown_recovered ? " · failed breakdown recovered" : ""} · volume ${cf.volume_ratio != null ? cf.volume_ratio.toFixed(2) + "× the 50-day average" + (cf.volume_confirms ? " (above 1.5×)" : "") : "—"}`;
  const ceil = lr && lr.ceiling ? lr.ceiling : null;
  const longTxt = lr ? `long range: 5-year closing high $${esD2(lr.high_5y)} (${lr.high_5y_date || "—"}, ${esPct(-lr.dist_5y)} above) · all-time closing high $${esD2(lr.ath)} (${lr.ath_date || "—"}, ${esPct(-lr.dist_ath)} above)` +
    (ceil ? ` · ceiling $${esD2(ceil.level)} (${(ceil.pair || []).map(p => `${p.date.slice(0, 7)} $${esD2(p.close)}, then ${esPct(p.decline)}`).join("; ")})${e.ceiling_flag ? ` <span class="c-warn">· within 15% below: state capped at WATCH</span>` : ""}` : " · no multi-year ceiling") : "";
  const siTxt = si ? `days to cover ${si.days_to_cover != null ? si.days_to_cover : "—"} · short interest ${si.short_pct_float != null ? (si.short_pct_float * 100).toFixed(1) + "% of the float" : "— of the float"}${si.change_vs_prior_month != null ? ` · ${si.change_vs_prior_month >= 0 ? "+" : ""}${(si.change_vs_prior_month * 100).toFixed(1)}% vs the prior month` : ""}${si.as_of ? ` (as of ${si.as_of})` : ""}${e.heavily_shorted ? ` <span class="c-warn">· heavily shorted (${escText30((e.heavily_shorted_by || []).join(" and "))})${e.state === "AVOID" ? "" : ": size halved"}</span>` : ""}` : "days to cover — · short interest —";
  const pf = (e.provider_flags || []).length ? `<div class="c-neg">provider data suspect: ${e.provider_flags.map(f => escText30(`${f.field} (${f.reason})`)).join("; ")}</div>` : "";
  // 7-Oct-2026 order (task C): the 30-day consensus-revision variables from the repository's own snapshots, shown
  // once 30 days of snapshots exist, DIAGNOSTIC and in no score until 12 months and the registered test
  const AR = S.analystRev, ar = AR && AR.names && AR.names[tk];
  const pct1 = v => v == null ? "—" : (v >= 0 ? "+" : "") + (v * 100).toFixed(1) + "%";
  const arTxt = ar && (ar.an_eps_rev_30 != null || ar.an_eps_breadth_30 != null || ar.an_rev_rev_30 != null)
    ? `<div class="c-3">analyst revisions, 30 days <span class="mono t1 w6 r1 x2 c-warn ls06">${escText30(AR.label || "DIAGNOSTIC")}</span> (information, in no score): consensus EPS for the fiscal year ${pct1(ar.an_eps_rev_30)} · breadth ${ar.an_eps_breadth_30 == null ? "—" : (ar.an_eps_breadth_30 >= 0 ? "+" : "") + ar.an_eps_breadth_30.toFixed(2)} of ${ar.analysts || "—"} analysts · revenue ${pct1(ar.an_rev_rev_30)} · against the snapshot of ${ar.base_snapshot || "—"}${ar.note ? " · " + escText30(ar.note) : ""}</div>` : "";
  return `<div class="es-block mono t1 lh16">
    <div><span class="c-3 w6 ls08">ENTRY STATE</span> <span class="es-badge ${ENTRY_CLS[e.state] || "c-3"} w7">${e.state}</span> <span class="mono t1 w6 r1 x2 c-warn ls06">${entryLabel()}</span> <span class="c-3">· as of ${e.date} · close $${esD2(e.close)}</span> ${flags}</div>
    ${S.entryState && S.entryState.validation ? `<div class="c-3">validation: ${escText30(S.entryState.validation.summary || S.entryState.validation.verdict || "")}</div>` : ""}
    <div class="c-2">${entryStateText(e)}</div>
    <div class="c-3">trend gate ${t.pass ? "passes" : "fails"} (12-1 return ${esPct(t.mom_12_1)}; 200-day $${esD2(t.ma200)}${t.below_200d ? ", close below it" : ", close above it"})</div>
    <div class="${noEntry ? "c-3" : "c-2"}">${noEntry ? "stop level (no entry at " + e.state + "; shown for reference)" : "stop"} $${esD2(e.stop)} <span class="c-3">(40-session low $${esD2(e.range_lo)} less 1 ATR $${esD2(e.atr)})</span></div>
    <div class="c-2">size at the default risk budget: ${entrySizeText(e)}</div>
    ${eff}
    <div class="${e.sessions_to_earnings != null && e.sessions_to_earnings <= 20 ? "c-warn" : "c-3"}">${entryEarnText(e)}</div>
    <div class="c-3">${siTxt}</div>
    ${longTxt ? `<div class="c-3">${longTxt}</div>` : ""}
    ${pf}
    ${arTxt}
    <details class="mt1"><summary class="mono t1 c-3 ptr ls05">entry timing (information: none of these changes a state, a size or an exit)</summary>
      <div class="c-3 mt1">setup measures: ${setupTxt}</div>
      <div class="c-3">${conf}</div>
    </details>
  </div>`;
}

// Order 6-Oct-2026: names the operator's orders discuss that are neither held, in a tier nor on the board get a
// full card here (data/review_names.json): the entry state with its flags and the provider-checked fundamentals.
function providerFieldsGrid(tk){
  const P = (S.providerFlags && S.providerFlags.names && S.providerFlags.names[tk]) || null;
  if (!P) return `<div class="mono t1 c-3">no provider record</div>`;
  const f = P.fields || {}, fl = {}; (P.flags || []).forEach(x => { fl[x.field] = x; });
  const num = (v, d) => v == null ? "—" : Number(v).toFixed(d == null ? 1 : d);
  const bn = v => v == null ? "—" : (v < 0 ? "−" : "") + "$" + (Math.abs(v) >= 1e9 ? (Math.abs(v) / 1e9).toFixed(2) + "B" : (Math.abs(v) / 1e6).toFixed(0) + "M");
  const cell = (label, field, txt) => fl[field]
    ? `<div class="fund-card suspect" title="${escText30("provider data suspect: " + fl[field].reason + " · excluded from the screen's scores until the next filing clears it")}"><div class="k">${label} <span class="c-neg">?</span></div><div class="v c-3"><s>${txt}</s></div><div class="t1 c-3 lh14">${escText30(fl[field].reason)}</div></div>`
    : `<div class="fund-card"><div class="k">${label}</div><div class="v">${txt}</div></div>`;
  return `<div class="fund-grid">${cell("FWD P/E", "forwardPE", num(f.forwardPE))}${cell("TRAIL P/E", "trailingPE", num(f.trailingPE))}${cell("FCF", "freeCashflow", bn(f.freeCashflow))}${cell("OP CASH FLOW", "operatingCashflow", bn(f.operatingCashflow))}${cell("REV GROWTH", "revenueGrowth", f.revenueGrowth == null ? "—" : (f.revenueGrowth * 100).toFixed(1) + "%")}</div>`;
}
function renderReviewNames(){
  const R = S.reviewNames; if (!R || !(R.names || []).length) return "";
  const cards = R.names.map(r => {
    const tk = String(r.ticker).toUpperCase();
    const nm = (((S.providerFlags || {}).names || {})[tk] || {}).fields || {};
    return `<div class="rcc-card"><h3>${tk} <span class="c-3 w5">· ${escText30(nm.shortName || "")} · ${escText30(r.why || "")}</span></h3>
      ${renderEntryState(tk)}
      <div class="mono t1 w6 c-3 ls18 mt2 mb2">FUNDAMENTALS · provider fields checked nightly (a flagged field is greyed and left out of the screen's scores)</div>
      ${providerFieldsGrid(tk)}</div>`;
  }).join("");
  return `<div class="mono t1 c-3 mb2">${escText30(R.note || "")}</div>${cards}`;
}

// Order 6-Oct-2026 (revised), section 6b: the operator's individual-stock picks against a QQQ shadow (same dollars
// in and out on the same dates), with the algorithmic tiers on the same terms. Descriptive; the number of
// independent decisions (distinct entry dates) sits beside every figure.
function renderPicksVsQQQ(){
  const P = S.picksQQQ; if (!P || !(P.windows || []).length) return "";
  const usd = v => v == null ? "—" : (v < 0 ? "−" : "+") + "$" + Math.abs(v).toLocaleString("en-US", {maximumFractionDigits: 0});
  const pct = v => v == null ? "—" : (v < 0 ? "−" : "+") + Math.abs(v * 100).toFixed(2) + "%";
  const nn = n => ` <span class="c-3 t1 nowrap" title="independent decisions: distinct entry dates">n=${n}</span>`;
  const cls = v => v == null ? "c-3" : v >= 0 ? "c-pos" : "c-neg";
  const minN = P.min_decisions || 30;
  const row = (w, label, x) => {
    const m = x.summary || {}; const n = m.decisions;
    const closed = m.closed ? `${m.closed_beat} of ${m.closed} (${Math.round((m.closed_beat_share || 0) * 100)}%)${nn(m.closed_decisions)}` : `no closed position${nn(0)}`;
    return `<tr><td class="c-1 w6">${label}</td><td class="c-3 t1">${w.label}</td>
      <td class="num ${cls(m.diff_usd)}">${usd(m.diff_usd)}${nn(n)}</td><td class="num ${cls(m.diff_pct)}">${pct(m.diff_pct)}${nn(n)}</td>
      <td class="num ${cls(m.riskadj_usd)}">${usd(m.riskadj_usd)} <span class="c-3">(${pct(m.riskadj_pct)})</span>${nn(n)}</td>
      <td class="num">${closed}</td><td class="num c-3">${m.positions} · $${Math.round(m.dollars_in || 0).toLocaleString("en-US")}${nn(n)}</td></tr>`;
  };
  const ws = P.windows.filter(w => w.operator);
  const rows = ws.map(w => row(w, "Operator", w.operator) + row(w, "Algorithmic tiers", w.algorithmic)).join("");
  const nOp = Math.max(0, ...ws.map(w => w.operator.summary.decisions || 0));
  const nAl = Math.max(0, ...ws.map(w => w.algorithmic.summary.decisions || 0));
  const winLines = ws.map(w => `${w.label}: from the close of ${w.opening_close} to ${w.as_of} (${w.sessions} sessions), QQQ ${pct(w.qqq_return)}`).join(" · ");
  const posRows = ws.map(w => (w.operator.positions || []).map(x => `<tr><td class="c-1 w6">${x.ticker}</td><td class="c-3 t1">${w.label}</td>
      <td class="t1 c-3">${escText30(x.entry_basis)}</td><td class="t1 c-3">${x.start} → ${x.end}${x.closed ? " (closed)" : ""}</td>
      <td class="num">$${Math.round(x.dollars_in).toLocaleString("en-US")}</td><td class="num ${cls(x.pnl_usd)}">${usd(x.pnl_usd)}</td><td class="num ${cls(x.shadow_pnl_usd)}">${usd(x.shadow_pnl_usd)}</td>
      <td class="num ${cls(x.diff_usd)}">${usd(x.diff_usd)}</td><td class="num c-3" title="${escText30(x.beta_basis)}">${x.beta}</td><td class="num ${cls(x.riskadj_usd)}">${usd(x.riskadj_usd)}</td></tr>`).join("")).join("");
  const bad = ws.flatMap(w => (w.operator.not_measurable || []).map(b => `${b.ticker} (${w.label}): ${escText30(b.reason)}`));
  const badU = [...new Set(bad)];
  const excl = [...new Set(ws.flatMap(w => [...(w.operator.excluded || []), ...Object.values(w.algorithmic.tiers || {}).flatMap(t => t.excluded || [])]).map(e => `${e.ticker} (${e.category})`))];
  const tierRows = ws.map(w => Object.entries(w.algorithmic.tiers || {}).map(([tid, t]) => { const m = t.summary || {}; const sp = tierSpec(tid) || {};
      return `<tr><td class="${cc(sp.color)} w6">${sp.short || tid}</td><td class="c-3 t1">${w.label}</td><td class="num ${cls(m.diff_usd)}">${usd(m.diff_usd)}${nn(m.decisions)}</td><td class="num ${cls(m.diff_pct)}">${pct(m.diff_pct)}${nn(m.decisions)}</td><td class="num ${cls(m.riskadj_usd)}">${usd(m.riskadj_usd)}${nn(m.decisions)}</td><td class="num">${m.closed ? `${m.closed_beat} of ${m.closed}` : "none"}${nn(m.closed_decisions || 0)}</td><td class="num c-3">${m.positions}</td></tr>`; }).join("")).join("");
  const D = P.definitions || {};
  return `<div class="rcc-card"><h3>PICKS AGAINST QQQ · <span class="c-3 w5">the operator's individual-stock positions against a shadow that puts the same dollars into QQQ on the same dates and takes them out on the same dates · the algorithmic tiers on the same terms · ${P.label || "DESCRIPTIVE"}</span>${asOfBadge(P.as_of)}</h3>
    <div class="mono t2 c-warn w6 mb2">${escText30(P.skill_note || "")} Operator: ${nOp} independent decision${nOp === 1 ? "" : "s"}; the algorithmic tiers: ${nAl}${nOp < minN || nAl < minN ? " — both below " + minN + "." : "."}</div>
    <div class="tbl-scroll"><table class="th-table stack-m"><tr><th>BOOK</th><th>WINDOW</th><th class="num">DIFFERENCE $</th><th class="num">DIFFERENCE %</th><th class="num">RISK-ADJUSTED $</th><th class="num">CLOSED THAT BEAT QQQ</th><th class="num">POSITIONS · DOLLARS IN</th></tr>${rows}</table></div>
    <div class="chart-meta">${winLines} · n = independent decisions (distinct entry dates) behind each figure · index funds, sector funds and gold left out${excl.length ? ": " + excl.join(", ") : " (none held in the windows)"}</div>
    <div class="mono t1 c-3 mt1">${escText30(P.data_basis || "")}</div>
    ${badU.length ? `<div class="mono t1 c-warn mt1">not measurable from the log (in no figure): ${badU.join(" · ")}</div>` : ""}
    <details class="mt2"><summary class="mono t1 c-3 ptr ls05">the operator's positions, one by one</summary>
      <div class="tbl-scroll"><table class="th-table stack-m"><tr><th>TICKER</th><th>WINDOW</th><th>ENTRY (HOW DATED)</th><th>MEASURED</th><th class="num">DOLLARS IN</th><th class="num">POSITION P&amp;L</th><th class="num">QQQ SHADOW P&amp;L</th><th class="num">DIFFERENCE</th><th class="num">BETA</th><th class="num">RISK-ADJ.</th></tr>${posRows}</table></div></details>
    <details class="mt1"><summary class="mono t1 c-3 ptr ls05">the algorithmic tiers, one by one</summary>
      <div class="tbl-scroll"><table class="th-table stack-m"><tr><th>TIER</th><th>WINDOW</th><th class="num">DIFFERENCE $</th><th class="num">DIFFERENCE %</th><th class="num">RISK-ADJUSTED $</th><th class="num">CLOSED THAT BEAT QQQ</th><th class="num">POSITIONS</th></tr>${tierRows}</table></div>
      <div class="mono t1 c-3 mt1">${escText30((ws[0] && ws[0].algorithmic.pooling) || "")}</div></details>
    <details class="mt1"><summary class="mono t1 c-3 ptr ls05">definitions</summary><div class="mono t1 c-3 mt1 lh17">${Object.entries(D).map(([k, v]) => `<div><span class="c-2">${k.replace(/_/g, " ")}</span>: ${escText30(v)}</div>`).join("")}<div><span class="c-2">beta</span>: ${escText30(P.beta_rule || "")}</div><div><span class="c-2">exclusions</span>: ${escText30(P.exclusion_rule || "")}</div></div></details>
  </div>`;
}

// ── Options lens (order 26-Sept-2026, Phase 3): the third column of every stock card ──
// What the options market prices about the name and, for held names, the structure the
// hedge selector ranks first. Descriptive; no directional implication anywhere.
function optLens(tk){ return (S.optionsLens && S.optionsLens.names && S.optionsLens.names[tk]) || null; }
function optPct(x, d){ return x == null ? "—" : (x * 100).toFixed(d == null ? 1 : d) + "%"; }
const OPT_STATE_CLS = {cheap:"c-pos", rich:"c-warn", mixed:"c-2"};
const OPT_GLYPH = {cheap:"◯", rich:"●", mixed:"◐"};   // hollow = cheap, filled = rich, half = mixed
function optEventText(o){
  const e = o && o.event; if (!e) return "";
  if (!e.next_earnings) return "no earnings date listed";
  const h = e.history || {}; const l8 = h.last8 || {};
  const when = e.days_to == null ? "" : e.days_to < 0 ? " (past)" : ` (${e.days_to}d, ${e.sessions_to} sessions)`;
  const parts = [`earnings ${e.next_earnings}${when}`];
  parts.push(e.implied_move != null ? `market prices ±${optPct(e.implied_move)}${e.expiry_after ? " from the " + e.expiry_after + " expiry" : ""}` : `implied move n/a${e.implied_move_reason ? " (" + e.implied_move_reason + ")" : ""}`);
  if (h.median_abs != null) parts.push(`median past reaction ${optPct(h.median_abs)} over ${h.n}`);
  if (h.n_exceeding_implied != null) parts.push(`${h.n_exceeding_implied} of ${h.n} exceeded`);
  if (l8.n_exceeding_implied != null) parts.push(`${l8.n_exceeding_implied} of last ${l8.n} exceeded`);
  return parts.join("; ");
}
// Order 6-Oct-2026, section 6: the main view shows a field only if it can change a state, a size or an exit.
// Of the options lens that is the earnings line (an earnings release within 20 sessions halves the size); the
// rest is descriptive and sits in one collapsed drawer: the volatility state, term structure, skew, the past
// reactions with their release timing, the hedge structure, dealer gamma and max pain.
function optReactionsText(tk){
  const R = (S.earningsRx && S.earningsRx.names && S.earningsRx.names[tk]) || null;
  const h = (R && R.history) || [];
  if (!h.length) return "";
  const rows = h.slice(-9).map(x => `${x.date.slice(0, 7)} ${x.time_of_day === "after_close" ? "after close" : "before open"} <span class="${x.reaction >= 0 ? "c-pos" : "c-neg"}">${x.reaction >= 0 ? "+" : ""}${(x.reaction * 100).toFixed(1)}%</span>`).join(" · ");
  return `<div class="mono t1 c-3 mt1">past reactions (before open: prior close to the release-day close; after close: the release-day close to the next close; timing from the 8-K filing or the provider's stamp): ${rows}</div>`;
}
function optionsRowHtml(tk, isPos){
  const o = optLens(tk);
  if (!o) return `<div class="ts-row"><div class="ts-label">Options</div><div class="ts-sub c-3">no chain vintage for this name</div><div class="ts-val"><span class="c-3">—</span></div><div class="ts-sub"></div></div>`;
  const v = o.volatility || {}, t = o.term_structure || {}, sk = o.skew || {}, g = o.dealer_gamma || {}, ps = o.positioning || {};
  const pill = o.impaired ? `<span class="c-warn w6" title="fewer than 70% of front-expiry strikes carry live bid-ask quotes">IMPAIRED</span>`
                          : `<span class="${OPT_STATE_CLS[v.state] || "c-3"} w6">${OPT_GLYPH[v.state] || ""} ${(v.state || "—").toUpperCase()}</span>`;
  const ivLine = `IV30 <span class="c-1">${optPct(v.iv30)}</span> · RV21 ${optPct(v.rv21)} · RV63 ${optPct(v.rv63)}${t.inverted ? ` · <span class="c-warn">term inverted</span>${t.reason ? ` <span class="c-3">(${t.reason})</span>` : ""}` : ""}`;
  const skewLine = sk.skew != null ? `skew ${(sk.skew * 100).toFixed(1)} pts (10% OTM put − call IV${sk.rr25 != null ? `; 25Δ RR ${(sk.rr25 * 100).toFixed(1)}` : ""})` : "skew n/a";
  let hedge = "";
  const hp = isPos && S.optionsHedges && S.optionsHedges.positions && S.optionsHedges.positions[tk];
  if (hp && hp.tenors && hp.tenors.length){
    const ten = hp.tenors[0]; const top = (ten.structures || []).find(s => s.rank === 1);
    if (top) hedge = `<div class="mono t1 c-3 mt1">hedge structure ranked first, ${ten.expiry} (${ten.tenor.replace("_", " ")}): <span class="c-2">${top.label}</span>, ${top.net_kind} $${Math.abs(top.net_per_share).toFixed(2)}/sh (${fmtMoney(Math.abs(top.net_on_position))} on the position) · <span class="c-warn">${S.optionsHedges.label}</span></div>`;
  }
  const drawer = `<details class="mt1 opt-detail"><summary class="mono t1 c-3 ptr ls05">options detail (descriptive: none of these changes a state, a size or an exit)</summary>
      <div class="mono t1 c-3 mt1">volatility ${pill} · ${ivLine}</div>
      <div class="mono t1 c-3 mt1">${skewLine}</div>
      ${optReactionsText(tk)}
      ${hedge}
      <div class="mono t1 c-3 mt1">dealer gamma (assumption-flagged): net gamma per 1% move ${g.per_1pct != null ? fmtMoney(g.per_1pct) : "—"} · flip level ${g.flip_level != null ? "$" + g.flip_level : "—"} · convention: ${g.convention || "dealers long calls, short puts"}. ${g.caveat || ""}</div>
      <div class="mono t1 c-3 mt1">max pain ${ps.max_pain != null ? "$" + ps.max_pain : "—"}${ps.max_pain_vs_spot != null ? ` (${optPct(ps.max_pain_vs_spot)} vs spot)` : ""}${ps.expiry ? ` at the ${ps.expiry} expiry` : ""} · put/call open interest ${ps.put_call_oi_ratio != null ? ps.put_call_oi_ratio : "—"} · ${ps.note || "descriptive only"}</div>
    </details>`;
  return `<div class="ts-row">
      <div class="ts-label">Options</div>
      <div class="ts-sub">${optEventText(o)}${optionsAgeBadge(S.optionsLens && S.optionsLens.session_date)}</div>
      <div class="ts-val"></div>
      <div class="ts-sub"></div>
    </div>${drawer}`;
}
function optEventLine(tk){   // 3.3: the event line for held names when a release falls within 10 sessions
  const o = optLens(tk); const e = o && o.event;
  if (!e || !e.next_earnings || e.sessions_to == null || e.sessions_to < 0 || e.sessions_to > 10) return "";
  return `<div class="mono t1 c-warn mt1">◎ ${optEventText(o)}</div>`;
}
function twoScoreBar(value, max, color){
  const pct = Math.max(0, Math.min(100, value / max * 100));
  return `<div class="ts-bar">
    <div class="ts-bar-fill ${cc(color,'bg')}" style="width:${pct.toFixed(0)}%"></div>
  </div>`;
}
function renderTwoScore(tk){
  const s = S.signals && S.signals.signals && S.signals.signals[tk];
  if (!s) return "";
  const quality = (s.data && s.data.composite != null) ? +s.data.composite : 0;
  const qPct    = (s.data && s.data.composite_pct != null) ? +s.data.composite_pct : 0;
  const rank    = (s.data && s.data.rank != null) ? +s.data.rank : null;
  const isPos   = s.mode === "position";
  const trade   = isPos ? null : (s.trade_now_strength != null ? +s.trade_now_strength : +s.signal_strength);
  const sig     = s.signal || "—";
  const note    = s.trade_now_note;
  const div     = divergenceState(quality, qPct, trade, sig, s.mode, s.state);
  if (isPos) return `<div class="two-score">
    <div class="ts-row">
      <div class="ts-label">Business quality</div>
      ${twoScoreBar(quality, 50, qualityColor(quality))}
      <div class="ts-val">${quality.toFixed(1)}<span class="ts-of">/50</span></div>
      <div class="ts-sub">${qPct.toFixed(0)}th pct${rank === 1 ? " · #1 in universe" : rank ? " · rank #" + rank : ""}</div>
    </div>
    <div class="ts-row">
      <div class="ts-label">Position vs rulebook</div>
      <div class="ts-sub">${sig}</div>
      <div class="ts-val"><span class="${cc(div.color)}">${div.icon}</span> <span class="t1 c-3">no entry strength in position mode</span></div>
      <div class="ts-sub">${tradeContext(s)}</div>
    </div>
    ${optionsRowHtml(tk, true)}
    <div class="ts-divergence ${cc(div.color)} ${cc(div.color,'bl')}">${div.icon} ${div.text} <span class="c-3">· ${s.label || "mechanical rulebook; expectancy not validated"}</span></div>
  </div>`;

  return `<div class="two-score">
    <div class="ts-row">
      <div class="ts-label">Business quality</div>
      ${twoScoreBar(quality, 50, qualityColor(quality))}
      <div class="ts-val">${quality.toFixed(1)}<span class="ts-of">/50</span></div>
      <div class="ts-sub">${qPct.toFixed(0)}th pct${rank === 1 ? " · #1 in universe" : rank ? " · rank #" + rank : ""}</div>
    </div>
    <div class="ts-row">
      <div class="ts-label">Setup reading</div>
      ${twoScoreBar(trade, 100, tradeColor(trade))}
      <div class="ts-val"><span class="${cc(tradeColor(trade))}">${sig}</span> · ${trade}<span class="ts-of">/100</span></div>
      <div class="ts-sub">${note ? '<span class="c-warn">' + note + '</span>' : tradeContext(s)}</div>
    </div>
    ${optionsRowHtml(tk, false)}
    <div class="ts-divergence ${cc(div.color)} ${cc(div.color,'bl')}">
      ${div.icon} ${div.text}
    </div>
  </div>`;
}

// ──────────────────────────────────────────────────────────────────────
// REGIME & OVERLAY panel — VIX term-structure regime + spike attribution.
// CONDITIONING/uncertainty information only. NEVER renders a directional
// implication for any event marker. The overlay scalar is shown but
// gated as DIAGNOSTIC until backtest validation closes.
// ──────────────────────────────────────────────────────────────────────
function renderRegimeOverlayPanel(){
  const r = S.volRegime;
  if (!r) return "";

  // State + dynamics
  const dyn = (r.dynamics && r.dynamics[r.state]) || {};
  const nextTypical = (() => {
    const dist = dyn.next_state_distribution || {};
    const keys = Object.keys(dist);
    if (!keys.length) return null;
    const top = keys.reduce((a,b) => dist[a] > dist[b] ? a : b);
    const total = Object.values(dist).reduce((a,b) => a+b, 0);
    return { state: top, pct: Math.round(dist[top] / total * 100) };
  })();

  // Conditioning row
  const condRow = (k, v, on) => `<div class="rop-cond-row">
    <span class="k">${k}</span>
    <span class="v ${on === true ? 'on' : on === false ? 'off' : ''}">${v}</span>
  </div>`;

  // Attribution
  const driver = r.attribution.primary_driver;
  const reversion = r.attribution.primary_reversion;
  const equityDrag = r.attribution.equity_drag;
  const eqInputs = r.attribution.equity_drag_inputs || {};

  // Term curve mini-chart datasets
  const curve = r.curve || {};
  const curvePoints = [
    {tenor: "spot",   v: curve.spot_vix},
    curve.vix1d ? {tenor: "1d",    v: curve.vix1d} : null,
    {tenor: "3M",     v: curve.vix3m},
  ].filter(Boolean);

  // History strip
  const history = (r.history_recent || []).slice(-180);
  const stripCells = history.map(h => `<div class="cell" data-st="${h.state}" title="${h.d}: ${h.state} (${h.spread})"></div>`).join("");

  // Past event-day spikes for the "past spikes" list
  const pastSpikes = (r.past_spikes || []).slice().reverse().slice(0, 8);
  const spikeList = pastSpikes.map(s => `
    <div>${s.d} · <strong>${s.state}</strong> Δspread ${s.delta_spread >= 0 ? "+" : ""}${s.delta_spread}${s.event ? ' · ' + s.event : ''}</div>
  `).join("");

  // Overlay scalar
  const ovs = r.overlay_scalar || {};

  // RoP-FIX B1: two-horizon line — acute today vs reverts later. Pulls the
  // VIX1D event-vol point + intraday VIX move so the reader sees the
  // acute-now / calm-later split explicitly instead of having to
  // reconcile a benign 73% reversion stat with an obviously stressed
  // session.
  const vixId   = S.intraday || {};
  const vixChg  = (vixId.vix_change_pct != null && vixId.vix_now != null)
    ? `${vixId.vix_change_pct >= 0 ? "+" : ""}${vixId.vix_change_pct}%` : null;
  const vixNow  = vixId.vix_now != null ? vixId.vix_now : (r.curve && r.curve.spot_vix);
  const twoHorizonLine = (nextTypical && r.curve && r.curve.vix1d != null) ? `
    <div class="mt2 serif t1 it c-2 lh155 x20">
      <strong class="fs-n mono c-1 w6">Acute today:</strong>
      VIX1D <strong class="fs-n mono c-1">${r.curve.vix1d}</strong>,
      VIX <strong class="fs-n mono c-1">${vixNow}</strong>${vixChg ? ` (${vixChg})` : ""}
      — front-end event vol elevated.
      Term structure (spot−3M = <strong class="fs-n mono c-1">${r.spread >= 0 ? "+" : ""}${r.spread}</strong>)
      only mildly inverted; historically reverts to
      <strong class="fs-n c-1">${nextTypical.state}</strong>
      <strong class="fs-n mono c-1">${nextTypical.pct}%</strong> of the time.
    </div>` : "";

  // RoP-FIX B2: atypical-entry caveat
  const en = r.entry || {};
  const atypicalCaveat = en.atypical_entry ? `
    <div class="mt2 serif t1 it c-warn lh155 x21">
      <strong class="fs-n mono ls06">⚠ ENTERED VIA A
      ${en.current_entry_dspread >= 0 ? "+" : ""}${en.current_entry_dspread} SHOCK</strong>
      (z = <strong class="fs-n mono">${en.entry_zscore}</strong>σ of ${r.state} entries,
      vs typical ${en.state_mean_entry >= 0 ? "+" : ""}${en.state_mean_entry}).
      The reversion stat above pools mostly gentle entries and may not apply to a shock-entered state.
    </div>` : "";

  // Walk-forward validation — RoP-FIX 2: surface BOTH metrics with Wilson CI
  // and honest small-n caveat. Today is excluded from both.
  const wf  = (r.validation && r.validation.walk_forward) || {};
  const at  = wf.all_triggers_reversion || {};
  const ev  = wf.event_day_only_reversion || {};
  const fmtCI = m => (m.wilson_95ci ? `${Math.round(m.wilson_95ci[0]*100)}–${Math.round(m.wilson_95ci[1]*100)}%` : "—");
  const wfTextAll = at.hit_rate != null
    ? `${at.n_reverted}/${at.n} (${Math.round(at.hit_rate*100)}%) · 95% CI ${fmtCI(at)}` : "—";
  const wfTextEv  = ev.hit_rate != null
    ? `${ev.n_reverted}/${ev.n} (${Math.round(ev.hit_rate*100)}%) · 95% CI ${fmtCI(ev)}`
    : (wf.event_day_caveat || "—");

  return `<section class="rop">
    <div class="rop-head">
      <div>
        <h2>REGIME & OVERLAY${asOfBadge(r.session_date || r.as_of)}</h2>
        <div class="sub">VIX term-structure state · spike attribution · diagnostic overlay</div>
      </div>
      <div class="mono t1 c-3">
        spread = <strong class="c-1">${r.spread >= 0 ? "+" : ""}${r.spread}</strong>
        (Δ ${r.delta_spread >= 0 ? "+" : ""}${r.delta_spread})
        · ${r.tradable_at ? `signal at close · tradable next open ${r.tradable_at}` : ""}
      </div>
    </div>

    <div class="rop-grid">
      <!-- State + dynamics -->
      <div class="rop-block">
        <h4>STATE · DYNAMICS</h4>
        <div class="rop-state ${r.state}">${r.state.replace("_"," ")}</div>
        <div class="rop-meta">
          Age <strong>${r.state_age}</strong> session${r.state_age === 1 ? "" : "s"}
          · median persistence <strong>${dyn.median_sessions || "—"}</strong>
          (p25 ${dyn.p25_sessions || "—"} · p75 ${dyn.p75_sessions || "—"})
          ${nextTypical ? `<div>most-common next state: <strong>${nextTypical.state}</strong> (${nextTypical.pct}% of transitions)</div>` : ""}
        </div>
        ${twoHorizonLine}
        ${atypicalCaveat}
        <div class="mt2">
          <div class="mono t1 w6 c-3 ls14">HISTORY · last 180 sessions</div>
          <div class="rop-history-strip">${stripCells}</div>
        </div>
        <div class="mt2">
          <div class="mono t1 w6 c-3 ls14">PAST TRIGGER SPIKES (most recent 8 · event-tagged if applicable)</div>
          <div class="rop-spike-list">${spikeList || '<div class="c-3 it">no recent trigger episodes</div>'}</div>
        </div>
        ${renderStatesLegend(r)}
      </div>

      <!-- Conditioning + attribution -->
      <div class="rop-block">
        <h4>CONDITIONING · ATTRIBUTION</h4>
        ${condRow("Event flag",
                  r.conditioning.event_flag ? r.conditioning.event_types.join(" · ") : "—",
                  r.conditioning.event_flag)}
        ${condRow("Δ2Y (bps)",
                  r.conditioning.delta_2y_bps != null
                    ? `${r.conditioning.delta_2y_bps >= 0 ? "+" : ""}${r.conditioning.delta_2y_bps} <span class="c-3 w4">(${r.conditioning.delta_2y_source})</span>`
                    : '<span class="c-3">unavailable (FRED T+1)</span>',
                  r.conditioning.front_end_repriced)}
        ${condRow("Close behaviour",
                  `proxy ${r.conditioning.held_close_proxy} ${r.conditioning.held_close ? '· held' : '· faded'}`,
                  r.conditioning.held_close)}
        <div class="rop-attr">
          <div class="mono t1 w6 c-3 ls14">PRIMARY DRIVER ${r.trigger_fired ? "" : '<span class="c-3">· no trigger</span>'}</div>
          <div class="driver">${driver.replace(/_/g, " ")}</div>
          <div class="reversion">reversion bucket: <strong class="c-1">${reversion.toUpperCase()}</strong>
            · horizon ${r.config.reversion_N} sessions within ${r.config.reversion_X_sigma}σ</div>
          ${equityDrag ? `<div class="overlay-flag">↘ EQUITY DRAG OVERLAY · SMH ${(eqInputs.smh_1d_return*100).toFixed(1)}% · breadth Δ ${eqInputs.breadth_delta_pp >= 0 ? "+" : ""}${eqInputs.breadth_delta_pp}pp ${eqInputs.breadth_z != null ? `(z = ${eqInputs.breadth_z}σ, holds)` : ""}</div>` : ""}
        </div>
      </div>

      <!-- Curve + overlay scalar + validation -->
      <div class="rop-block">
        <h4>TERM CURVE · OVERLAY</h4>
        <div class="rop-curve-wrap"><canvas id="rop-curve"></canvas></div>
        <div class="serif t1 it c-3 mt2 lh14">
          Headline spread = <strong class="fs-n mono c-2">spot − 3M</strong>
          (VIX − VIX3M). The 1-day (VIX1D) point is event-vol context — plotted as
          a separate marker, NOT part of the spread definition.
        </div>
        <div class="rop-overlay-scalar">
          <div class="lbl">OVERLAY POSITION SCALAR</div>
          <div class="v">${ovs.value >= 0 ? "+" : ""}${ovs.value} <span class="mono t1 w6 c-accent ls14">${ovs.label}</span></div>
          <div class="cap">${ovs.caption || ""}</div>
        </div>
        <div class="rop-validation">
          <div class="mono t1 w6 c-3 ls14 mb1">
            WALK-FORWARD REVERSION · horizon ${at.horizon_sessions || "—"} sessions / ±${at.threshold_sigma || "—"}σ
            · today (${wf.today_excluded_from_metrics || "—"}) excluded
          </div>
          <div class="flx gap1 x22">
            <div>All triggers (the well-evidenced number): <strong class="c-1">${wfTextAll}</strong></div>
            <div>Event-day only (handful per year): <strong class="c-2 it">${wfTextEv}</strong></div>
            ${ev.hit_rate != null && ev.n < 30 ? `<div class="c-warn it t1 mt1">⚠ ${wf.event_day_caveat || ""}</div>` : ""}
          </div>
          <div class="mt2">No-look-ahead: <strong class="c-pos">${r.validation && r.validation.no_lookahead_passed ? "PASS" : "—"}</strong></div>
        </div>
      </div>
    </div>
  </section>`;
}

// RoP-FIX 6: states legend — explains the four spread bands with verbal
// descriptions. Mono caption underneath the STATE block.
function renderStatesLegend(r){
  const breaks = (r.config && r.config.state_breaks) || {};
  const dc = breaks.deep_contango_max != null ? breaks.deep_contango_max.toFixed(1) : "−3.0";
  const c  = breaks.contango_max != null ? breaks.contango_max.toFixed(1) : "−1.0";
  const f  = breaks.flattening_max != null ? "+" + breaks.flattening_max.toFixed(1) : "+0.5";
  const row = (name, band, gloss) => `
    <div class="gap2 x23">
      <div class="mono t1 w6 c-2 ls04">${name}</div>
      <div class="mono t1 w5 c-3">${band}</div>
      <div class="serif t1 it c-3 lh14">${gloss}</div>
    </div>`;
  return `<div class="mt2">
    <div class="mono t1 w6 c-3 ls14 mb1">
      TERM-STRUCTURE STATES &nbsp;<span class="w4 c-3 ls0">(spread = VIX − VIX3M)</span>
    </div>
    ${row("deep contango",  `spread &lt; ${dc}`,
          "Front-month vol far below 3-month; steep, calm upward curve. Most favourable for roll-harvest.")}
    ${row("contango",        `${dc} to ${c}`,
          "Normal upward curve, front below back. Calm baseline; roll-harvest still works.")}
    ${row("flattening",      `${c} to ${f}`,
          "Curve near-flat — front catching up to back. Transitional; tension building. Trim short-vol. ‘Flattening’ here is a spread-LEVEL band; the direction/decay is in the dynamics line above.")}
    ${row("backwardation",   `&gt; ${f}`,
          "Front above back — market prices more fear now than later. Acute stress. Favours long-front / tail.")}
  </div>`;
}

function renderRopCurveChart(){
  const r = S.volRegime;
  if (!r || !r.curve) return;
  const ctx = document.getElementById("rop-curve");
  if (!ctx) return;
  if (S.ropCurveChart) { try { S.ropCurveChart.destroy(); } catch(e){} }
  const curve = r.curve;
  // The spread is spot−3M; plot those two as the "term curve" line.
  // VIX1D (1-day event vol) is plotted as a SEPARATE marker so the reader
  // doesn't mistake event-vol for part of the spread definition.
  const spreadPoints = [
    {x: 0, y: curve.spot_vix},
    {x: 2, y: curve.vix3m},
  ].filter(p => p.y != null);
  const eventVolPoint = curve.vix1d != null ? [{x: 1, y: curve.vix1d}] : [];
  // Color the spread line by current state (semantic)
  const CV = CHARTS.colors();
  const lineColor = r.spread > 0.5 ? CV.neg : (r.spread > -1 ? CV.warn : CV.pos);
  try {
    S.ropCurveChart = CHARTS.make(ctx, {
      type: "line",
      data: { datasets: [
        { label: "term (spot ↔ 3M)", role: "headline", data: spreadPoints,
          borderColor: lineColor, tension: 0,
          pointRadius: 6, pointBackgroundColor: lineColor, pointBorderColor: CV.surface,
          pointBorderWidth: 2, showLine: true, fill: false },
        { label: "1-day VIX1D (event vol)", role: "benchmark", data: eventVolPoint,
          borderColor: CHARTS.alpha(CV.info, 0.6), borderDash: [3,3],
          pointRadius: 5, pointBackgroundColor: "transparent",
          pointBorderColor: CV.info, pointBorderWidth: 2, showLine: false, fill: false },
      ] },
      options: {
        interaction: {mode: "nearest", axis: "xy", intersect: true},
        scales: {
          x: {type: "linear", min: -0.3, max: 2.3,
              ticks: {callback: v => ({0: "spot (1M)", 1: "1-day", 2: "3M"})[v] || ""}},
        },
        plugins: {
          tooltip: {callbacks: { label: ctx => ` ${({0:"spot (1M)",1:"1-day VIX1D",2:"3M"})[ctx.parsed.x] || ""}: ${ctx.parsed.y.toFixed(2)}` }},
        },
      },
    });
  } catch (e) {
    console.error("[rop-curve] Chart.js failed:", e);
  }
}

// Event-day badge for cycle position
function eventTodayBadge(){
  const r = S.volRegime;
  if (!r || !r.event_today || !r.event_today.length) return "";
  return `<div class="event-today-badge">
    <span class="lbl">⊙</span> SCHEDULED MACRO EVENT TODAY · ${r.event_today.join(" · ")}
    <div class="event-today-cap">Regime read is conditional on the print; volatility around it is expected.</div>
  </div>`;
}

// "Next scheduled event in N sessions"
function nextEventLine(){
  const r = S.volRegime;
  if (!r || !r.next_event) return "";
  const n = r.next_event.sessions_away;
  return `<div class="next-event-line">
    Next scheduled event: <strong class="c-2">${r.next_event.types.join("·")}</strong>
    in <strong class="c-2">${n}</strong> session${n === 1 ? "" : "s"}
    (${r.next_event.date}) · model uncertainty elevated.
  </div>`;
}

// ──────────────────────────────────────────────────────────────────────
// THESIS layer — meso: cross-sectional structure of the bets.
// Risk accounting + epistemics, NOT a return forecaster. Holdings-based
// exposure only; no factor regressions on live data; no rotation signal;
// the registry/claims are frozen judgment artifacts rendered verbatim.
// ──────────────────────────────────────────────────────────────────────
// P1.2: thesis identity from the categorical set (palette members only; styles.css --cat1..8)
const THESIS_COLORS = {
  ai_infra: "var(--cat2)", fin_plumbing: "var(--cat3)", hard_assets: "var(--cat1)",
  defensive_quality: "var(--cat6)", ldg_ex_ai: "var(--cat7)", consumer_cyclical: "var(--cat4)",
  speculative_crypto: "var(--cat5)", unclassified: "var(--text-3)", cash: "var(--hairline-hi)",
};
function memberWeight(v){ return (v && typeof v === "object") ? +v.weight : (v == null ? null : +v); }   // registry v4: {weight, sub}
function memberSub(v){ return (v && typeof v === "object") ? (v.sub || null) : null; }
function parentOf(k){ return String(k).split("/")[0]; }
function subLabel(k){ const [p, sub] = String(k).split("/"); const reg = (S.thesisReg && S.thesisReg.theses && S.thesisReg.theses[p]) || {}; const st = reg.sub_theses && reg.sub_theses[sub]; return sub ? (st && st.label ? st.label : sub) : ""; }
const SUB_ORDER = ["memory", "chips", "networking", "hyperscaler", "power", "other"];
function subShade(k){ const sub = String(k).split("/")[1]; const i = SUB_ORDER.indexOf(sub); return "sub-" + (i < 0 ? 5 : i); }
function thesisColor(k){ return THESIS_COLORS[parentOf(k)] || "var(--cat8)"; }
function thesisLabel(k){
  const reg = S.thesisReg && S.thesisReg.theses;
  if (k === "unclassified") return "unclassified";
  if (k === "cash") return "cash";
  return (reg && reg[k] && reg[k].label) || k;
}

function thesisParts(){
  const td = S.thesis;
  if (!td) return "";
  const frozen = td.registry_frozen;
  const view = S.thesisView || "invested";
  const tab  = S.thesisTab || "live";
  const expKey = view === "total" ? "exposure_total" : "exposure_invested";

  // ---- B1: exposure stacked bars + N_eff + overlap ----
  const subSegs = (t, k, w, scale) => {   // v4: a thesis with sub_theses renders its sub-segments, parent total in the title
    const subs = Object.entries(t.exposure_sub || {}).filter(([sk]) => parentOf(sk) === k).sort((a, b) => b[1] - a[1]);
    if (!subs.length) return `<div class="${cc(thesisColor(k),'bg')}" style="width:${(w*100).toFixed(1)}%" title="${thesisLabel(k)}: ${(w*100).toFixed(1)}%"></div>`;
    return subs.map(([sk, sw]) => `<div class="${cc(thesisColor(k),'bg')} ${subShade(sk)}" style="width:${(sw*scale*100).toFixed(1)}%" title="${thesisLabel(k)} · ${subLabel(sk)}: ${(sw*scale*100).toFixed(1)}% (parent ${(w*100).toFixed(1)}%)"></div>`).join("");
  };
  const tierRows = Object.entries(td.tiers || {}).map(([tid, t]) => {
    const exp = t[expKey] || {};
    const scale = expKey === "exposure_total" ? (t.invested_share || 1) : 1;
    const segs = Object.entries(exp).map(([k, w]) => subSegs(t, k, w, scale)).join("");
    const ts = tierSpec(tid);
    return `<div class="th-bar-row">
      <div class="tname ${cc(ts ? ts.color : 'var(--t2)')}">${ts ? ts.short : tid}</div>
      <div class="th-stack">${segs}</div>
      <div class="th-meta">N<sub>eff</sub> <strong class="c-1">${t.n_eff}</strong>
        · uncl ${(t.unclassified_share*100).toFixed(0)}%${t.provisional_share ?
        ` · <span class="c-warn mono t1 w6 r1 x13" title="${(t.coverage_caveat||'').replace(/"/g,'&quot;')} — ${(t.provisional_names||[]).join(', ')}">PROVISIONAL ${(t.provisional_share*100).toFixed(0)}%</span>` : ''}${t.extend_registry_prompt ?
        ' <span class="c-warn" title="Unclassified > 15% of invested — extend the registry (version bump)">⚠ EXTEND</span>' : ''}</div>
    </div>`;
  }).join("");
  const legend = Object.keys(THESIS_COLORS).map(k =>
    `<span><span class="sw ${cc(thesisColor(k),'bg')}"></span>${thesisLabel(k)}</span>`).join("");

  const tids = Object.keys(td.tiers || {});
  const om = td.overlap_matrix || {};
  const heat = (v) => {
    const a = Math.max(0, Math.min(1, v));
    return `rgba(201,168,106,${(a*0.55).toFixed(2)})`;
  };
  const overlapTable = `<table class="th-table mt2">
    <tr><th>OVERLAP</th>${tids.map(t => `<th>${(tierSpec(t)||{}).short || t}</th>`).join("")}</tr>
    ${tids.map(a => `<tr><td>${(tierSpec(a)||{}).short || a}</td>${tids.map(b =>
      `<td style="background:${a===b ? 'transparent' : heat(om[a]?.[b] ?? 0)}">${a===b ? "—" : ((om[a]?.[b] ?? 0)).toFixed(2)}</td>`).join("")}</tr>`).join("")}
  </table>`;

  // ---- B2: basket performance table ----
  const fmtPc = v => v == null ? "—" : ((v >= 0 ? "+" : "") + (v*100).toFixed(1) + "%");
  const basketRows = Object.entries(td.baskets || {}).map(([k, b]) => `
    <tr>
      <td><span class="sw ib wd2 ht2 r1 ${cc(thesisColor(k),'bg')} mr2"></span>${b.label}</td>
      <td class="${b.ret_1d > 0 ? 'pos' : b.ret_1d < 0 ? 'neg' : ''}">${fmtPc(b.ret_1d)}</td>
      <td class="${b.ret_1w > 0 ? 'pos' : b.ret_1w < 0 ? 'neg' : ''}">${fmtPc(b.ret_1w)}</td>
      <td class="${b.ret_inception > 0 ? 'pos' : b.ret_inception < 0 ? 'neg' : ''}">${fmtPc(b.ret_inception)}</td>
      <td class="neg">${fmtPc(b.drawdown_from_peak)}</td>
      <td class="c-3">${b.proxy_etf || "—"} ${fmtPc(b.proxy_ret_1w)}${(b.provisional_members||[]).length ? ` <span class="c-warn mono t1 w6 r1 x13" title="provisional members in this basket: ${b.provisional_members.join(', ')} — expire unless approved">PROVISIONAL +${b.provisional_members.length}</span>` : ''}</td>
      <td>${b.divergence_flag ? `<span class="c-warn" title="basket vs proxy diverge ${b.divergence_1w_pp}pp on the week — classification drift smell">⚠ ${b.divergence_1w_pp}pp</span>` : '<span class="c-3">ok</span>'}</td>
    </tr>`).join("");

  // ---- B3: falsification register ----
  const claims = (S.thesisClaims && S.thesisClaims.claims) || [];
  const ks = td.kill_status || {};
  const claimCards = claims.map(c => {
    const k = ks[c.claim_id || c.thesis_id] || {};
    const status = k.met
      ? `<span class="cl-status c-neg">KILL CRITERIA MET ON ${k.date}</span>`
      : `<span class="cl-status c-pos">no kill criteria met</span>`;
    const log = (c.log || []).slice(-6).reverse().map(l =>
      l.type === "auto"
        ? `<div>${l.date} · ${l.event} · basket 1d ${(l.basket_ret_1d*100).toFixed(2)}%</div>`
        : `<div class="an">${l.date} · analyst entry · ${l.note || ""}${l.kill ? " · KILL" : ""}</div>`
    ).join("");
    const subHead = c.claim_id ? ` <span class="c-3">· ${c.label || c.sub}</span>${(c.label || "").includes("(") ? "" : ` <span class="mono t1 c-3">(${(c.tickers || []).join(", ")})</span>`}` : "";
    const review = c.review_by ? `<div class="mono t1 c-3 mt1">review by <strong class="c-2">${c.review_by}</strong> · next earnings ${c.next_earnings || "—"} + 14 days (event calendar) · frozen ${String(c.frozen_at || "").slice(0, 10)}</div>` : "";
    return `<div class="th-claim">
      <div class="cl-head">
        <span class="cl-name ${cc(thesisColor(c.thesis_id))}">${thesisLabel(c.thesis_id)}${subHead}</span>
        ${status}
      </div>
      <div class="cl-text">${c.claim}</div>
      ${c.disconfirmers && c.claim_id ? `<div class="mono t1 c-3">disconfirmers: ${c.disconfirmers.join(" · ")}</div>` : ""}
      ${review}
      <div class="cl-kill"><span class="k">KILL</span>${c.kill_criteria}</div>
      <div class="th-log">${log || '<div class="c-3 it">no log entries</div>'}</div>
    </div>`;
  }).join("");

  // ---- B4: attribution waterfalls ----
  const attr = td.attribution || {};
  const maxAbs = Math.max(0.0001, ...Object.values(attr).flatMap(a =>
    a.cum ? Object.values(a.cum).map(Math.abs) : [0]));
  const wfRow = (lbl, v) => {
    const w = Math.abs(v) / maxAbs * 50;
    const color = v >= 0 ? "var(--g)" : "var(--r)";
    const left = v >= 0 ? 50 : 50 - w;
    return `<div class="th-wf">
      <span class="lbl">${lbl}</span>
      <div class="barwrap"><div class="bar ${cc(color,'bg')}" style="left:${left}%;width:${w}%"></div>
        <div class="wd1 x24"></div></div>
      <span class="val">${(v*100).toFixed(2)}%</span>
    </div>`;
  };
  const attrBlocks = Object.entries(attr).map(([tid, a]) => {
    const ts = tierSpec(tid); const c = a.cum || {};
    return `<div class="mb2">
      <div class="mono t1 w6 ${cc(ts ? ts.color : 'var(--t2)')} mb1">
        ${ts ? ts.short : tid} <span class="c-3 w4">· active vs SPY ${(c.active*100).toFixed(2)}% · ${a.n_days} sessions</span></div>
      ${wfRow("cash effect", c.cash_eff)}
      ${wfRow("thesis allocation", c.alloc_eff)}
      ${wfRow("selection", c.selection)}
    </div>`;
  }).join("");

  // ---- B5: backtest sub-tab ----
  const bt = S.thesisBT || {};
  const btRows = Object.entries(bt.tiers || {}).map(([tid, t]) => {
    const ts = tierSpec(tid); const c = t.cum || {};
    return `<tr>
      <td class="${cc(ts ? ts.color : 'var(--t2)')}">${ts ? ts.short : tid}</td>
      <td>${t.n_periods}</td>
      <td class="${c.active > 0 ? 'pos' : 'neg'}">${(c.active*100).toFixed(0)}%</td>
      <td class="${c.cash_eff > 0 ? 'pos' : 'neg'}">${(c.cash_eff*100).toFixed(0)}%</td>
      <td class="${c.alloc_eff > 0 ? 'pos' : 'neg'}">${(c.alloc_eff*100).toFixed(0)}%</td>
      <td class="${c.selection > 0 ? 'pos' : 'neg'}">${(c.selection*100).toFixed(0)}%</td>
      <td class="c-3 tal">${Object.entries(t.avg_exposure || {}).slice(0,3).map(([k,v]) => `${thesisLabel(k)} ${(v*100).toFixed(0)}%`).join(" · ")}</td>
    </tr>`;
  }).join("");
  const btCaveats = (bt.caveats || []).map(c => `<div class="th-caveat">⚠ ${c}</div>`).join("");

  return {td, frozen, view, tab, tierRows, legend, overlapTable, basketRows, claimCards, attrBlocks, btRows, btCaveats, bt};
}
function thesisHead(title, sub, extra){
  const td = S.thesis; if (!td) return "";
  const frozen = td.registry_frozen;
  return `<div class="thesis-head"><div><h2>${title}${asOfBadge(td.session_date || td.as_of)}${!frozen ? '<span class="th-pending">REGISTRY v' + td.registry_version + ' PENDING APPROVAL</span>' : '<span class="mono t1 w5 c-3 ml2">registry v' + td.registry_version + ' frozen ' + String(td.registry_frozen_at || "").slice(0, 10) + '</span>'}</h2><div class="sub">${sub}</div></div>${extra || ""}</div>`;
}
function renderThesisExposure(){   // B1 + B2 (tournament page)
  const P = thesisParts(); if (!P) return "";
  const {td, view, tierRows, legend, overlapTable, basketRows} = P;
  return `<section class="thesis">${thesisHead("THESIS — EXPOSURE & BASKETS", "the meso level: cross-sectional structure of the bets — risk accounting, not a return forecaster")}
    <div class="th-block">
      <h4>B1 · EXPOSURE & CONCENTRATION
        <span class="th-toggle">
          <button class="${view==='invested' ? 'on' : ''}" data-thesis-view="invested">INVESTED</button>
          <button class="${view==='total' ? 'on' : ''}" data-thesis-view="total">TOTAL incl. cash</button>
        </span></h4>
      ${tierRows}
      <div class="th-legend">${legend}</div>
      ${overlapTable}
      <div class="th-caveat">${td.method_caption}</div>
    </div>
    <div class="th-block">
      <h4>B2 · THESIS BASKETS — performance & drawdown (context, not signal)</h4>
      <table class="th-table">
        <tr><th>THESIS</th><th>1D</th><th>1W</th><th>SINCE 05-20</th><th>DD</th><th>PROXY 1W</th><th>DIV</th></tr>
        ${basketRows}
      </table>
      <div class="mt2">
        <div class="mono t1 w6 c-3 ls14 mb1">
          RELATIVE STRENGTH — ai_infra / fin_plumbing · ai_infra / hard_assets
          <span class="w4 ls0 c-3">· ${td.rs_caption}</span></div>
        <div class="th-rs-wrap"><canvas id="thesis-rs-chart"></canvas></div>
      </div>
      <div class="th-caveat">${td.small_n_caveat}</div>
    </div>
  </section>`;
}
function renderThesisRegister(){   // B3 (register page)
  const P = thesisParts(); if (!P) return "";
  return `<section class="thesis">${thesisHead("THESIS REGISTER — CLAIMS · DISCONFIRMERS · KILL CRITERIA · LOG", "auto = mechanical event-day and earnings-day entries; analyst = Werner; kill status is mechanical")}
    <div class="th-block">${P.claimCards}</div>
  </section>`;
}
function renderThesisAttribution(){   // B4 live + B5 backtest (tournament page)
  const P = thesisParts(); if (!P) return "";
  const {td, tab, attrBlocks, btRows, btCaveats, bt} = P;
  const toggle = `<span class="th-toggle"><button class="${tab==='live' ? 'on' : ''}" data-thesis-tab="live">LIVE</button><button class="${tab==='backtest' ? 'on' : ''}" data-thesis-tab="backtest">BACKTEST</button></span>`;
  const live = `<div class="th-block">
      <h4>B4 · ATTRIBUTION — cash | allocation | selection (sums to active vs SPY; residual-defined)</h4>
      ${attrBlocks}
      <div class="th-caveat">${td.small_n_caveat} Components are arithmetic sums of daily effects; no CIs fabricated on ${td.sessions_since_inception} points.</div>
      <div class="th-caveat">"Selection" is measured against equal-weight thesis baskets; with coarse buckets, within-thesis composition (e.g. memory vs megacap-AI) appears as selection. Registry v4 carries a sub-thesis field for display; the parent buckets — and this attribution — are unchanged by it.</div>
    </div>`;
  const back = `<div class="th-block">
      <h4>B5 · BACKTEST ATTRIBUTION — full walk-forward, ${(bt.tiers && Object.values(bt.tiers)[0] || {}).n_periods || "—"} monthly periods</h4>
      <table class="th-table">
        <tr><th>TIER</th><th>PERIODS</th><th>CUM ACTIVE</th><th>CASH</th><th>ALLOCATION</th><th>SELECTION</th><th class="tal">AVG TOP EXPOSURES</th></tr>
        ${btRows}
      </table>
      ${btCaveats}
    </div>`;
  return `<section class="thesis">${thesisHead("THESIS — ATTRIBUTION", "cash effect, thesis allocation and selection; live since inception and over the walk-forward backtest", toggle)}
    ${tab === "live" ? live : back}
  </section>`;
}

function renderThesisRsChart(){
  const td = S.thesis;
  if (!td || !td.rs_series) return;
  const ctx = document.getElementById("thesis-rs-chart");
  if (!ctx) return;
  if (S.thesisRsChart) { try { S.thesisRsChart.destroy(); } catch(e){} }
  const toIdx = arr => (arr || []).map((p, i) => ({x: i, y: p.v, d: p.d}));
  const s1 = toIdx(td.rs_series.ai_infra_vs_fin_plumbing);
  const s2 = toIdx(td.rs_series.ai_infra_vs_hard_assets);
  // Regime shading: amber boxes over spans where R_t >= 0.5 (HIGH+) within window
  const annotations = {};
  if (S.regimeDaily && s1.length) {
    const dates = s1.map(p => p.d);
    const rmap = {};
    S.regimeDaily.forEach(r => { if (r.date && r.R_t != null) rmap[String(r.date).slice(0,10)] = +r.R_t; });
    let spanStart = null;
    dates.forEach((d, i) => {
      const hot = (rmap[d] ?? 0) >= 0.5;
      if (hot && spanStart === null) spanStart = i;
      if ((!hot || i === dates.length - 1) && spanStart !== null) {
        annotations["regime" + spanStart] = {
          type: "box", xMin: spanStart, xMax: i, yScaleID: "y",
          backgroundColor: CHARTS.alpha(CHARTS.colors().warn, 0.08), borderWidth: 0,
        };
        spanStart = null;
      }
    });
  }
  const xTickCb = arr => v => {
    const i = Math.round(v);
    return (i >= 0 && i < arr.length && arr[i]) ? arr[i].d.slice(0, 7) : "";
  };
  try {
    const CS = CHARTS.colors();
    S.thesisRsChart = CHARTS.make(ctx, {
      type: "line",
      data: { datasets: [
        { label: "ai_infra / fin_plumbing", data: s1, borderColor: CS.info, tension: 0.1 },
        { label: "ai_infra / hard_assets",  data: s2, borderColor: CS.accent, tension: 0.1 },
      ]},
      options: {
        scales: {
          x: {type: "linear", min: 0, max: Math.max(0, s1.length - 1),
              ticks: {stepSize: Math.max(1, Math.floor(s1.length/6)), callback: xTickCb(s1)}},
        },
        plugins: {
          tooltip: {callbacks: { title: items => (items[0] && s1[items[0].dataIndex]?.d) || "",
                                  label: c => ` ${c.dataset.label}: ${c.parsed.y.toFixed(3)}` }},
          annotation: {annotations},
        },
      },
    });
  } catch (e) {
    console.error("[thesis-rs] Chart.js failed:", e);
  }
}

// ──────────────────────────────────────────────────────────────────────
// Scanner: list all tickers with computed signals side-by-side, with two
// mini-bars per row (quality + trade-now) and the divergence flag. The
// dashboard's other views (regime gauge, tier rows) are organised by
// strategy; this view is organised by ACTIONABILITY across every name.
// ──────────────────────────────────────────────────────────────────────
function scannerRows(){
  if (!S.signals || !S.signals.signals) return [];
  const rows = [];
  for (const [tk, s] of Object.entries(S.signals.signals)){
    const quality = (s.data && s.data.composite != null) ? +s.data.composite : 0;
    const qPct    = (s.data && s.data.composite_pct != null) ? +s.data.composite_pct : 0;
    const rank    = (s.data && s.data.rank != null) ? +s.data.rank : 9999;
    const trade   = s.mode === "position" ? null : (s.trade_now_strength != null ? +s.trade_now_strength : +s.signal_strength);
    const sig     = s.signal || "—";
    const div     = divergenceState(quality, qPct, trade, sig, s.mode, s.state);
    // quad order: actionable buys + exits at the top, holds at the bottom
    const quadOrder = ({clean:9, exit:8, trim:7, watch:6, momo:5, hedge:4,
                        wait:3, monitor:2, hold:1, avoid:0})[div.cls] ?? 0;
    // options lens (3.2): the third dimension — volatility state by marker, a ring for a release inside 30 days
    const o = optLens(tk); const ov = (o && o.volatility) || {}; const oe = (o && o.event) || {};
    const optState = o ? (o.impaired ? "impaired" : ov.state) : null;
    const optDays = oe.days_to != null ? oe.days_to : null;
    const optRing = optDays != null && optDays >= 0 && optDays <= 30;
    const optOrder = ({cheap:0, mixed:1, rich:2, impaired:3})[optState] ?? 9;
    rows.push({tk, quality, qPct, rank, trade, sig, divCls:div.cls,
               divColor:div.color, divIcon:div.icon, quadOrder,
               mode:s.mode, note:s.trade_now_note,
               optState, optDays, optRing, optOrder, optImp: oe.implied_move});
  }
  return rows;
}
function scannerFilterFn(filter){
  if (filter === "earnings")  return r => r.optRing;
  if (filter === "clean")     return r => r.divCls === "clean";
  if (filter === "watch")     return r => r.divCls === "watch";
  if (filter === "exit")      return r => r.divCls === "exit" || r.divCls === "trim";
  if (filter === "quality")   return r => r.quality >= 38;
  if (filter === "positions") return r => r.mode === "position";
  return () => true;
}
function scannerSortFn(sortKey, dir){
  const mult = dir === "asc" ? 1 : -1;
  if (sortKey === "tk")      return (a,b) => mult * a.tk.localeCompare(b.tk);
  if (sortKey === "quality") return (a,b) => mult * (a.quality - b.quality);
  if (sortKey === "trade")   return (a,b) => mult * ((a.trade ?? -1) - (b.trade ?? -1));
  if (sortKey === "opt")     return (a,b) => (mult * ((a.optOrder ?? 9) - (b.optOrder ?? 9))) || ((a.optDays ?? 999) - (b.optDays ?? 999));
  // quad (default): divergence-quadrant ordering first, then quality desc
  return (a,b) => (mult * (a.quadOrder - b.quadOrder))
                || (b.quality - a.quality);
}
function renderScanner(){
  const rows0 = scannerRows();
  if (!rows0.length) return "";
  const rows = rows0.filter(scannerFilterFn(S.scannerFilter))
                    .sort(scannerSortFn(S.scannerSort, S.scannerSortDir));

  const sortCls = (k) => k === S.scannerSort ? `sort ${S.scannerSortDir === "asc" ? "asc" : ""}` : "";

  const filterChips = [
    {k:"all",       lbl:`All (${rows0.length})`},
    {k:"clean",     lbl:`★ Conditions met (${rows0.filter(r=>r.divCls==="clean").length})`},
    {k:"watch",     lbl:`⚠ Quality, extended from the reference (${rows0.filter(r=>r.divCls==="watch").length})`},
    {k:"exit",      lbl:`▽ Below a rulebook level (${rows0.filter(r=>r.divCls==="exit"||r.divCls==="trim").length})`},
    {k:"quality",   lbl:`Top quality (${rows0.filter(r=>r.quality>=38).length})`},
    {k:"positions", lbl:`Owned (${rows0.filter(r=>r.mode==="position").length})`},
    {k:"earnings",  lbl:`◎ Earnings ≤30d (${rows0.filter(r=>r.optRing).length})`},
  ];

  const tradeColorFor = t => tradeColor(t);
  const qColorFor     = q => qualityColor(q);

  let body = "";
  for (const r of rows){
    const qPct = Math.max(0, Math.min(100, r.quality / 50 * 100));
    const tPct = r.trade == null ? 0 : Math.max(0, Math.min(100, r.trade));
    body += `<tr class="row" data-scanner-tk="${r.tk}">
      <td class="tk">${r.tk}</td>
      <td class="bar-cell">
        <div class="minibar-wrap">
          <div class="minibar"><div class="minibar-fill ${cc(qColorFor(r.quality),'bg')}" style="width:${qPct.toFixed(0)}%"></div></div>
        </div>
      </td>
      <td class="val">${r.quality.toFixed(1)}<small class="c-3">/50</small>${r.rank===1 ? ' <span class="x25">#1</span>' : r.rank<=10 ? ` <span class="c-3">#${r.rank}</span>` : ''}</td>
      <td class="bar-cell">${r.trade == null ? `<span class="c-3 t1">position mode</span>` : `<div class="minibar-wrap">
          <div class="minibar"><div class="minibar-fill ${cc(tradeColorFor(r.trade),'bg')}" style="width:${tPct.toFixed(0)}%"></div></div>
        </div>`}
      </td>
      <td class="val">${r.trade == null ? `<span class="${cc(r.divColor)}">${r.sig.length > 22 ? r.sig.substring(0,20) + "…" : r.sig}</span>` : `<span class="${cc(tradeColorFor(r.trade))}">${r.sig.length > 18 ? r.sig.substring(0,16) + "…" : r.sig}</span> · ${r.trade}`}</td>
      <td class="flag ${cc(r.divColor)}">${r.divIcon} ${r.divCls}</td>
      <td class="t1">${entryBadge(r.tk)}</td>
      <td class="opt" title="${r.optState ? `options: volatility ${r.optState}${r.optDays != null ? "; earnings in " + r.optDays + " days" : ""}${r.optImp != null ? "; market prices ±" + (r.optImp * 100).toFixed(1) + "%" : ""}` : "no chain vintage"}">${r.optState ? `<span class="${OPT_STATE_CLS[r.optState] || "c-warn"} w6">${OPT_GLYPH[r.optState] || "◌"}</span> <span class="c-3">${r.optState}</span>` : `<span class="c-3">—</span>`}${r.optRing ? ` <span class="c-warn" title="earnings release inside 30 days">◎ ${r.optDays}d</span>` : ""}</td>
    </tr>`;
  }

  return `<section class="scanner">
    <div class="scanner-head">
      <div>
        <h2>SCANNER — BUSINESS QUALITY × SETUP READING${asOfBadge(S.signals && S.signals.updated)}${S.optionsLens ? optionsAgeBadge(S.optionsLens.session_date) : ""}</h2>
        <div class="sc-sub">${rows.length} of ${rows0.length} names · top of list = best divergence quadrant</div>
      </div>
      <div class="filter-row">
        ${filterChips.map(f => `<button class="filter-btn ${S.scannerFilter===f.k?"on":""}" data-scfilter="${f.k}">${f.lbl}</button>`).join("")}
      </div>
    </div>
    <table>
      <thead><tr>
        <th class="${sortCls("tk")}"      data-scsort="tk">TICKER</th>
        <th class="${sortCls("quality")}" data-scsort="quality">BUSINESS QUALITY</th>
        <th class="num"></th>
        <th class="${sortCls("trade")}"   data-scsort="trade">SETUP READING</th>
        <th class="num"></th>
        <th class="${sortCls("quad")}"    data-scsort="quad">FLAG</th>
        <th title="entry state (DIAGNOSTIC): AVOID · WATCH · READY · READY-HALF">ENTRY STATE</th>
        <th class="${sortCls("opt")}"     data-scsort="opt" title="options: ◯ volatility cheap · ● rich · ◐ mixed · ◎ earnings inside 30 days">OPTIONS</th>
      </tr></thead>
      <tbody>${body}</tbody>
    </table>
  </section>`;
}

// -------- Signal box (entry/stop/target/size/why/risks) --------
const SIG_COLORS = {
  // P1.2: semantic classes (styles.css .sig-*) instead of per-signal rgba/hex; the palette does not grow
  "STRONG BUY": {cls:"sig-pos sig-strong", text:"var(--pos)",  icon:"▲▲"},
  "BUY":        {cls:"sig-pos",            text:"var(--pos)",  icon:"▲"},
  "WATCH":      {cls:"sig-info",           text:"var(--info)", icon:"◉"},
  "WAIT":       {cls:"sig-warn",           text:"var(--warn)", icon:"⏸"},
  "HOLD":       {cls:"sig-2",              text:"var(--text-2)", icon:"—"},
  "TRIM":       {cls:"sig-warn",           text:"var(--warn)", icon:"✂"},
  "SELL":       {cls:"sig-neg",            text:"var(--neg)",  icon:"▼"},
};
function rrColor(rr){ return rr >= 2.0 ? "#4ade80" : rr >= 1.5 ? "#facc15" : "#f87171"; }
function fmtMoney(v){ if (v == null || !Number.isFinite(v)) return "—"; return "$" + v.toLocaleString("en-US",{minimumFractionDigits:0,maximumFractionDigits:0}); }
function sigVerb(s){ return (s||"HOLD").split(/[\s—]+/)[0].toUpperCase(); }

function renderSignalBox(tk){
  const sig = S.signals && S.signals.signals && S.signals.signals[tk];
  if (!sig) return "";
  if (sig.mode === "position") return renderPositionBox(sig, tk);
  return renderEntryBox(sig);
}

const GRADE_COLORS = {   // descriptive setup grades (16-Sept, acceptance 8): colour by condition count, no verb
  strong: SIG_COLORS["STRONG BUY"], conditions_met: SIG_COLORS["BUY"], partial: SIG_COLORS["WATCH"],
  few: SIG_COLORS["HOLD"], extended: SIG_COLORS["WAIT"],
};
function renderEntryBox(sig){
  const baseSig = sigVerb(sig.signal);
  const sc = (sig.setup_grade && (baseSig === "CAUTION" ? SIG_COLORS["SELL"] : GRADE_COLORS[sig.setup_grade])) || SIG_COLORS[baseSig] || SIG_COLORS["HOLD"];
  const rr = sig.target?.reward_risk ?? 0;
  const rrc = rrColor(rr);

  const cell = (label, value, sub) => `
    <div>
      <div class="mono t1 w6 c-3 ls16 mb1">${label}</div>
      ${value}${sub ? `<div class="mono t1 c-3 mt1">${sub}</div>` : ""}
    </div>`;

  const condList = obj => Object.entries(obj || {}).map(([k, v]) =>
    `<div class="ib mr3">
       <span class="${cc(v?'#4ade80':'#f87171')} w7">${v?'✓':'✗'}</span>
       <span class="c-3">${k.replace(/_/g,' ')}</span>
     </div>`).join("");

  return `<div class="sig-card ${sc.cls} r2 mb3 x26">
    <div class="flx mb3 gap3 x27">
      <div>
        <span class="sig-badge mono t1 w8 ls15 ${sc.cls} r1 x28">${sc.icon} ${sig.signal}</span>
        <span class="mono t1 w5 c-3 ml2">${sig.category} · setup rank ${sig.signal_strength}/100 · descriptive</span>
      </div>
      <div class="mono t1 w5 c-3">
        R/R <strong class="${cc(rrc)}">${rr}:1</strong>
        <span class="ib wd2 ht2 r-round ${cc(rrc,'bg')} ml1 va-m"></span>
      </div>
    </div>

    <div class="gap2 mb3 x29">
      ${cell("RULEBOOK STOP",
        `<div class="mono t3 w7 c-neg">$${(sig.stop?.price ?? 0).toFixed(2)}</div>`,
        `${sig.stop?.category_rule || ""}${sig.stop?.category_rule ? "<br>" : ""}the rulebook's percentage stop (the entry state's stop above is a separate rule)`)}
      ${cell("RULEBOOK TARGET LEVELS",
        `<div class="mono t3 w7 c-pos">$${(sig.target?.base ?? 0).toFixed(2)}</div>`,
        `Cons: $${(sig.target?.conservative ?? 0).toFixed(2)}<br>Aggr: $${(sig.target?.aggressive ?? 0).toFixed(2)}`)}
    </div>
    <details class="mb2"><summary class="mono t1 c-3 ptr ls05">rulebook reference (descriptive): the mean-reversion reference and the rulebook's 1%-risk size, which the entry state's size supersedes</summary>
    <div class="gap2 mt2 x29">
      ${cell("MEAN-REVERSION REFERENCE",
        `<div class="mono t3 w7 c-2">$${(sig.entry?.primary ?? 0).toFixed(2)}</div>`,
        `${(sig.entry?.basis || "").replace(/rulebook entry zone/g, "mean-reversion reference")}<br>2nd: $${(sig.entry?.secondary ?? 0).toFixed(2)} · a reference level, not an entry signal (the entry state above reads timing)`)}
      ${cell("RULEBOOK SIZE FORMULA",
        `<div class="mono t3 w7 c-1">${fmtMoney(sig.size?.dollars)}</div>`,
        `${sig.size?.shares ?? 0} shares · ${sig.size?.pct_portfolio ?? 0}% (1% risk budget, 5% cap)<br>loss at the stop: ${fmtMoney(sig.size?.max_loss)}`)}
    </div></details>

    <div class="mb2">
      <span class="mono t1 w6 c-3 ls16">WHY</span>
      <p class="c-2 lh16 mt1 x30">${sig.why || ""}</p>
    </div>
    <div>
      <span class="mono t1 w6 c-3 ls16">RISKS</span>
      <p class="serif t2 it c-3 lh155 mt1">${sig.risks || ""}</p>
    </div>

    <details class="mt2">
      <summary class="mono t1 w5 c-3 ptr ls05">Signal conditions</summary>
      <div class="mt2 mono t1 lh19">
        <div><span class="c-3 w7">ENTRY:</span> ${condList(sig.conditions?.buy)}</div>
        <div><span class="c-3 w7">STRONG:</span> ${condList(sig.conditions?.strong_buy)}</div>
        <div><span class="c-3 w7">CAUTION:</span> ${condList(sig.conditions?.sell)}</div>
      </div>
    </details>
    ${sigLabelLine(sig)}
  </div>`;
}

// -------- Position-mode signal box (held names) — 16-Sept 1.7: observations against the rulebook, never imperatives --------
const POS_STATE = {
  below_stop_from_cost: {cls: "sig-neg",  icon: "▽"}, below_trailing_level: {cls: "sig-warn", icon: "◇"},
  past_trim_level:      {cls: "sig-warn", icon: "◆"}, thesis_flags:         {cls: "sig-neg",  icon: "✗"},
  hedge_condition:      {cls: "sig-info", icon: "◈"}, yellow_flags:         {cls: "sig-2",    icon: "◦"},
  within_rules:         {cls: "sig-2",    icon: "○"}, insufficient_history: {cls: "sig-2",    icon: "·"},
  no_price_history:     {cls: "sig-2",    icon: "·"},
};
function sigLabelLine(sig){ return `<div class="sig-label mono t1 c-3 mt2">${sig.label || "mechanical rulebook; expectancy not validated"}</div>`; }
function renderPositionBox(sig, tk){
  const p = sig.position || {}, s = sig.stops || {};
  const st = POS_STATE[sig.state] || POS_STATE.within_rules;
  const money = v => v == null ? "—" : "$" + fmt(Math.round(Math.abs(v)));
  const cell = (label, big, sub, cls="c-1") => `<div><div class="mono t1 w6 c-3 ls16 mb1">${label}</div><div class="mono t3 w7 ${cls}">${big}</div>${sub ? `<div class="mono t1 c-3 mt1">${sub}</div>` : ""}</div>`;
  if (sig.state === "insufficient_history" || sig.state === "no_price_history") {
    return `<div class="sig-card ${st.cls} r2 mb3 x26">
      <div class="flx mb3 gap3 x27"><div><span class="sig-badge mono t1 w8 ls15 ${st.cls} r1 x28">${st.icon} ${sig.signal}</span><span class="mono t1 w5 c-3 ml2">position mode · ${p.shares != null ? p.shares + " shares" : ""}</span></div><div class="mono t1 w5 c-3">POSITION MODE</div></div>
      <p class="c-2 lh16 x30">${sig.observation || ""}</p>
      <div class="gap2 mb2 x29">${cell("COST", sig.cost_basis != null ? "$" + (+sig.cost_basis).toFixed(2) : "—", "", "c-2")}${cell("RULEBOOK STOP FROM COST", sig.stop_from_cost != null ? "$" + (+sig.stop_from_cost).toFixed(2) : "—", sig.stop_rule || "", "c-2")}${p.current_price != null ? cell("PRICE", "$" + (+p.current_price).toFixed(2), p.gain_pct != null ? (p.gain_pct >= 0 ? "+" : "") + p.gain_pct.toFixed(1) + "% on cost" : "") : ""}</div>
      ${sigLabelLine(sig)}
    </div>`;
  }
  const thesisRows = (sig.thesis || []).map(t => {
    const cls = t.status === "green" ? "c-pos" : t.status === "yellow" ? "c-warn" : "c-neg";
    const icon = t.status === "green" ? "✓" : t.status === "yellow" ? "⚠" : "✗";
    return `<div class="serif t1 ${cls} lh17">${icon} ${t.text}</div>`; }).join("");
  const trimHtml = sig.trim
    ? `<div class="mono t1 c-3 mt2">next rulebook trim level: <strong class="c-2">${sig.trim.at_gain}</strong> at $${sig.trim.trigger_price} (${sig.trim.distance >= 0 ? "+" : ""}${sig.trim.distance}% from here; ${sig.trim.trim_pct}% of the position at that level)</div>`
    : (sig.trim_passed ? `<div class="mono t1 c-3 mt2">every trim level of the schedule (+100 / +200 / +300 percent) has been passed</div>` : `<div class="mono t1 c-3 mt2">no trim level ahead</div>`);
  const hedgeHtml = sig.hedge ? `<div class="mt2 mono t1 c-3">${sig.hedge.text}</div>` : "";
  const gainCls = (p.gain_pct || 0) >= 0 ? "c-pos" : "c-neg";
  return `<div class="sig-card ${st.cls} r2 mb3 x26">
    <div class="flx mb3 gap3 x27">
      <div><span class="sig-badge mono t1 w8 ls15 ${st.cls} r1 x28">${st.icon} ${sig.signal}</span><span class="mono t1 w5 c-3 ml2">${sig.category} · ${p.weight_pct}% of portfolio</span></div>
      <div class="mono t1 w5 c-3">POSITION MODE</div>
    </div>
    <p class="c-1 lh16 x30 sig-observation">${sig.observation || ""}</p>
    ${optEventLine(tk)}
    <div class="gap2 mb2 x29">
      ${cell("COST", "$" + (+p.cost_basis).toFixed(2), `${p.shares} shares`, "c-2")}
      ${cell("PRICE", "$" + (+p.current_price).toFixed(2), money(p.position_value))}
      ${cell("ON COST", (p.gain_pct >= 0 ? "+" : "") + (+p.gain_pct).toFixed(1) + "%", (p.gain_dollars >= 0 ? "+" : "−") + money(p.gain_dollars), gainCls)}
      ${cell("RULEBOOK STOP FROM COST", "$" + (+sig.stop_from_cost).toFixed(2), `${sig.stop_rule || ""} · price ${s.vs_stop_from_cost_pct >= 0 ? "+" : ""}${s.vs_stop_from_cost_pct}% from it`, "c-neg")}
      ${cell("TRAILING LEVEL", "$" + (+s.trail_stop).toFixed(2), `−${s.trail_pct}% from the $${(+p.peak_price).toFixed(0)} peak · ${s.trail_bracket} bracket · price ${s.vs_trailing_pct >= 0 ? "+" : ""}${s.vs_trailing_pct}% from it`, "c-warn")}
    </div>
    ${trimHtml}${hedgeHtml}
    <div class="mt3"><div class="mono t1 w6 c-3 ls12 mb2">THESIS CHECK · descriptive readings</div>${thesisRows}</div>
    <details class="mt2"><summary class="mono t1 w5 c-3 ptr ls05">Rulebook levels</summary><div class="mt2 mono t1 c-3 lh17">${sig.why || ""}</div></details>
    ${sigLabelLine(sig)}
  </div>`;
}

function renderTickerDetail(tk){
  const data = S.tickers && S.tickers[tk];
  if (!data) return `<div class="tk-detail"><div class="c-3">No data for ${tk}</div></div>`;
  const T = data.tech || {}, F = data.fund || {}, SC = data.score, C = data.corr || {};

  // Score bar component
  const scoreBar = (label, pct) => {
    const v = (pct != null) ? pct : 50;
    return `<div class="sb">
      <div class="sb-lbl">${label}</div>
      <div class="sb-bar"><div class="fill ${cc(rankColor(v),'bg')}" style="width:${v}%"></div></div>
      <div class="sb-val">${v.toFixed(0)}</div>
    </div>`;
  };
  // Fundamental card
  // Order 6-Oct-2026, section 4: a field the provider checks flag is greyed out with the reason (and excluded
  // from the screen's scores until the next filing clears it)
  const pflags = {}; ((entryRec(tk) || {}).provider_flags || []).forEach(f => { pflags[f.field] = f; });
  const fundCard = (label, val, unit="", field=null) => {
    const fl = field && pflags[field];
    if (fl) return `<div class="fund-card suspect" title="${escText30("provider data suspect: " + fl.reason + " · excluded from the screen's scores until the next filing clears it")}"><div class="k">${label} <span class="c-neg">?</span></div><div class="v c-3"><s>${val == null ? "—" : val + unit}</s></div><div class="t1 c-3 lh14">${escText30(fl.reason)}</div></div>`;
    if (val == null) return `<div class="fund-card"><div class="k">${label}</div><div class="v c-3">—</div></div>`;
    return `<div class="fund-card"><div class="k">${label}</div><div class="v">${val}${unit}</div></div>`;
  };

  return `<div class="tk-detail">
    <div class="tk-head">
      <div class="tk-title">
        <h3>${tk} <small class="t1 c-3">${data.name || ""}</small></h3>
        <div class="sub">${data.sector || ""}${data.industry ? " · " + data.industry : ""}</div>
        <div class="tk-tiers">IN: ${(data.in_tiers || []).map(t => {
          const ts = tierSpec(t); return `<span class="${cc(ts ? ts.color : "var(--t3)")}">${ts ? ts.short : t}</span>`;
        }).join(" · ") || "—"}</div>
      </div>
      <button class="tk-close" data-close-tk="1">CLOSE ✕</button>
    </div>

    ${renderTwoScore(tk)}

    ${renderEntryState(tk)}
    ${renderSignalBox(tk)}

    <div class="tk-grid">
      <div>
        <div class="flx mb2 x33">
          <div class="mono t1 w6 c-3 ls18">PRICE — MA50 — MA200</div>
          <div class="flx gap1">
            ${["3M","6M","1Y"].map(p => `<button class="period-btn ${S.tickerChartPeriod===p?"on":""}" data-tkp="${p}">${p}</button>`).join("")}
          </div>
        </div>
        <div class="tk-chart-wrap"><canvas id="ticker-chart"></canvas></div>
        <div class="tk-rets">
          ${["1w","1m","3m","6m","1y"].map(p => {
            const v = T["ret_"+p];
            return `<div class="ret-card"><div class="k">${p.toUpperCase()}</div><div class="v ${v!=null?pnlc(v):'neut'}">${v!=null?fmtP1(v):"—"}</div></div>`;
          }).join("")}
        </div>
      </div>
      <div class="tk-stats">
        <div class="stat"><div class="k">PRICE</div><div class="v">$${fmt2(T.price)}</div></div>
        <div class="stat"><div class="k">RSI(14)</div><div class="v ${cc(T.rsi>70?"var(--r)":T.rsi<30?"var(--g)":"var(--t1)")}">${T.rsi != null ? T.rsi.toFixed(1) : "—"}</div></div>
        <div class="stat"><div class="k">vs MA50</div><div class="v ${pnlc(T.ma50_dist)}">${fmtP1(T.ma50_dist)}</div></div>
        <div class="stat"><div class="k">vs MA200</div><div class="v ${pnlc(T.ma200_dist)}">${fmtP1(T.ma200_dist)}</div></div>
        <div class="stat"><div class="k">52W RANGE</div><div class="v">${T.range_52w_pct != null ? T.range_52w_pct.toFixed(0) + "%" : "—"}<small> of high</small></div></div>
        <div class="stat"><div class="k">REALIZED VOL</div><div class="v">${T.vol_20d != null ? T.vol_20d.toFixed(0) + "%" : "—"}</div></div>
        <div class="stat"><div class="k">52W HIGH</div><div class="v">$${fmt2(T.high_52w)}</div></div>
        <div class="stat"><div class="k">52W LOW</div><div class="v">$${fmt2(T.low_52w)}</div></div>
      </div>
    </div>

    <div class="tk-grid2">
      <div>
        <div class="mono t1 w6 c-3 ls18 mb2">FUNDAMENTALS (snapshot)</div>
        <div class="fund-grid">
          ${fundCard("FWD P/E",   F.fwd_pe, "", "forwardPE")}
          ${fundCard("TRAIL P/E", F.trail_pe)}
          ${fundCard("P/B",       F.pb)}
          ${fundCard("P/S",       F.ps)}
          ${fundCard("EV/EBITDA", F.ev_ebitda)}
          ${fundCard("PEG",       F.peg)}
          ${fundCard("REV GROWTH", F.rev_growth, "%", "revenueGrowth")}
          ${fundCard("GROSS MGN",  F.gross_mgn, "%")}
          ${fundCard("OP MGN",     F.op_mgn, "%")}
          ${fundCard("ROE",        F.roe, "%")}
          ${fundCard("FCF",        F.fcf_B ? "$" + F.fcf_B + "B" : null, "", "freeCashflow")}
          ${fundCard("MCAP",       F.mcap_B ? "$" + F.mcap_B + "B" : null)}
        </div>
      </div>
      <div>
        <div class="mono t1 w6 c-3 ls18 mb2">
          SCORE BREAKDOWN ${SC ? `· rank #${SC.rank} (${SC.percentile.toFixed(0)}th pct)` : ""}
        </div>
        ${SC ? `<div class="flx mono t1 w6 c-2 mb2 x34">
          <span>TECH ${SC.technical.toFixed(1)}/25</span>
          <span>FUND ${SC.fundamental.toFixed(1)}/25</span>
          <span class="c-1 w7">COMPOSITE ${SC.composite.toFixed(1)}/50</span>
        </div>` : ""}
        <div class="score-bars">
          ${SC && SC.components ? Object.entries({
            "MA200 dist":  SC.components.ma200_dist,
            "RSI":         SC.components.rsi,
            "Rel str 6m":  SC.components.rel_str_6m,
            "Fwd P/E":     SC.components.fwd_pe,
            "Rev growth":  SC.components.rev_growth,
            "Gross mgn":   SC.components.gross_mgn,
            "ROE":         SC.components.roe,
            "Op mgn":      SC.components.op_mgn,
          }).map(([k,v]) => scoreBar(k, v)).join("") : ""}
        </div>
      </div>
    </div>

    <div>
      <div class="mono t1 w6 c-3 ls18 mb2">
        TOP-10 60-DAY CORRELATIONS (red >0.7, yellow 0.4-0.7, green <0.4)
      </div>
      <div class="corr-row">
        ${Object.entries(C).slice(0, 10).map(([sym, v]) => `
          <div class="corr-card">
            <div class="tk">${sym}</div>
            <div class="v ${cc(corrColor(v))}">${v.toFixed(2)}</div>
          </div>`).join("") || "<div style='color:var(--t4)'>No correlation data</div>"}
      </div>
    </div>
  </div>`;
}

function hedgingNote(level){
  return ({
    "full":           "Tier policy: SPY put spreads when R<sub>t</sub> > 0.6 (50% notional, 0.5%/q budget); a standing VIX call tail hedge.",
    "moderate":       "Covered calls on +30% winners. SPY put spreads when R<sub>t</sub> > 0.7.",
    "light":          "Covered calls on +40% winners. Put spreads only when R<sub>t</sub> > 0.85.",
    "none_until_crisis": "No hedging. Exit to cash on R<sub>t</sub> > 0.85.",
  })[level] || level;
}

function renderTierDetail(tid){
  const t = tierSpec(tid);
  if (!t) return "";
  const live = S.tournament && S.tournament.history && S.tournament.history.length > 0
    ? S.tournament.history[S.tournament.history.length-1].tiers[tid] : null;

  let positions = [];
  if (live && live.positions) {
    positions = live.positions;
  } else if (tid === "5_werner") {
    positions = Object.entries(t.holdings).map(([tk, h]) => ({
      ticker: tk, shares: h.shares, cost_basis: h.cost, price: null, value: null, gain_pct: null, _note: h._note,
    }));
  } else if (S.holdings && S.holdings.tiers && S.holdings.tiers[tid]) {
    positions = S.holdings.tiers[tid].map(tk => ({ticker: tk}));
  }

  const targetCash = live ? live.target_cash_pct : (t.cash_floor * 100);
  const actualCash = live ? live.actual_cash_pct : (t.cash_floor * 100);
  const navStr = live ? "$" + fmt(live.nav) : "—";

  let h = `<div class="td-grid">
    <div>
      <div class="td-block">
        <div class="td-label">CASH ALLOCATION</div>
        <div class="flx x35">
          <div class="td-val">${actualCash.toFixed(0)}<small class="t1 c-3">% actual</small></div>
          <div class="mono t1 c-3">target ${targetCash.toFixed(0)}%</div>
        </div>
        <div class="gauge mt2">
          <div class="eq" style="width:${100-actualCash}%"></div>
          <div class="csh" style="width:${actualCash}%"></div>
        </div>
        <div class="td-sub">equity ${(100-actualCash).toFixed(0)}% · cash ${actualCash.toFixed(0)}% · NAV ${navStr}</div>
      </div>
      <div class="hedge"><span class="k">HEDGING</span>${hedgingNote(t.hedging)}</div>
    </div>
    <div>
      <div class="td-block">
        <div class="td-label">DESCRIPTION</div>
        <div class="serif t1 c-2 lh15">${t.description}</div>
        <div class="td-sub mt2">
          benchmark: <strong class="c-2">${t.benchmark}</strong> ·
          ${tid !== "5_werner" && t.n_holdings ? `target N=${t.n_holdings} · ` : ""}
          cash formula: <code>${t.cash_formula || `min(${t.cash_max}, ${t.cash_floor} + R · ${t.cash_slope})`}</code>
        </div>
      </div>
    </div>
  </div>`;

  h += `<table class="h-table"><tr>
    <th>TICKER</th><th title="entry state (DIAGNOSTIC): AVOID · WATCH · READY · READY-HALF">ENTRY STATE</th><th>SECTOR</th><th class="num">PRICE</th><th class="num">VALUE</th>
    ${tid==="5_werner" ? '<th class="num">COST</th><th class="num">GAIN</th>' : ''}
    <th class="num">WEIGHT</th><th></th>
  </tr>`;
  positions.forEach(p => {
    const sector = S.tickers && S.tickers[p.ticker] ? S.tickers[p.ticker].sector : "";
    const dim = (p.shares === 0 || p.value == null && tid==="5_werner");
    const open = (S.expandedTicker === p.ticker);
    h += `<tr class="tk-row ${open?"open":""}" data-tk="${p.ticker}"${dim ? ' class="dim"' : ''}>
      <td><strong class="c-1">${p.ticker}</strong></td>
      <td class="t1">${entryBadge(p.ticker)}</td>
      <td class="c-3 t1">${sector || "—"}</td>
      <td class="num">${p.price != null ? "$"+fmt2(p.price) : "—"}</td>
      <td class="num">${p.value != null ? "$"+fmt(p.value) : "—"}</td>
      ${tid==="5_werner" ? `
        <td class="num">${p.cost_basis ? "$"+fmt2(p.cost_basis) : "—"}</td>
        <td class="num ${p.gain_pct!=null?pnlc(p.gain_pct):'neut'}">${p.gain_pct!=null?fmtP1(p.gain_pct):"—"}</td>` : ""}
      <td class="num">${p.weight != null ? p.weight.toFixed(1) + "%" : "—"}</td>
      <td><span class="chev ${open?"open":""}">›</span></td>
    </tr>`;
    if (open) {
      h += `<tr><td colspan="${tid==="5_werner"?9:7}" class="p0 x36">${renderTickerDetail(p.ticker)}</td></tr>`;   // +1: the entry-state column
    }
  });
  h += `</table>`;
  if (S.holdings && S.holdings.turnover && S.holdings.turnover[tid] != null && tid !== "5_werner") {
    h += `<div class="mono t1 c-3 mt2 tar">
      monthly turnover (last rebalance): <strong class="c-2">${(S.holdings.turnover[tid]*100).toFixed(0)}%</strong>
    </div>`;
  }
  if (typeof renderTierLogs === "function") h += renderTierLogs(tid);   // audit order 30-Sept (4.3): trades and spells, newest first
  return h;
}

// ══ P1.4 hierarchy pieces ═══════════════════════════════════════════════════
// The deflated claim (Decision Memo 9 Sept 2026 §3). Exact wording is do-not-touch.
const DEFLATED_CLAIM = "A regime-conditional cash overlay reduced maximum drawdown by roughly half relative to buy-and-hold on point-in-time inputs over 2010 to 2026, against roughly 30 percent for the best one-line rule, at a cost of about half the benchmark's annualized return. Its return-per-volatility advantage over simple rules is positive on revised inputs and indistinguishable from zero on real-time inputs, and its drawdown advantage narrows to a few points in the 2008 crisis. The stock-selection component has no measurable skill. The graduated drawdown probability does not beat the base rate out of fold.";
function renderClaimSentence(){
  return `<p class="claim serif t3" data-claim="deflated">${DEFLATED_CLAIM}</p>`;
}
// Standing "moved by" line under the gauge (P3.5) — top three contributors with signed
// points and the interaction residual, from the nightly delta attribution.
function renderMovedByLine(){
  const a = S.regime && S.regime.attribution;   // P3.5: R_full delta attribution, written nightly by compute_regime_v2.py
  if (!a || !a.top3) return "";
  const sg = v => (v >= 0 ? "+" : "") + (+v).toFixed(2);
  const movers = a.top3.map(c => `<span class="nowrap" title="${c.label}: Δphi ${sg(c.delta_phi)} → ${sg(c.contribution_pts)} R_full points">${c.key} <span class="${c.contribution_pts >= 0 ? "c-neg" : "c-pos"}">${sg(c.contribution_pts)}</span></span>`).join(" · ");
  return `<div class="moved-by mono t1 c-2 mt2" title="${a.method || ""}">R<sub>full</sub> ${sg(a.delta_pts)} pts vs ${a.prev} — moved by: ${movers} · interaction residual ${sg(a.residual_pts)}</div>`;
}
// ── 16-Sept 1.5: stress scenarios beside the drawdown chart (fixed scenarios, 126-session betas) ──
function renderStressPanel(){
  const b = S.book; if (!b || !b.stress) return `<div class="stress-panel"><div class="fx-head mono t1 c-3">STRESS SCENARIOS</div><div class="mono t1 c-3">book.json not published</div></div>`;
  const money = v => "$" + fmt(Math.round(Math.abs(v)));
  const rows = b.stress.map(sc => `<tr title="${(sc.method || "").replace(/"/g, "'")}"><td class="c-2">${sc.label}</td><td class="num c-neg">−${money(sc.loss)}</td><td class="num c-neg w6">${(sc.share_nav * 100).toFixed(1)}%</td></tr>`).join("");
  return `<div class="stress-panel"><div class="fx-head mono t1 c-3">STRESS SCENARIOS · <span class="c-3">fixed · dollars and share of NAV ${money(b.nav)}</span>${holdingsPill()}${intradayBadge(b)}</div>
    <table class="stress-table"><tr><th>SCENARIO</th><th class="num">LOSS</th><th class="num">OF NAV</th></tr>${rows}</table>
    <div class="mono t1 c-3 mt1">index shocks through each holding's ${b.definitions ? b.definitions.window_sessions : 126}-session beta to the shocked index; thesis shocks from registry exposures · ${b.stress_note || "descriptive"}</div>
  </div>`;
}
function renderDrawdownCard(){      // P2.1: underwater chart, tier one
  const r = S.ddRange || "ALL";
  const btn = (p, t) => `<button class="period-btn ${r === p ? "on" : ""}" data-ddr="${p}">${t}</button>`;
  return `<div class="rcc-card dd-card">
    <div class="chart-head"><h3>DRAWDOWN FROM RUNNING PEAK · <span class="c-3 w5">all tiers and benchmarks, one axis</span></h3>
      <div class="periods">${btn("1M","1M")}${btn("3M","3M")}${btn("ALL","SINCE INCEPTION")}${btn("BT","BACKTEST")}</div></div>
    ${renderClaimSentence()}
    <div class="dd-body"><div><div class="chart-wrap dd-wrap"><canvas id="dd-chart"></canvas></div>
    <div class="chart-meta" id="dd-meta"></div></div>${renderStressPanel()}</div>
  </div>`;
}
const DD_LABEL = {"1_cap_pres":"CAP PRES","2_balanced":"BALANCED","3_aggressive":"AGGRESSIVE","4_tactical":"TACTICAL","5_werner":"WERNER",
                  spy:"SPY", qqq:"QQQ", "60_40":"60/40", sso:"SSO", tlt:"TLT"};
function renderDrawdownChart(){
  const ctx = document.getElementById("dd-chart"); if (!ctx) return;
  if (S.ddChart) { try { S.ddChart.destroy(); } catch (e) {} }
  const C = CHARTS.colors(); const range = S.ddRange || "ALL";
  const datasets = []; let meta = "";
  const mk = (k, pts, lastDepth) => {
    const isBench = !TIER_ORDER.includes(k);
    const color = isBench ? (C.bench[k] || C.n2) : C.tier[k];
    return {label: DD_LABEL[k] || k, data: pts, role: k === "4_tactical" ? "headline" : (isBench ? "benchmark" : "series"),
            borderColor: color, backgroundColor: CHARTS.alpha(color, isBench ? 0.05 : 0.12), fill: "origin", tension: 0,
            borderDash: isBench ? [3, 3] : undefined, directLabel: `${DD_LABEL[k] || k} ${lastDepth != null ? (lastDepth * 100).toFixed(1) + "%" : ""}`};
  };
  if (range === "BT") {
    const bt = S.backtestDD;
    if (!bt || !bt.dates) { ctx.parentElement.innerHTML = '<div class="ld">backtest drawdown companion not published yet</div>'; return; }
    const step = Math.max(1, Math.floor(bt.dates.length / 900));
    Object.entries(bt.series).forEach(([k, arr]) => {
      const pts = []; for (let i = 0; i < arr.length; i += step) if (arr[i] != null) pts.push({x: bt.dates[i], y: arr[i] * 100});
      if (pts.length) datasets.push(mk(k, pts, arr[arr.length - 1]));
    });
    meta = `backtest ${bt.window[0]} → ${bt.window[1]} · plotted every ${step === 1 ? "session" : step + " sessions"} · benchmarks weight 1, the regime tier (tactical) 2 · direct labels carry the current depth`;
  } else {
    const hist = (S.tournament && S.tournament.history) || [];
    const rows = range === "1M" ? hist.slice(-22) : range === "3M" ? hist.slice(-64) : hist;
    const t0 = rows.length ? rows[rows.length - 1].tiers[TIER_ORDER[0]] : null;
    if (!t0 || t0.drawdown == null) { ctx.parentElement.innerHTML = '<div class="ld">drawdown series not yet published (written by compute_nav.py at the next nightly)</div>'; return; }
    TIER_ORDER.forEach(tid => {
      const pts = rows.filter(r => r.tiers && r.tiers[tid] && r.tiers[tid].drawdown != null).map(r => ({x: r.date, y: r.tiers[tid].drawdown * 100}));
      if (pts.length) datasets.push(mk(tid, pts, rows[rows.length - 1].tiers[tid] && rows[rows.length - 1].tiers[tid].drawdown));
    });
    ["spy", "qqq", "60_40", "sso", "tlt"].forEach(b => {
      const pts = rows.filter(r => r.benchmarks && r.benchmarks[b] && r.benchmarks[b].drawdown != null).map(r => ({x: r.date, y: r.benchmarks[b].drawdown * 100}));
      if (pts.length) datasets.push(mk(b, pts, rows[rows.length - 1].benchmarks[b].drawdown));
    });
    meta = `live since inception ${hist.length ? hist[0].date : "—"} · ${rows.length} sessions shown · depth below the running peak since inception · benchmarks weight 1, the regime tier (tactical) 2`;
  }
  const narrow = window.matchMedia && window.matchMedia("(max-width: 820px)").matches;   // P5.1: fewer ticks on mobile
  S.ddChart = CHARTS.make(ctx, {
    type: "line", data: {datasets},
    options: {
      layout: {padding: {right: narrow ? 70 : 96}},
      scales: {x: {type: "time", time: {unit: range === "BT" ? "year" : (range === "1M" ? "day" : "month")}, ticks: {maxTicksLimit: narrow ? 4 : 10}},
               y: {max: 0, ticks: {callback: v => v.toFixed(0) + "%", maxTicksLimit: narrow ? 4 : 8}}},
      plugins: {tooltip: {callbacks: {label: c => ` ${c.dataset.label}: ${c.parsed.y.toFixed(2)}%`}}},
    },
  });
  const m = document.getElementById("dd-meta"); if (m) m.textContent = meta;
}
// ── P2.3 Thesis treemap: squarified, plain SVG, tokens only ─────────────────
// Rectangles sized by portfolio weight, filled from the five-step diverging scale by one-day
// return (bounded ±3%), grouped by thesis with a label and a hairline separator; cash is a neutral
// rectangle; provisional and partial memberships render dashed; positions below 0.5% aggregate
// into an "other" rectangle per thesis. The caption states N_eff for the selected portfolio.
function squarify(items, x, y, w, h){
  const out = []; let rest = items.filter(i => i.area > 0).slice().sort((a, b) => b.area - a.area);
  const total = rest.reduce((s, i) => s + i.area, 0); if (!total || w <= 0 || h <= 0) return out;
  const k = (w * h) / total; rest = rest.map(i => ({...i, a: i.area * k}));
  let rx = x, ry = y, rw = w, rh = h, row = [];
  const worst = (r, len) => { const s = r.reduce((a, i) => a + i.a, 0); const mx = Math.max(...r.map(i => i.a)), mn = Math.min(...r.map(i => i.a)); return Math.max(len * len * mx / (s * s), s * s / (len * len * mn)); };
  const lay = r => { const s = r.reduce((a, i) => a + i.a, 0);
    if (rw >= rh) { const cw = s / rh; let cy = ry; r.forEach(i => { const ch = i.a / cw; out.push({...i, x: rx, y: cy, w: cw, h: ch}); cy += ch; }); rx += cw; rw -= cw; }
    else { const ch = s / rw; let cx = rx; r.forEach(i => { const cw = i.a / ch; out.push({...i, x: cx, y: ry, w: cw, h: ch}); cx += cw; }); ry += ch; rh -= ch; } };
  while (rest.length) { const len = Math.max(1e-6, Math.min(rw, rh)); const it = rest[0];
    if (!row.length || worst([...row, it], len) <= worst(row, len)) { row.push(it); rest = rest.slice(1); } else { lay(row); row = []; } }
  if (row.length) lay(row);
  return out;
}
function dvClass(ret){   // five steps over [−3%, +3%], clamped
  if (ret == null || !isFinite(ret)) return "dv0";
  const p = Math.max(-3, Math.min(3, ret * 100));
  return p < -1.8 ? "dv-2" : p < -0.6 ? "dv-1" : p <= 0.6 ? "dv0" : p <= 1.8 ? "dv1" : "dv2";
}
function treemapData(tid){
  const h = (S.tournament && S.tournament.history) || []; if (h.length < 1) return null;
  const last = h[h.length - 1], prev = h.length > 1 ? h[h.length - 2] : null;
  const td = last.tiers && last.tiers[tid]; if (!td) return null;
  const prevTier = prev && prev.tiers && prev.tiers[tid];
  const prevPx = Object.assign({}, prevTier && prevTier.prices_snapshot ? prevTier.prices_snapshot : {},
    ...(prevTier && prevTier.positions ? prevTier.positions.filter(p => p.price).map(p => ({[p.ticker]: p.price})) : []));
  const nav = (td.equity || 0) + (td.cash || 0); if (!(nav > 0)) return null;
  const reg = (S.thesisReg && S.thesisReg.theses) || {};
  const ledger = (S.provLedger && S.provLedger.entries) || {};
  const provNames = new Set(((S.thesis && S.thesis.tiers && S.thesis.tiers[tid]) || {}).provisional_names || []);
  const groups = {};
  (td.positions || []).filter(p => p.value > 0).forEach(p => {
    const w = p.value / nav; const pp = prevPx[p.ticker]; const ret = (pp && p.price) ? p.price / pp - 1 : null;
    let best = null, bw = 0, multi = 0, bsub = null;
    Object.entries(reg).forEach(([k, th]) => { const mv = th.members && th.members[p.ticker]; const mw = memberWeight(mv); if (mw) { multi++; if (mw > bw) { bw = mw; best = k; bsub = th.sub_theses ? (memberSub(mv) || "other") : null; } } });
    let provisional = false;
    if (!best && provNames.has(p.ticker) && ledger[p.ticker] && ledger[p.ticker].proposed) {
      const [k, mw] = Object.entries(ledger[p.ticker].proposed).sort((a, b) => b[1] - a[1])[0]; best = k; bw = mw; provisional = true;
    }
    const key = best ? (bsub ? `${best}/${bsub}` : best) : "unclassified";   // v4: sub-thesis resolution (display only)
    (groups[key] = groups[key] || []).push({ticker: p.ticker, w, ret, mw: best ? bw : null, partial: !!best && bw < 0.999, multi, provisional});
  });
  const cashW = (td.cash || 0) / nav;
  const neff = (S.thesis && S.thesis.tiers && S.thesis.tiers[tid] && S.thesis.tiers[tid].n_eff) || null;
  return {groups, cashW, nav, neff, date: last.date, n: (td.positions || []).filter(p => p.value > 0).length};
}
function renderTreemapCard(){
  const sel = S.tmSel || "5_werner";
  const d = treemapData(sel);
  const btn = (id, t) => `<button class="period-btn ${sel === id ? "on" : ""}" data-tm="${id}">${t}</button>`;
  const selector = `<div class="periods">${btn("5_werner", "BOOK")}${TIER_ORDER.filter(t => t !== "5_werner").map(t => btn(t, (tierSpec(t) || {}).short || t)).join("")}</div>`;
  if (!d) return `<div class="rcc-card tm-card"><div class="chart-head"><h3>THESIS TREEMAP</h3>${selector}</div><div class="ld">no positions for this selection</div></div>`;
  // 1-Oct-2026: on a phone the 1000-unit frame scaled 12-unit labels down to ~4px; lay out in a
  // narrow frame there so the labels render near their nominal size
  const narrowTm = window.matchMedia && window.matchMedia("(max-width: 820px)").matches;
  const W = narrowTm ? 400 : 1000, H = narrowTm ? 460 : 440, LBL = 16;
  const fitTxt = (t, w) => { const n = Math.max(4, Math.floor((w - 12) / 8.3)); /* 12-unit mono + .08em tracking ≈ 8.2 units a character */ return t.length > n ? t.slice(0, n - 1) + "…" : t; };
  const gitems = Object.entries(d.groups).map(([k, arr]) => ({key: k, area: arr.reduce((s, p) => s + p.w, 0)}));
  if (d.cashW > 0) gitems.push({key: "cash", area: d.cashW});
  const grects = squarify(gitems, 0, 0, W, H);
  let svg = "";
  const parentTot = {}; gitems.forEach(g => { const pk = parentOf(g.key); parentTot[pk] = (parentTot[pk] || 0) + g.area; });
  grects.forEach(g => {
    const label = thesisLabel(parentOf(g.key)) + (g.key.includes("/") ? " · " + subLabel(g.key) : "");
    svg += `<rect class="tm-group" x="${g.x.toFixed(1)}" y="${g.y.toFixed(1)}" width="${g.w.toFixed(1)}" height="${g.h.toFixed(1)}"></rect>`;
    if (g.key === "cash") {
      svg += `<rect class="tm-rect cash" x="${(g.x + 2).toFixed(1)}" y="${(g.y + 2).toFixed(1)}" width="${Math.max(0, g.w - 4).toFixed(1)}" height="${Math.max(0, g.h - 4).toFixed(1)}"><title>cash · ${(d.cashW * 100).toFixed(1)}% of NAV</title></rect>`;
      if (g.w > 60 && g.h > 24) svg += `<text class="tm-t" x="${(g.x + 8).toFixed(1)}" y="${(g.y + 18).toFixed(1)}">cash ${(d.cashW * 100).toFixed(0)}%</text>`;
      return;
    }
    if (g.w > 70 && g.h > LBL + 8) svg += `<text class="tm-glabel" x="${(g.x + 6).toFixed(1)}" y="${(g.y + 12).toFixed(1)}"><title>${label} · ${(g.area * 100).toFixed(1)}%</title>${fitTxt(`${label.toUpperCase()} · ${(g.area * 100).toFixed(0)}%${g.key.includes("/") && g.w > 240 ? ` (${thesisLabel(parentOf(g.key)).toUpperCase()} ${(parentTot[parentOf(g.key)] * 100).toFixed(0)}%)` : ""}`, g.w)}</text>`;
    const members = d.groups[g.key] || [];
    const big = members.filter(m => m.w >= 0.005), small = members.filter(m => m.w < 0.005);
    const items = big.map(m => ({key: m.ticker, area: m.w, m}));
    if (small.length) items.push({key: "other", area: small.reduce((s, m) => s + m.w, 0), other: small});
    const inner = squarify(items, g.x + 2, g.y + (g.h > LBL + 8 ? LBL : 2), Math.max(0, g.w - 4), Math.max(0, g.h - (g.h > LBL + 8 ? LBL + 2 : 4)));
    inner.forEach(r => {
      const m = r.m;
      const cls = m ? dvClass(m.ret) : "dv0";
      const dashed = m && (m.provisional || m.partial);
      const title = m
        ? `${m.ticker} · weight ${(m.w * 100).toFixed(1)}% · 1-day ${m.ret != null ? ((m.ret >= 0 ? "+" : "") + (m.ret * 100).toFixed(2) + "%") : "n/a"} · thesis ${label}${m.mw != null ? " · membership " + m.mw.toFixed(2) : ""}${m.provisional ? " · PROVISIONAL" : ""}${m.partial ? " · partial" : ""}${m.multi > 1 ? " · in " + m.multi + " theses" : ""}`
        : `other · ${r.other.length} position${r.other.length === 1 ? "" : "s"} below 0.5% · ${(r.area * 100).toFixed(2)}% combined · ${r.other.map(o => o.ticker).join(", ")}`;
      svg += `<rect class="tm-rect ${cls}${dashed ? " prov" : ""}" x="${r.x.toFixed(1)}" y="${r.y.toFixed(1)}" width="${Math.max(0, r.w - 1).toFixed(1)}" height="${Math.max(0, r.h - 1).toFixed(1)}"><title>${title}</title></rect>`;
      if (r.w > 44 && r.h > 26) svg += `<text class="tm-t" x="${(r.x + 5).toFixed(1)}" y="${(r.y + 15).toFixed(1)}">${m ? m.ticker : "other"}</text>`;
      if (r.w > 60 && r.h > 40 && m) svg += `<text class="tm-s" x="${(r.x + 5).toFixed(1)}" y="${(r.y + 29).toFixed(1)}">${(m.w * 100).toFixed(1)}% · ${m.ret != null ? ((m.ret >= 0 ? "+" : "") + (m.ret * 100).toFixed(1) + "%") : "—"}</text>`;
    });
  });
  const legend = ["dv-2", "dv-1", "dv0", "dv1", "dv2"].map((c, i) => `<span class="tm-lg ${c}"></span>${["≤ −1.8%", "−1.8…−0.6", "±0.6", "0.6…1.8", "≥ 1.8%"][i]}`).join(" ");
  const subKeys = Object.keys(d.groups).filter(k => k.includes("/"));
  const parents = {}; subKeys.forEach(k => { const pk = parentOf(k); (parents[pk] = parents[pk] || []).push(k); });
  const parentLine = Object.entries(parents).map(([pk, ks]) => `<strong class="c-1">${thesisLabel(pk)} ${(parentTot[pk] * 100).toFixed(0)}%</strong> = ${ks.sort((a, b) => (d.groups[b].reduce((s_, m) => s_ + m.w, 0)) - (d.groups[a].reduce((s_, m) => s_ + m.w, 0))).map(k => `${subLabel(k)} ${(d.groups[k].reduce((s_, m) => s_ + m.w, 0) * 100).toFixed(0)}%`).join(" · ")}`).join(" ; ");
  return `<div class="rcc-card tm-card">
    <div class="chart-head"><h3>THESIS TREEMAP · <span class="c-3 w5">${sel === "5_werner" ? "the book" : (tierSpec(sel) || {}).short} · weight by area, one-day return by colour · sub-thesis resolution</span>${asOfBadge(d.date)}</h3>${selector}</div>
    <svg class="tm-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="thesis treemap">${svg}</svg>
    <div class="chart-meta">N<sub>eff</sub> = <strong class="c-1">${d.neff != null ? d.neff : "—"}</strong> effective theses across ${d.n} positions · grouped by thesis and, inside ai_infra, by sub-thesis (registry v${(S.thesisReg && S.thesisReg.version) || "—"}; display only, the parent bucket sizes) · ${parentLine ? "parent totals: " + parentLine + " · " : ""}dashed = provisional or partial membership · ${legend} · bounded ±3% daily</div>
  </div>`;
}
// P2.2 — "What the overlay has shown": the deflated claim verbatim, both C3 verdicts on one line
// with the amendment noted, the C3 drawdown-path chart, and the "second opinion today" strip
// (regime reading beside the three rules' current states; descriptive — no rule drives sizing).
function renderRetirementPanel(){
  const r = S.c3; if (!r || !r.decision) return "";
  const d2 = r.decision_v2 || {}; const ci = d2.paired_diff_return_per_vol_ci90 || [];
  const sg = x => (x >= 0 ? "+" : "") + (+x).toFixed(3);
  const verdictLine = `<div class="mono t1 c-2 mt2" title="v1 (c39e2aa): margin over the best rule had to exceed the half-width of the regime's own 90% interval — a bar no monthly overlay on this window could clear. v2 (amended 9-Sept-2026 after the v1 result): paired 90% interval above zero. Both verdicts stay on record.">
    <span class="c-neg w6">v1: fail</span> on a rule with no discriminating power; <span class="c-pos w6">v2: pass</span>, paired difference [${ci.length ? sg(ci[0]) + ", " + sg(ci[1]) : "—"}] · amendment made after the v1 result, disclosed in reports/c3_registration_v2.md
  </div>`;
  let strip = "";
  const cp = S.comparators;
  if (cp && cp.rules && cp.rules.sma10 && cp.rules.tsmom_12_1 && cp.rules.vol_target_10) {
    const rg = cp.regime || {}, sm = cp.rules.sma10, tm = cp.rules.tsmom_12_1, vt = cp.rules.vol_target_10;
    const expCls = e => e >= 0.999 ? "c-pos" : e <= 0.001 ? "c-neg" : "c-warn";
    const bpr = (cp.book_posture && cp.book_posture.rows) || [];
    const trRow = f => bpr.find(f);
    const tr = r => r && r.book_share != null ? ` · <span class="c-2">at your beta ${(r.book_share * 100).toFixed(0)}%</span>` : "";
    const actualTxt = cp.book_posture && cp.book_posture.actual_equity_share != null ? ` · actual ${(cp.book_posture.actual_equity_share * 100).toFixed(0)}%` : "";
    const cell = (k, v, s, cls) => `<div class="so-cell"><div class="k">${k}</div><div class="v ${cls || ""}">${v}</div><div class="s">${s}</div></div>`;
    strip = `<div class="so-strip">
      ${cell("REGIME INDEX · READING", `${rg.state || "—"} · R<sub>full</sub> ${rg.R_full != null ? (+rg.R_full).toFixed(3) : "—"}`, `tier-4 exposure ${rg.exposure != null ? (rg.exposure * 100).toFixed(0) + "%" : "—"}${tr(trRow(r => r.tier === "4_tactical"))}${actualTxt} · as of ${rg.as_of || cp.session_date}`, cc(ewColor(rg.state)))}
      ${cell("10-MONTH SMA · MONTHLY", String(sm.state || "—").toUpperCase(), `P<sub>m</sub> ${sm.computed_from.P_m} vs SMA10 ${(+sm.computed_from.sma10).toFixed(2)} at ${sm.computed_from.month_end_date}${sm.evaluation && sm.evaluation.next_evaluation ? " · next " + sm.evaluation.next_evaluation : ""}${tr(trRow(r => r.id === "sma10"))}`, expCls(sm.exposure))}
      ${cell("12-1 MOMENTUM · MONTHLY", String(tm.state || "—").toUpperCase(), `12-1 return ${(tm.computed_from.ret_12_1 * 100).toFixed(1)}% (${tm.computed_from.P_m_12_date} → ${tm.computed_from.P_m_1_date})${tm.evaluation && tm.evaluation.next_evaluation ? " · next " + tm.evaluation.next_evaluation : ""}${tr(trRow(r => r.id === "tsmom_12_1"))}`, expCls(tm.exposure))}
      ${cell("10% VOL TARGET · DAILY", `${(vt.exposure * 100).toFixed(0)}% exposure`, `σ<sub>60</sub> ${(vt.computed_from.sigma_ann * 100).toFixed(1)}% ann. through ${vt.computed_from.through} · min(1, 10% / σ)${tr(trRow(r => r.id === "vol_target_10"))}${(() => { const v = trRow(r => r.kind === "vol_target" && r.target === 0.1); return v && v.book_share_on_book_vol != null ? ` · on the book's own vol ${(v.book_share_on_book_vol * 100).toFixed(0)}%` : ""; })()}`, expCls(vt.exposure))}
    </div>
    <div class="mono t1 c-3 mt1">second opinion today · ${cp.note || "descriptive; no rule drives sizing"} · constants from ${cp.registration || "reports/c3_registration.md §B6"} · session ${cp.session_date}</div>`;
  }
  return `<div class="rcc-card ret-panel"><h3>WHAT THE OVERLAY HAS SHOWN · <span class="c-3 w5">pre-registered test C3, both verdicts of record</span>${asOfBadge(cp && cp.session_date)}</h3>
    ${renderClaimSentence()}
    ${verdictLine}
    <div class="chart-wrap c3-wrap"><canvas id="c3-chart"></canvas></div>
    <div class="chart-meta" id="c3-meta"></div>
    ${strip}
  </div>`;
}
// ── 16-Sept 1.4 / Phase 4: posture versus every rule, at the book's beta (descriptive) ──
function renderPostureCard(){
  const cp = S.comparators, bp = cp && cp.book_posture; if (!bp) return "";
  const p1 = v => v == null ? "—" : (v * 100).toFixed(0) + "%";
  const actual = bp.actual_equity_share;
  const rows = (bp.rows || []).map(r => {
    const sub = r.kind === "regime_schedule"
      ? `<div class="c-3 t1">full deployment (cash at the floor): index ${p1(r.full_deployment_index_share)} → book ${p1(r.full_deployment_book_share)}</div>`
      : r.kind === "vol_target" ? `<div class="c-3 t1">on the book's own realised volatility (σ<sub>60</sub> ${(bp.sigma_book_60 * 100).toFixed(1)}%): <strong class="c-1">${p1(r.book_share_on_book_vol)}</strong> · 126-session σ ${p1(r.book_share_on_book_vol_126)}</div>` : (r.state ? `<div class="c-3 t1">state ${r.state}</div>` : "");
    const gap = (r.book_share != null && actual != null) ? actual - r.book_share : null;
    return `<tr title="${(r.label || "").replace(/"/g, "'")}"><td class="c-2">${r.rule}${sub}</td><td class="num">${p1(r.index_share)}</td><td class="num c-1 w6">${p1(r.book_share)}</td><td class="num">${p1(actual)}${gap != null ? ` <span class="${gap > 0 ? "c-warn" : "c-3"} t1">(${gap >= 0 ? "+" : ""}${(gap * 100).toFixed(0)} pp)</span>` : ""}</td></tr>`;
  }).join("");
  return `<div class="rcc-card posture-card"><h3>BOOK-AWARE SIZING, DESCRIPTIVE · <span class="c-3 w5">posture versus every rule at the book's beta · equity-sleeve β ${(+bp.beta_equity_sleeve).toFixed(2)} (${bp.beta_with_cash != null ? (+bp.beta_with_cash).toFixed(2) : "—"} with cash) · updated nightly</span>${asOfBadge(cp.session_date)}</h3>
    <div class="tbl-scroll"><table class="posture-table"><tr><th>RULE</th><th class="num" title="the equity share the rule implies for a beta-one index">INDEX (β = 1)</th><th class="num" title="index share ÷ equity-sleeve beta, capped at 100 percent">TRANSLATED TO A BOOK OF YOUR BETA</th><th class="num">ACTUAL EQUITY SHARE</th></tr>${rows}</table></div>
    <div class="chart-meta">the regime schedule's cash share for each tier scaled by the equity sleeve's beta; volatility targeting at 10 and 15 percent on the book's realised volatility; each beside the actual share · ${bp.translation} · regime schedule at R<sub>full</sub> ${cp.regime && cp.regime.R_full} · <strong class="c-1">descriptive; no rule drives this book.</strong> no execution path · session ${cp.session_date}</div>
  </div>`;
}
function renderC3PathChart(){
  const ctx = document.getElementById("c3-chart"); if (!ctx) return;
  const p = S.c3Paths;
  if (!p || !p.dates) { ctx.parentElement.innerHTML = '<div class="ld">C3 drawdown paths not published</div>'; return; }
  if (S.c3Chart) { try { S.c3Chart.destroy(); } catch (e) {} }
  const C = CHARTS.colors();
  const spec = [["regime", "regime index, tier-4 sizing", C.tier["4_tactical"], "headline"],
                ["best_rule", `best rule: ${p.best_rule_label}`, C.info, "series"],
                ["buy_and_hold", "buy-and-hold", C.n1, "benchmark"]];
  const datasets = spec.map(([k, label, color, role]) => ({
    label, role, borderColor: color, backgroundColor: CHARTS.alpha(color, role === "benchmark" ? 0.05 : 0.12), fill: "origin", tension: 0,
    borderDash: role === "benchmark" ? [3, 3] : undefined,
    data: p.dates.map((d, i) => ({x: d, y: p.series[k][i] * 100})),
    directLabel: `${label.split(",")[0].split(":")[0]} min ${(p.min[k] * 100).toFixed(0)}%`,
  }));
  S.c3Chart = CHARTS.make(ctx, {type: "line", data: {datasets}, options: {
    layout: {padding: {right: 118}},
    scales: {x: {type: "time", time: {unit: "year"}}, y: {max: 0, ticks: {callback: v => v.toFixed(0) + "%"}}},
    plugins: {tooltip: {callbacks: {label: c => ` ${c.dataset.label}: ${c.parsed.y.toFixed(1)}%`}}},
  }});
  const m = document.getElementById("c3-meta");
  if (m) m.textContent = `drawdown paths from the C3 results (tier-4 overlay, ${p.window[0]} → ${p.window[1]}, net of costs, ${p.sampling}) · max drawdown: regime ${(p.min.regime * 100).toFixed(1)}% · ${p.best_rule_label} ${(p.min.best_rule * 100).toFixed(1)}% · buy-and-hold ${(p.min.buy_and_hold * 100).toFixed(1)}%`;
}
// ── P3.3 Style-factor exposure strip (per-name 252-session regression, weight-averaged) ──
function renderFactorStrip(key){
  const f = S.factors; const p = f && f.portfolios && f.portfolios[key];
  if (!p || !p.exposure) return `<div class="fx-strip"><div class="fx-head mono t1 c-3">FACTOR EXPOSURE</div><div class="mono t1 c-3">${f ? "no exposure for this portfolio" : "factor_exposure.json not published"}</div></div>`;
  const rows = [["market", "MARKET"], ["size", "SIZE"], ["value", "VALUE"], ["momentum", "MOMENTUM"]];
  const maxAbs = Math.max(1, ...rows.map(([k]) => Math.abs(p.exposure[k] || 0)));
  const sg = v => (v >= 0 ? "+" : "") + v.toFixed(2);
  return `<div class="fx-strip" title="${(f.method || "").replace(/"/g, "'")}">
    <div class="fx-head mono t1 c-3">FACTOR EXPOSURE · <span class="c-3">${f.label || "estimated, 252-session regression"}</span></div>
    ${rows.map(([k, l]) => { const v = p.exposure[k] || 0; const w = Math.abs(v) / maxAbs * 50;
      return `<div class="fx-row"><span class="fx-k mono t1 c-2">${l}</span><span class="fx-bar"><span class="fx-zero"></span><span class="fx-fill ${v >= 0 ? "bg-info" : "bg-warn"}" style="left:${(v >= 0 ? 50 : 50 - w).toFixed(1)}%;width:${w.toFixed(1)}%"></span></span><span class="fx-v mono t1 c-1">${sg(v)}</span></div>`; }).join("")}
    <div class="mono t1 c-3 mt1">proxies: SPY · IWM−SPY · IWD−IWF · MTUM−SPY · weight-averaged betas over ${(p.covered_weight * 100).toFixed(0)}% of equity, ${p.n_names} names${p.excluded && p.excluded.length ? " · excluded " + p.excluded.join(", ") : ""} · session ${f.session_date}</div>
  </div>`;
}
// ── P3.2 The book: positions (weight, cost basis, price, unrealized P&L, one-day), totals,
//    thesis exposure bars + N_eff, and the factor strip beside them. Sorted by weight. ──
function thesisOf(tk){
  const reg = (S.thesisReg && S.thesisReg.theses) || {};
  const hits = Object.entries(reg).filter(([k, t]) => t.members && t.members[tk] != null).sort((a, b) => memberWeight(b[1].members[tk]) - memberWeight(a[1].members[tk]));
  if (!hits.length) return "unclassified";
  const [k, t] = hits[0]; const mw = memberWeight(t.members[tk]), sub = memberSub(t.members[tk]);
  return `${thesisLabel(k)}${sub ? " · " + subLabel(k + "/" + sub) : ""}${mw < 0.999 ? " · " + mw.toFixed(2) : ""}`;
}
function renderBookPanel(){
  const b = S.book;
  const h = S.tournament && S.tournament.history; if (!b && !(h && h.length)) return "";
  const money = v => v == null ? "—" : "$" + fmt(Math.round(Math.abs(v)));
  const pct = (v, nd = 1) => v == null ? "—" : `<span class="${v >= 0 ? "c-pos" : "c-neg"}">${v >= 0 ? "+" : ""}${(v * 100).toFixed(nd)}%</span>`;
  const pl = v => v == null ? "—" : `<span class="${v >= 0 ? "c-pos" : "c-neg"}">${v >= 0 ? "+" : "−"}${money(v)}</span>`;
  const n2 = v => v == null ? "—" : (+v).toFixed(2);
  const p1 = v => v == null ? "—" : (v * 100).toFixed(1) + "%";
  const th = S.thesis && S.thesis.tiers && S.thesis.tiers["5_werner"];
  const exp = (b && b.portfolio && b.portfolio.thesis_exposure) || (th && th.exposure_invested) || {};
  const expSub = (th && th.exposure_sub) || {};
  const bars = Object.entries(exp).sort((a, c) => c[1] - a[1]).map(([k, v]) => {
    const subs = Object.entries(expSub).filter(([sk]) => parentOf(sk) === k).sort((a, c) => c[1] - a[1]);
    const fill = subs.length
      ? subs.map(([sk, sw]) => `<span class="${cc(thesisColor(k), 'bg')} ${subShade(sk)} ib" style="width:${(sw * 100).toFixed(1)}%" title="${subLabel(sk)} ${(sw * 100).toFixed(1)}%"></span>`).join("")
      : `<span class="${cc(thesisColor(k), 'bg')}" style="width:${(v * 100).toFixed(1)}%"></span>`;
    const subTxt = subs.length ? `<div class="mono t1 c-3">${subs.map(([sk, sw]) => `${subLabel(sk)} ${(sw * 100).toFixed(0)}%`).join(" · ")}</div>` : "";
    return `<div class="th-exp-row"><span class="th-exp-k mono t1 c-2">${thesisLabel(k)}${subTxt}</span><span class="th-exp-bar">${fill}</span><span class="th-exp-v mono t1 c-1">${(v * 100).toFixed(0)}%</span></div>`; }).join("");
  if (!b) {   // fallback: the tournament row only (book.json not yet published)
    const last = h[h.length - 1], w = last.tiers && last.tiers["5_werner"]; if (!w) return "";
    const pos = (w.positions || []).filter(p => p.value > 0).sort((a, c) => c.value - a.value);
    const nav = pos.reduce((s_, p) => s_ + p.value, 0) + (w.cash || 0);
    return `<div class="rcc-card book-panel"><h3>THE BOOK · <span class="c-3 w5">positions from data/holdings.json, the only holdings source · analytics arrive with book.json at the next nightly</span>${asOfBadge(last.date)}</h3>
      <div class="tbl-scroll"><table class="book-table"><tr><th>TICKER</th><th class="num">WEIGHT</th><th class="num">SHARES</th><th class="num">COST</th><th class="num">PRICE</th><th class="num">GAIN</th></tr>
      ${pos.map(p => `<tr><td class="mono t2 c-1 w6">${p.ticker}</td><td class="num">${(p.value / nav * 100).toFixed(1)}%</td><td class="num">${p.shares}</td><td class="num">${p.cost_basis != null ? p.cost_basis.toFixed(2) : "—"}</td><td class="num">${p.price.toFixed(2)}</td><td class="num">${p.gain_pct != null ? pct(p.gain_pct / 100) : "—"}</td></tr>`).join("")}</table></div></div>`;
  }
  const P = b.portfolio || {};
  const pos = (b.positions || []).slice().sort((a, c) => (c.value || 0) - (a.value || 0));
  const rows = pos.map(p => {
    if (p.value == null) return `<tr><td class="mono t2 c-1 w6">${p.ticker}</td><td colspan="15" class="c-3 t1">${p.status} · ${p.shares} shares at cost ${p.cost_basis} · excluded from the analytics (no price source carries this name)</td></tr>`;
    const insuff = p.insufficient_history;
    return `<tr${insuff ? ' class="dim"' : ""}>
      <td class="mono t2 c-1 w6">${p.ticker}${insuff ? ` <span class="c-warn t1" title="${p.status}">·</span>` : ""}</td>
      <td class="num">${p1(p.share_nav)}</td><td class="num">${p1(p.share_equity)}</td>
      <td class="num">${p.shares}</td><td class="num">${p.cost_basis.toFixed(2)}</td><td class="num">${p.price.toFixed(2)}</td>
      <td class="num">${money(p.value)}</td><td class="num">${pl(p.unrealized)}</td><td class="num">${pct(p.return_vs_cost)}</td>
      <td class="num" title="annualised, ${b.definitions ? b.definitions.window_sessions : 126} sessions">${p1(p.vol_ann)}</td>
      <td class="num" title="OLS to SPY, n ${p.beta_spy && p.beta_spy.n_obs}">${n2(p.beta_spy && p.beta_spy.beta)}</td>
      <td class="num" title="OLS to SMH, n ${p.beta_smh && p.beta_smh.n_obs}">${n2(p.beta_smh && p.beta_smh.beta)}</td>
      <td class="num" title="share of portfolio variance, cash at zero volatility">${p.risk_share == null ? "—" : `<span class="risk-cell"><span class="risk-fill bg-warn" style="width:${Math.min(100, p.risk_share * 100).toFixed(0)}%"></span><span>${p1(p.risk_share)}</span></span>`}</td>
      <td class="num" title="from the one-year peak ${p.peak_1y_date || ""}">${pct(p.drawdown_1y)}</td>
      <td class="num" title="distance from the 200-day average">${pct(p.ma200_dist)}</td>
      <td class="num">${p.rsi14 == null ? "—" : p.rsi14.toFixed(0)}</td>
      <td class="c-3 t1">${thesisOf(p.ticker)}${insuff ? ` · <span class="c-warn">${p.status}</span>` : ""}</td></tr>`;
  }).join("");
  const cell = (k, v, sub, cls) => `<div class="so-cell"><div class="k">${k}</div><div class="v ${cls || "c-1"}">${v}</div><div class="s">${sub || ""}</div></div>`;
  const stats = `<div class="so-strip book-stats">
    ${cell("VOLATILITY · ANNUALISED", `${p1(P.vol_ann_with_cash)} <span class="c-3">with cash</span> · ${p1(P.vol_ann_equity)} <span class="c-3">equity sleeve</span>`, `126 sessions · 60-session sleeve figure ${p1(P.vol_ann_equity_60)}`)}
    ${cell("BETA TO SPY", `${n2(P.beta_spy_with_cash)} <span class="c-3">with cash</span> · ${n2(P.beta_spy_equity)} <span class="c-3">equity sleeve</span>`, `Σ w β over position betas; sleeve regression ${n2(P.beta_spy_equity_regression)} · to SMH ${n2(P.beta_smh_with_cash)} with cash, ${n2(P.beta_smh_equity)} sleeve`)}
    ${cell("EFFECTIVE THESES · SIZING FIGURE", `${P.effective_theses != null ? P.effective_theses : "—"}`, `1/Σw² over the registry exposure of the invested sleeve · this is the figure used for sizing`)}
    ${cell("EFFECTIVE BETS · CORRELATION", `${P.effective_bets != null ? P.effective_bets : "—"}`, `exponential entropy of the equity correlation eigenvalues · ${P.effective_bets_note || ""}`)}
  </div>`;
  return `<div class="rcc-card book-panel"><h3>THE BOOK · <span class="c-3 w5">positions from data/holdings.json (${b.source && b.source.holdings_as_of ? "holdings as of " + b.source.holdings_as_of : "the only holdings source"}) · ${b.intraday ? "values live; risk windows through " + b.as_of : "analytics through " + b.as_of}</span>${holdingsPill()}${intradayBadge(b)}</h3>
    <div class="mono t1 c-3 mb2">NAV ${money(b.nav)} = equity ${money(b.equity)} + cash ${money(b.cash)} · invested ${p1(b.invested_share)} · window ${b.window ? b.window.start + " → " + b.window.end : ""} · ${b.note || ""}${(b.warnings || []).length ? ` · <span class="c-warn">${b.warnings.join("; ")}</span>` : ""}</div>
    <div class="tbl-scroll"><table class="book-table">
      <tr><th>TICKER</th><th class="num">NAV %</th><th class="num">EQ %</th><th class="num">SHARES</th><th class="num">COST</th><th class="num">PRICE</th><th class="num">VALUE</th><th class="num">UNREAL.</th><th class="num">vs COST</th><th class="num">VOL</th><th class="num">β SPY</th><th class="num">β SMH</th><th class="num">RISK SHARE</th><th class="num">DD 1Y</th><th class="num">vs MA200</th><th class="num">RSI</th><th>THESIS</th></tr>
      ${rows}
      <tr class="book-total"><td class="mono t2 c-1 w6">TOTAL</td><td class="num">${p1(b.invested_share)}</td><td class="num">100%</td><td class="num">${pos.filter(p => p.value != null).length} names</td><td></td><td></td><td class="num">${money(b.equity)}</td><td class="num">${pl(pos.reduce((s_, p) => s_ + (p.unrealized || 0), 0))}</td><td></td><td class="num">${p1(P.vol_ann_equity)}</td><td class="num">${n2(P.beta_spy_equity)}</td><td class="num">${n2(P.beta_smh_equity)}</td><td class="num">100%</td><td></td><td></td><td></td><td class="c-3 t1">cash ${money(b.cash)} · NAV ${money(b.nav)}</td></tr>
    </table></div>
    ${stats}
    <div class="book-grid">
      <div><div class="fx-head mono t1 c-3">THESIS EXPOSURE · <span class="c-3">registry v${(S.thesisReg && S.thesisReg.version) || "—"} · N<sub>eff</sub> ${P.effective_theses != null ? P.effective_theses : (th && th.n_eff != null ? th.n_eff : "—")} effective theses · invested ${p1(b.invested_share)} of NAV</span></div>
        ${bars || '<div class="mono t1 c-3">no classified exposure</div>'}
        ${th && th.coverage_caveat ? `<div class="mono t1 c-warn mt1">${th.coverage_caveat}</div>` : ""}
        <div class="mono t1 c-3 mt1">partial memberships leave a remainder counted as unclassified (registry policy)</div></div>
      ${renderFactorStrip("book")}
    </div>
  </div>`;
}
// ── P4.1 Action log (tier three): last 30 entries of data/actions.jsonl, newest first, each linked
//    to the session's published vintage row ──
function renderActionLog(){
  const acts = (S.actions || []).slice(-30).reverse();
  const pub = {}; (S.regimePub || []).forEach(r => { if (r && r.date) pub[String(r.date).slice(0, 10)] = r; });
  const fmtW = w => Object.entries(w || {}).map(([k, v]) => `${k} ${v}`).join(", ");
  const usd = x => "$" + Number(x).toLocaleString("en-US", {minimumFractionDigits: 2, maximumFractionDigits: 2});
  const rows = acts.map(a => {
    const v = pub[a.session_date]; const rt = v && v.R_t_published != null && v.R_t_published !== "" ? (+v.R_t_published).toFixed(4) : "not published";
    // Two record shapes share the log: tier rebalances (entries/exits + cash target before → after)
    // and operator trades (ticker, quantity, price; price may be pending the brokerage export).
    const isTrade = !!a.ticker;
    const names = isTrade ? `${a.ticker} ${a.quantity != null ? a.quantity + " sh" : ""}`
      : `${(a.entries || []).length ? "+" + a.entries.join(" ") : ""}${(a.exits || []).length ? " −" + a.exits.join(" ") : ""}`;
    const pending = /pending/i.test(a.source || "") ? ` <span class="tier-tag c-warn" title="${escText30(a.source)}">pending export</span>` : "";
    const sizing = isTrade
      ? (a.price != null ? `${usd(a.amount != null ? a.amount : a.price * (a.quantity || 0))} @ ${usd(a.price)}${/inferred/i.test(a.price_basis || "") ? " (inferred)" : ""}` : "price not yet known")
      : (a.target_cash_pct_before != null || a.target_cash_pct_after != null
          ? `cash ${a.target_cash_pct_before != null ? a.target_cash_pct_before + "%" : "—"} → ${a.target_cash_pct_after != null ? a.target_cash_pct_after + "%" : "—"}` : "—");
    const when = a.date_range ? `${a.date_range[0]} to ${a.date_range[1]}` : a.session_date;
    return `<tr>
      <td><a class="c-info" href="data/regime_daily_published.csv" title="published vintage row ${a.session_date}: R_t ${rt}${v && v.no_publish_reason ? " · " + v.no_publish_reason : ""}">${when}</a></td>
      <td>${(tierSpec(a.tier) || {}).short || a.tier}</td>
      <td class="c-1">${(a.action || []).join(", ")}${pending}</td>
      <td class="c-3">${names}</td>
      <td class="c-2" title="${isTrade ? escText30(a.price_basis || "") : `before: ${fmtW(a.weights_before)} · after: ${fmtW(a.weights_after)}`}">${sizing}</td>
      <td>${a.regime || "—"} · ${a.R_full != null ? a.R_full : "—"}</td>
      <td class="c-3 mono t1" title="sha256 of the input snapshot (prices, holdings, R_t)">${String(a.input_snapshot_sha256 || "").slice(0, 12)}</td>
    </tr>`; }).join("");
  return `<div class="rcc-card act-panel"><h3>ACTION LOG · <span class="c-3 w5">append-only · newest first · last 30 of ${(S.actions || []).length}</span></h3>
    ${rows ? `<div class="tbl-scroll"><table class="stack-m"><tr><th>SESSION</th><th>TIER</th><th>ACTION</th><th>NAMES</th><th>SIZING</th><th>REGIME · R<sub>full</sub></th><th>INPUT HASH</th></tr>${rows}</table></div>`
           : `<div class="mono t1 c-3">no actions logged yet — the log begins with the first change after deploy (no retroactive entries); written by compute_nav.py when a tier's positions or sizing change</div>`}
  </div>`;
}
// ── P4.2 Calibration panel (tier three, beside the ranking panel): in-sample and out-of-fold
//    reliability curves on one axis with the diagonal; base-rate Brier marked; OOF Brier beside ──
function brierToRate(b){ const d = 1 - 4 * b; return d >= 0 ? (1 - Math.sqrt(d)) / 2 : null; }   // Brier of a constant forecast p̄ is p̄(1−p̄)
function renderCalibrationPanel(){
  const c = S.v4Cal; if (!c || !c.methods) return "";
  const win = c.winning_method || "equal_weight"; const m = c.methods[win] || {};
  const base = brierToRate(c.base_rate_brier);
  return `<div class="rcc-card cal-panel"><h3>V4 CALIBRATION · <span class="c-3 w5">reliability of ${win.replace("_", " ")}: in-sample vs out-of-fold, one axis</span>${asOfBadge(c.as_of, {cadence: "monthly"})}</h3>
    <div class="chart-wrap cal-wrap"><canvas id="cal-chart"></canvas></div>
    <div class="chart-meta">base-rate Brier <strong class="c-1">${c.base_rate_brier}</strong>${base != null ? ` (event rate ${(base * 100).toFixed(1)}%)` : ""} · out-of-fold Brier, production model <strong class="c-1">${m.brier_out_of_fold}</strong> · in-sample ${m.brier_in_sample} (the isotonic fit, not evidence) · ${c.fold_definition && c.fold_definition.n_folds ? c.fold_definition.n_folds + " leave-one-crisis-out folds · " : ""}does not beat the base rate out of fold; use as a ranking, not a forecast.</div>
  </div>`;
}
function renderCalibrationChart(){
  const ctx = document.getElementById("cal-chart"); if (!ctx) return;
  const c = S.v4Cal; if (!c) return; const win = c.winning_method || "equal_weight";
  const ins = ((c.in_sample_reliability_bins || {})[win]) || c.reliability_bins || [];
  const oof = ((c.out_of_fold_reliability_bins || {})[win]) || [];
  if (S.calChart) { try { S.calChart.destroy(); } catch (e) {} }
  const C = CHARTS.colors(); const base = brierToRate(c.base_rate_brier);
  const pts = arr => arr.map(b => ({x: b.predicted_mean, y: b.observed_freq, n: b.n}));
  const datasets = [
    {label: "diagonal", role: "benchmark", borderColor: C.n2, borderDash: [3, 3], data: [{x: 0, y: 0}, {x: 1, y: 1}], directLabel: "perfect"},
    {label: "in-sample (isotonic fit)", role: "series", borderColor: C.n1, data: pts(ins), pointRadius: 3, directLabel: "in-sample"},
    {label: "out-of-fold", role: "headline", borderColor: C.info, data: pts(oof), pointRadius: 3, directLabel: "out-of-fold"},
  ];
  if (base != null) datasets.push({label: `base rate ${(base * 100).toFixed(1)}%`, role: "benchmark", borderColor: C.warn, borderDash: [2, 3], data: [{x: 0, y: base}, {x: 1, y: base}], directLabel: `base rate (Brier ${c.base_rate_brier})`});
  S.calChart = CHARTS.make(ctx, {type: "line", data: {datasets}, options: {
    layout: {padding: {right: 150}},
    interaction: {mode: "nearest", axis: "xy", intersect: true},
    scales: {x: {type: "linear", min: 0, max: 1, ticks: {callback: v => (v * 100).toFixed(0) + "%"}, title: {display: true, text: "predicted probability", color: C.n2, font: {family: CHARTS.tok("mono"), size: CHARTS.px("t1")}}},
             y: {min: 0, max: 1, ticks: {callback: v => (v * 100).toFixed(0) + "%"}, title: {display: true, text: "observed frequency", color: C.n2, font: {family: CHARTS.tok("mono"), size: CHARTS.px("t1")}}}},
    plugins: {tooltip: {callbacks: {label: ctx => ` ${ctx.dataset.label}: predicted ${(ctx.parsed.x * 100).toFixed(1)}% → observed ${(ctx.parsed.y * 100).toFixed(1)}%${ctx.raw && ctx.raw.n ? " (n " + ctx.raw.n + ")" : ""}`}}},
  }});
}
// ── 16-Sept 1.6 / Phase 5: diversification sleeves — grouped by thesis, quality-gated; correlation to the equity book ──
function sleeveRow(s_){
  const c = s_.corr; const w = c == null ? 0 : Math.abs(c) * 50;
  const bar = c == null ? `<span class="c-3 t1">${s_.note || "n/a"}</span>` : `<span class="sleeve-bar"><span class="sleeve-zero"></span><span class="sleeve-fill ${c >= 0 ? "bg-warn" : "bg-pos"}" style="left:${(c >= 0 ? 50 : 50 - w).toFixed(1)}%;width:${w.toFixed(1)}%"></span></span>`;
  const kind = s_.kind === "etf" ? "sector / asset ETF" : `quality-passing screen name · ${thesisLabel(s_.group || "")} · composite ${s_.screen_composite} (F ${s_.fundamental} · V ${s_.visibility})`;
  return `<tr><td class="mono t2 c-1 w6">${s_.ticker}</td><td class="c-2">${s_.label}</td><td class="c-3 t1">${kind}</td><td class="sleeve-cell">${bar}</td><td class="num c-1">${c == null ? "—" : (c >= 0 ? "+" : "") + c.toFixed(2)}</td><td class="num c-3">${s_.n_obs}</td></tr>`;
}
function renderSleevesPanel(){
  const b = S.book; if (!b || !b.sleeves) return "";
  const qb = b.quality_bar || {fundamental: 18, visibility: 15};
  const groups = (b.sleeve_groups || []).map(g => {
    const rows = g.etfs.map(sleeveRow).join("") + (g.names.length ? g.names.map(sleeveRow).join("")
      : `<tr><td></td><td colspan="5" class="c-3 t1">no screen name in ${g.theses.length ? g.theses.map(thesisLabel).join(" / ") : "this group"} passes the quality bar (fundamental ≥ ${qb.fundamental}, visibility ≥ ${qb.visibility}) — the group's evidence is its ETFs</td></tr>`);
    return `<tr class="sleeve-group"><td colspan="6" class="mono t1 w6 c-2">${g.label.toUpperCase()}${g.theses.length ? ` <span class="c-3 w4">· registry ${g.theses.map(thesisLabel).join(", ")}</span>` : ""}</td></tr>${rows}`;
  }).join("");
  const rest = b.sleeves.filter(s_ => !(b.sleeve_groups || []).some(g => g.etfs.some(e => e.ticker === s_.ticker) || g.names.some(n => n.ticker === s_.ticker)));
  return `<div class="rcc-card sleeves-panel"><h3>${(b.sleeves_heading || "exposures the book lacks, at the level where the system has evidence").toUpperCase()} · <span class="c-3 w5">sleeves grouped by thesis · correlation of daily returns to the equity book, ${b.definitions ? b.definitions.window_sessions : 126} sessions</span>${holdingsPill()}${intradayBadge(b)}</h3>
    <div class="tbl-scroll"><table class="sleeves-table"><tr><th>SLEEVE</th><th>NAME</th><th>KIND</th><th>CORRELATION TO THE BOOK</th><th class="num">ρ</th><th class="num">n</th></tr>${groups}${rest.length ? `<tr class="sleeve-group"><td colspan="6" class="mono t1 w6 c-2">OTHER SLEEVES · <span class="c-3 w4">ascending</span></td></tr>${rest.map(sleeveRow).join("")}` : ""}</table></div>
    <div class="chart-meta">${b.sleeves_note || ""} · screen names pass the quality bar (fundamental ≥ ${qb.fundamental}, visibility ≥ ${qb.visibility}, the shelf's bar) and carry a registry thesis; held names excluded · book series: constant current equity weights · sorted ascending within each group</div>
  </div>`;
}
function renderCalendarCard(){
  const ev = (S.eventCal && S.eventCal.events) || [];
  const today = _etDateISO(new Date());
  const next = ev.filter(e => e && e.date >= today && e.type !== "REFUNDING" && (e.type !== "TREASURY" || ["3Y","10Y","30Y"].includes(e.tenor || String(e.label || "").split(" ")[0]))).slice(0, 8);   // R6.3 (1-Oct-2026): the pre-R6 type set
  if (!next.length) return "";
  return `<div class="rcc-card cal-card"><h3>CALENDAR · <span class="c-3 w5">next scheduled macro events</span></h3>
    <table class="cal-table">${next.map(e => `<tr><td class="mono t1 c-2">${e.date}</td><td class="mono t1 c-1">${e.label || e.type}</td><td class="serif t1 c-3">${e.name || ""}</td></tr>`).join("")}</table>
  </div>`;
}
// P1.5: numbers tween over --tween when a re-render changes them (badges fade via CSS; nothing slides)
function applyTweens(){
  const ms = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--tween")) || 0;
  S._tw = S._tw || {};
  document.querySelectorAll("[data-tween]").forEach(el => {
    const key = el.dataset.tween, to = parseFloat(el.dataset.val), fmt = el.dataset.fmt || "n2";
    if (!isFinite(to)) return;
    const from = S._tw[key];
    S._tw[key] = to;
    if (from == null || from === to || ms <= 0) return;
    const f = v => fmt === "n3" ? v.toFixed(3) : fmt === "p" ? fmtP(v) : fmt === "p1" ? fmtP1(v) : fmt === "nav" ? "$" + fmt(v) : v.toFixed(2);
    const t0 = performance.now();
    const tick = cb => (document.hidden ? setTimeout(() => cb(performance.now()), 16) : requestAnimationFrame(cb));   // frames stop in hidden tabs
    const step = now => { const k = Math.min(1, (now - t0) / ms); el.textContent = f(from + (to - from) * k); if (k < 1) tick(step); };
    tick(step);
  });
}

// ── 6.3: the leaderboard block (leader banner · race chart · leaderboard), used by tournament.html ──
function renderLeaderboardBlock(){
  const live = S.tournament && S.tournament.history && S.tournament.history.length > 0
    ? S.tournament.history[S.tournament.history.length-1] : null;
  const allSeries = buildSeries();
  const tmMap = {};
  TIER_ORDER.forEach(tid => {
    const ser = allSeries.tiers[tid];
    if (!ser || ser.length === 0) return;
    const periodSer = applyPeriod(ser, S.period);
    const benchTid = BENCH_FOR_TIER[tid];
    const periodBench = applyPeriod(allSeries.bench[benchTid] || [], S.period);
    tmMap[tid] = tierMetrics(periodSer, periodBench);
  });
  // Audit order 30-Sept (4.4 / T3): the operator tier is NOT COMPARABLE until it is rebuilt from the
  // brokerage transactions export — it never enters the ranking or the leader banner.
  const wc = S.tournament && S.tournament.werner_comparable;
  const werNotComparable = !!(wc && wc.comparable === false);
  let leader = null, leaderRet = -Infinity;
  Object.entries(tmMap).forEach(([tid, m]) => { if (werNotComparable && tid === "5_werner") return; if (m && m.total > leaderRet) { leaderRet = m.total; leader = tid; } });

  let h = "";
  // ---- Leader banner ----
  if (leader && tmMap[leader]) {
    const lt = tierSpec(leader); const m = tmMap[leader];
    h += `<div class="lb">
      <div class="lb-crown">♛</div>
      <div>
        <div class="lb-name ${cc(lt.color)}">${lt.name} leads</div>
        <div class="lb-stat">over ${S.period === "ALL" ? "full sample" : S.period}: <strong>${fmtP(m.total)}</strong> · Sharpe ${m.sharpe.toFixed(2)} · max DD ${fmtP1(m.maxDD)}</div>
      </div>
    </div>`;
  }

  // ---- Race chart ----
  h += `<div class="chart-card">
    <div class="chart-head">
      <div class="chart-title">RACE CHART · LOG SCALE · NAV rebased to 1.0 at period start</div>
      <div class="periods">
        ${["1M","3M","6M","YTD","1Y","5Y","ALL"].map(p =>
          `<button class="period-btn ${S.period===p?"on":""}" data-p="${p}">${p}</button>`).join("")}
      </div>
    </div>
    <div class="chart-wrap"><canvas id="race-chart"></canvas></div>
    <div class="chart-meta">${TIER_ORDER.length} tiers + SPY benchmark · 5_werner is live-only (no backtest)</div>
  </div>`;

  // ---- Leaderboard ----
  // Regime-conditional sorting: when toggle is on, sort by the current-state
  // shrunk annualized return from the JS-shrunk conditional scores. The
  // unconditional toggle keeps the existing total-return ordering.
  const condMode = !!S.leaderboardCondMode;
  const currentState = (S.volRegime && S.volRegime.state) || null;
  const condFor = (tid) => {
    const cs = S.condScores && S.condScores.sleeves && S.condScores.sleeves[tid];
    if (!cs || !currentState) return null;
    const cell = cs.per_state && cs.per_state[currentState];
    return cell || null;
  };
  const sorted = Object.entries(tmMap).filter(([tid,m]) => m != null && !(werNotComparable && tid === "5_werner")).sort((a,b) => {
    if (!condMode) return (b[1].total - a[1].total);
    const ca = condFor(a[0]); const cb = condFor(b[0]);
    return ((cb && cb.shrunk_ann_return) || -9e9) - ((ca && ca.shrunk_ann_return) || -9e9);
  });
  if (werNotComparable && tmMap["5_werner"]) sorted.push(["5_werner", tmMap["5_werner"]]);   // shown last, unranked

  const toggleHtml = `<span class="cond-toggle">
    <button class="${!condMode ? "on" : ""}" data-cond-mode="off">UNCONDITIONAL</button>
    <button class="${condMode  ? "on" : ""}" data-cond-mode="on">CONDITIONAL · ${currentState || "—"}</button>
  </span>`;

  const sc = S.condScores || {};
  const sn = (sc.state_day_counts || {})[currentState] || 0;
  const condCap = condMode
    ? `<div class="cond-caption">CONDITIONAL on <strong class="c-accent">${currentState || "—"}</strong>: scores are James-Stein shrunk toward unconditional. Bucket n = ${sn} days. ${sc.caption || ""}</div>`
    : "";

  h += `<div class="lbtable lb-tournament">
    <div class="lb-h"><h2>LEADERBOARD${asOfBadge(live && live.date)}</h2>
      <div class="lb-h-sub">${S.period === "ALL" ? "full sample" : S.period} · ${condMode ? "ranked by shrunk " + currentState + " return" : "ranked by total return"} · <span title="C1: costs = half-spread + impact, one-way, on NAV-weight turnover at every rebalance">net of costs (${(S.tournament && S.tournament.cost_restatement && S.tournament.cost_restatement.cost_model) || "10 bps one-way"})</span>${c2DisclosureHtml()}${toggleHtml}</div></div>
    ${condCap}
    <table>
      <tr>
        <th>#</th><th>TIER</th>
        <th class="num" title="net of transaction costs; hover a NAV for the pre-cost figure and the restated net (C1)">NAV <small class="c-3 w5">net</small></th>
        <th class="num">TOTAL</th>
        <th class="num" title="C1: one-way turnover per year — backtest basis for tiers 1–4 (names and the cash sleeve, at every rebalance); hover a cell for the live-to-date figure">TURNOVER<small class="c-3 w5">/yr</small></th>
        <th class="num" title="C1: cost drag on annualized return, basis points per year, backtest basis (3 bps half-spread + 7 bps impact, one-way, on NAV-weight turnover)">COST DRAG</th>
        <th class="num">1M</th>
        <th class="num">1W</th>
        <th class="num">SHARPE</th>
        <th class="num">MAX DD</th>
        <th class="num">vs BENCH</th>
        <th class="num">N</th>
        <th></th>
      </tr>`;
  sorted.forEach(([tid, m], i) => {
    const t = tierSpec(tid);
    const liveTier = live ? live.tiers[tid] : null;
    const navVal = liveTier ? liveTier.nav : null;
    const nPos = liveTier ? liveTier.n_positions : null;
    const open = (S.expanded === tid);
    const notComp = werNotComparable && tid === "5_werner";
    const wcLast = notComp && wc.series && wc.series.length ? wc.series[wc.series.length - 1] : null;
    h += `<tr class="tier-row ${open?"open":""} ${notComp ? "dim" : ""}" data-tid="${tid}">
      <td class="rank ${i===0 && !notComp?"first":""}">${notComp ? "—" : i+1}</td>
      <td>
        <span class="tier-dot ${cc(t.color,'bg')}"></span>
        <span class="tier-name">${t.short}</span>${notComp ? ' <span class="mono t1 w6 r1 x2 c-warn">NOT COMPARABLE</span>' : ""}
        <div class="tier-desc">${notComp ? `excluded from the ranking: ${(wc.comparable_reason || "").substring(0, 120)}… · re-seed ${(wc.reseed_events || []).map(e => e.date + " " + (e.step_pct >= 0 ? "+" : "") + e.step_pct + "%").join(", ") || "—"} · comparable series (step excluded) $${wcLast ? fmt(wcLast.nav_comparable) : "—"}` : `${(t.description||"").substring(0,80)}${(t.description||"").length>80?"…":""}`}</div>
      </td>
      <td class="num" title="${(() => { const cr = S.tournament && S.tournament.cost_restatement && S.tournament.cost_restatement.tiers && S.tournament.cost_restatement.tiers[tid]; return cr ? `pre-cost $${fmt(cr.nav_pre_cost_last)} · restated net (spread+impact model) $${fmt(cr.nav_net_restated_last)} · cumulative cost charged ${cr.cumulative_cost_flat_pct}% (flat, as published) vs ${cr.cumulative_cost_model_pct}% (model) · one-way turnover ${cr.turnover_one_way_total} over ${cr.n_rebalances} rebalances` : "net of costs"; })()}">${navVal ? "$"+fmt(navVal) : "—"}</td>
      <td class="num ${pnlc(m.total)}"><span data-tween="tot-${tid}" data-val="${m.total}" data-fmt="p">${fmtP(m.total)}</span>${(() => {
        if (!condMode) return "";
        const cc = condFor(tid);
        if (!cc || cc.shrunk_ann_return == null) return ` <small class="c-3">· n=0</small>`;
        const s = cc.shrunk_ann_return;
        return ` <small class="c-accent w5"> · ${currentState[0].toUpperCase()}: ${(s*100).toFixed(1)}%</small><small class="c-3"> · n=${cc.n} · w=${cc.shrinkage_weight}</small>`;
      })()}</td>
      ${(() => { // P3.4: C1's figures beside the net return
        const bm = S.metrics && S.metrics[tid]; const cr = S.tournament && S.tournament.cost_restatement && S.tournament.cost_restatement.tiers && S.tournament.cost_restatement.tiers[tid];
        if (!bm || bm.turnover_one_way_annual == null) return `<td class="num c-3" title="discretionary tier: not costed by the C1 model; no backtest">—</td><td class="num c-3" title="discretionary tier: not costed">—</td>`;
        const live = cr ? ` · live to date ${cr.turnover_one_way_total}× one-way over ${cr.n_rebalances} rebalances, model cost ${cr.cumulative_cost_model_pct}% cumulative (flat as published ${cr.cumulative_cost_flat_pct}%)` : "";
        return `<td class="num" title="backtest basis: ${bm.turnover_one_way_annual}× one-way per year${live}">${(bm.turnover_one_way_annual * 100).toFixed(0)}%</td>
      <td class="num" title="backtest basis: ${bm.cost_drag_cagr_pp} pp of CAGR per year${live}">${Math.round(bm.cost_drag_cagr_pp * 100)} bps</td>`; })()}
      <td class="num ${m.m1!=null?pnlc(m.m1):'neut'}">${m.m1!=null?fmtP1(m.m1):"—"}</td>
      <td class="num ${m.w1!=null?pnlc(m.w1):'neut'}">${m.w1!=null?fmtP1(m.w1):"—"}</td>
      <td class="num"><span data-tween="sh-${tid}" data-val="${m.sharpe}" data-fmt="n2">${m.sharpe.toFixed(2)}</span></td>
      <td class="num neg" title="${c2TierTitle(tid)}"><span data-tween="dd-${tid}" data-val="${m.maxDD}" data-fmt="p1">${fmtP1(m.maxDD)}</span>${c2TierSub(tid)}</td>
      <td class="num ${m.alpha!=null?pnlc(m.alpha):'neut'}">${m.alpha!=null?fmtP1(m.alpha):"—"}</td>
      <td class="num">${nPos != null ? nPos : "—"}</td>
      <td><span class="chev ${open?"open":""}">›</span></td>
    </tr>`;
    if (open) {
      h += `<tr><td colspan="13" class="p0"><div class="tier-detail open">${renderTierDetail(tid)}</div></td></tr>`;
    }
  });
  h += `</table></div>`;
  return {html: h, allSeries};
}
// ── 6.3: event bindings shared by every page (elements absent on a page are simply not bound) ──
function bindEvents(){
  // ---- Bindings ----
  document.querySelectorAll(".period-btn[data-p]").forEach(b => b.addEventListener("click", () => {
    S.period = b.dataset.p; render();
  }));
  document.querySelectorAll(".period-btn[data-ddr]").forEach(b => b.addEventListener("click", () => {
    S.ddRange = b.dataset.ddr; render();
  }));
  document.querySelectorAll(".period-btn[data-tm]").forEach(b => b.addEventListener("click", () => {
    S.tmSel = b.dataset.tm; render();
  }));
  document.querySelectorAll(".tier-row").forEach(r => r.addEventListener("click", (ev) => {
    if (ev.target.closest(".tk-row") || ev.target.closest(".tk-detail")) return;
    const tid = r.dataset.tid;
    S.expanded = (S.expanded === tid) ? null : tid;
    if (S.expanded !== tid) S.expandedTicker = null;
    render();
  }));
  document.querySelectorAll(".tk-row").forEach(r => r.addEventListener("click", (ev) => {
    if (ev.target.closest(".tk-detail")) return;
    ev.stopPropagation();
    const tk = r.dataset.tk;
    S.expandedTicker = (S.expandedTicker === tk) ? null : tk;
    render();
  }));
  document.querySelectorAll("[data-close-tk]").forEach(b => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    S.expandedTicker = null;
    render();
  }));
  document.querySelectorAll(".period-btn[data-tkp]").forEach(b => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    S.tickerChartPeriod = b.dataset.tkp;
    render();
  }));
  // ---- Indicator card clicks (open / close drill-down, inline under tier) ----
  document.querySelectorAll(".ind-card[data-ind]").forEach(c => c.addEventListener("click", (ev) => {
    if (ev.target.closest(".ind-detail")) return;
    const k = c.dataset.ind;
    S.expandedIndicator = (S.expandedIndicator === k) ? null : k;
    render();
  }));
  document.querySelectorAll("[data-close-ind]").forEach(b => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    S.expandedIndicator = null;
    render();
  }));
  document.querySelectorAll(".id-period-btn[data-indp]").forEach(b => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    S.indPeriod = b.dataset.indp;
    render();
  }));
  // ---- Scanner: filter chips, sortable headers, row click → expand ticker
  document.querySelectorAll(".scanner .filter-btn[data-scfilter]").forEach(b => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    S.scannerFilter = b.dataset.scfilter;
    render();
  }));
  document.querySelectorAll(".scanner th[data-scsort]").forEach(th => th.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const k = th.dataset.scsort;
    if (S.scannerSort === k) {
      S.scannerSortDir = (S.scannerSortDir === "desc") ? "asc" : "desc";
    } else {
      S.scannerSort = k; S.scannerSortDir = "desc";
    }
    render();
  }));
  document.querySelectorAll(".scanner tr.row[data-scanner-tk]").forEach(tr => tr.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const tk = tr.dataset.scannerTk;
    // Find which tier this ticker lives in; expand that tier and the ticker.
    const owner = TIER_ORDER.find(tid => {
      const t = S.tournament && S.tournament.history && S.tournament.history.slice(-1)[0];
      const holdings = t?.tiers?.[tid]?.holdings || [];
      return holdings.includes(tk);
    });
    if (owner) {
      S.expanded = owner;
      S.expandedTicker = tk;
    } else {
      // Ticker not currently in any live tier — still try detail panel for it.
      S.expandedTicker = tk;
    }
    render();
    setTimeout(() => {
      const row = document.querySelector(`tr[data-tk="${tk}"]`) || document.querySelector(".tk-detail");
      if (row && row.scrollIntoView) row.scrollIntoView({behavior:"smooth", block:"center"});
    }, 50);
  }));
  // Conditional/unconditional toggle on leaderboard
  document.querySelectorAll("[data-cond-mode]").forEach(b => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    S.leaderboardCondMode = b.dataset.condMode === "on";
    render();
  }));
  // Thesis section toggles
  document.querySelectorAll("[data-thesis-view]").forEach(b => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    S.thesisView = b.dataset.thesisView;
    render();
  }));
  document.querySelectorAll("[data-thesis-tab]").forEach(b => b.addEventListener("click", (ev) => {
    ev.stopPropagation();
    S.thesisTab = b.dataset.thesisTab;
    render();
  }));

}
// ── 6.3: chart draws shared by every page; each draw returns when its canvas is absent ──
function drawCharts(allSeries){
  setTimeout(() => {
    renderRegimeTimeline();
    renderRopCurveChart();
    renderThesisRsChart();
    renderChart(allSeries, S.period);
    renderDrawdownChart();      // P2.1 (tier one)
    renderC3PathChart();        // P2.2 (tier two)
    renderCalibrationChart();   // P4.2 (tier three)
    renderBondsCurveChart();    // fixed-income module (bonds page; guarded by canvas id)
    renderGlobalRatesCharts();  // global rates (order 6-Oct-2026; guarded by canvas ids)
    if (S.expandedTicker) renderTickerChart(S.expandedTicker);
    if (S.expandedIndicator) {
      // Scroll FIRST so the panel area is committed to layout, then render
      // charts (which rAF-defers to give Chart.js correct canvas dimensions).
      const panel = document.querySelector(".ind-detail");
      if (panel && panel.scrollIntoView) {
        panel.scrollIntoView({behavior: "smooth", block: "nearest", inline: "nearest"});
      }
      renderIndicatorCharts();
    }
  }, 10);
}
// Decision Memo 9-Sept-2026 §6: standing disclosure on the backtest panel — the
// regime-index history uses revised FRED inputs; the point-in-time figure (C2)
// is shown beside the displayed one. Served tier sizing uses the internal vol
// index (no FRED inputs), so the displayed max DD itself is not the revised-input
// number; the C2 pair is the 24-indicator overlay through the same engine.
function c2DisclosureHtml(){
  const c = S.c2; const t4 = c && c.drawdown_reduction && c.drawdown_reduction["4_tactical"];
  if (!t4 || !t4.rev || !t4.pit) return "";
  const rv = t4.rev.dd_reduction_vs_spy * 100, pt = t4.pit.dd_reduction_vs_spy * 100;
  return ` · <span class="c-warn" title="C2 (reports/retirement_test_C2_input_vintages.md): the regime-index history uses revised FRED inputs. Rebuilt on ALFRED point-in-time inputs, the 24-indicator overlay's drawdown reduction vs SPY through the same engine is ${pt.toFixed(1)}% against ${rv.toFixed(1)}% on revised inputs (tier 4). Revisions account for roughly a third of the apparent reduction, release lag for almost none. Served tier sizing uses the internal vol-based index (no FRED inputs). Hover a MAX DD cell for the per-tier pair.">backtest history on revised inputs · point-in-time drawdown reduction ${pt.toFixed(0)}% vs ${rv.toFixed(0)}% revised (C2)</span>`;
}
function c2TierSub(tid){
  const c = S.c2 && S.c2.drawdown_reduction && S.c2.drawdown_reduction[tid];
  if (!c || !c.rev || !c.pit) return "";
  return `<div class="mono t1 w5 c-3" title="C2 drawdown reduction vs SPY: point-in-time vs revised inputs (24-indicator overlay, same engine)">DD red. PIT ${(c.pit.dd_reduction_vs_spy*100).toFixed(0)}% · rev ${(c.rev.dd_reduction_vs_spy*100).toFixed(0)}%</div>`;
}
function c2TierTitle(tid){
  const c = S.c2 && S.c2.drawdown_reduction && S.c2.drawdown_reduction[tid];
  if (!c || !c.rev || !c.pit) return "max drawdown of the displayed series";
  return `C2: 24-indicator overlay through the same engine — drawdown reduction vs SPY ${(c.rev.dd_reduction_vs_spy*100).toFixed(1)}% on revised inputs (max DD ${(c.rev.max_dd*100).toFixed(1)}%) vs ${(c.pit.dd_reduction_vs_spy*100).toFixed(1)}% on point-in-time inputs (max DD ${(c.pit.max_dd*100).toFixed(1)}%). The displayed max DD is the served series (internal vol-index sizing, no FRED inputs).`;
}

// ── Fixed-income module (order 16-Sept-2026, Phase 5) ────────────────────────────────────
// bonds.html panels. Every panel is descriptive: states and associations, no rate forecast,
// no buy or sell instruction. The rates-regime state carries the DIAGNOSTIC label.
function _bpct(v, d){ return v == null ? "—" : (v).toFixed(d == null ? 1 : d) + "%"; }
function _bnum(v, d){ return v == null ? "—" : (+v).toFixed(d == null ? 2 : d); }
function _diagChip(){ return `<span class="mono t1 w6 r1 x2 c-warn ls06">DIAGNOSTIC</span>`; }
const _CURVE_STATE_CLR = {inverted:"c-neg", flat:"c-warn", normal:"c-2", steep:"c-pos"};
const _CREDIT_STATE_CLR = {tight:"c-warn", normal:"c-2", wide:"c-warn", stressed:"c-neg"};

// ── Global rates (order 6-Oct-2026): why long-term yields are rising across the G7, the U.S. 10-year split into its
// parts, Treasury auctions, the drivers, and rule-based conditions. Descriptive throughout: no forecast, no recommendation.
const grPct = (v, d) => v == null ? "—" : Number(v).toFixed(d == null ? 2 : d) + "%";
const grBp = v => v == null ? "—" : (v >= 0 ? "+" : "") + Math.round(v * 100) + "bp";
const grSgn = (v, d, u) => v == null ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(d == null ? 1 : d) + (u || "");
const grDate = d => d ? String(d).slice(0, 10) : "—";
function grSrc(m){ return m ? `${escText30(m.label || "")} · ${escText30(m.source || "")}${m.id ? " " + escText30(m.id) : ""} · as of ${grDate(m.as_of)}${m.error ? ` · <span class="c-warn">last fetch failed (${escText30(m.error)})</span>` : ""}` : ""; }
function grStale(dateStr, lagDays){
  if (!dateStr) return true;
  const age = (Date.now() - new Date(String(dateStr).slice(0, 10) + "T12:00:00Z").getTime()) / 864e5;
  return age > lagDays;
}
function renderGlobalRatesA(){
  const G = S.globalRates; if (!G || !G.panel_a) return `<div class="rcc-card"><h3>G7 10-YEAR YIELDS</h3><div class="mono t1 c-3">data/rates/global_rates.json not published yet</div></div>`;
  const A = G.panel_a, cm = A.comovement || {};
  const rows = A.rows.map(r => `<tr><td class="c-1 w6">${r.name}</td>
      <td class="num c-1 w6">${grPct(r.level)}</td><td class="c-3">${grDate(r.date)}${r.kind !== "daily" ? ' <span class="c-warn">monthly average</span>' : ""}</td>
      <td class="num">${r.chg_1w == null ? "—" : grBp(r.chg_1w)}</td><td class="num">${grBp(r.chg_1m)}</td><td class="num">${grBp(r.chg_12m)}</td>
      <td class="num c-2">${r.pctile_20y == null ? "—" : Math.round(r.pctile_20y) + "th"}</td>
      <td class="num c-3">${grPct(r.monthly_level)} <span class="t1">(${r.monthly_date || "—"})</span></td>
      <td class="c-3 t1">${escText30(r.src_source || "")}${r.src_as_of ? " · " + grDate(r.src_as_of) : ""}</td></tr>`).join("");
  const vs = Object.entries(cm.vs_us || {}).map(([k, v]) => `${(A.rows.find(r => r.code === k) || {}).name || k} ${Number(v).toFixed(2)}`).join(", ");
  return `<div class="rcc-card"><h3>G7 10-YEAR YIELDS · <span class="c-3 w5">level, change over a week, a month and twelve months, and the level's place in each country's last 20 years of monthly data</span>${asOfBadge(G.as_of, {lag: 1})}</h3>
    <div class="tbl-scroll"><table class="th-table stack-m"><tr><th>COUNTRY</th><th class="num">10-YEAR</th><th>AS OF</th><th class="num">1 WEEK</th><th class="num">1 MONTH</th><th class="num">12 MONTHS</th><th class="num">20-YEAR %ILE</th><th class="num">LATEST MONTHLY AVG</th><th>SOURCE</th></tr>${rows}</table></div>
    <div class="dd-body mt2"><div class="dd-wrap"><div class="mono t1 c-3">10-year yields since January 2021 (weekly; France and Italy monthly averages)</div><canvas id="gr-a-levels" height="230"></canvas></div>
      <div class="dd-wrap"><div class="mono t1 c-3">change since 1 January 2026, basis points</div><canvas id="gr-a-change" height="230"></canvas></div></div>
    <div class="mono t1 c-2 mt1">co-movement: the average pairwise correlation of monthly yield changes over the ${cm.months || 36} months to ${cm.through || "—"} is <span class="c-1 w6">${cm.avg_pairwise == null ? "—" : Number(cm.avg_pairwise).toFixed(2)}</span>; each country with the United States: ${vs}</div>
    <div class="chart-meta">${escText30(cm.basis || "")} · percentiles from the OECD monthly averages · ${escText30((G.footnotes || {}).uk || "")} · ${escText30((G.footnotes || {}).monthly || "")}</div></div>`;
}
function renderGlobalRatesB(){
  const G = S.globalRates; const B = G && G.panel_b; if (!B) return "";
  const c = B.current || {}, h = B.term_premium_history || {}, id = B.identities || {};
  const row = (lab, x) => x ? `<tr><td class="c-2">${lab}</td><td class="num c-1 w6">${grPct(x.value)}</td><td class="c-3">${grDate(x.date)}</td><td class="num">${grBp(x.chg_1m)}</td><td class="num">${grBp(x.chg_12m)}</td></tr>` : "";
  const idOk = (g) => g == null ? "—" : (Math.abs(g) <= (id.tolerance_pp || 0.02) ? `<span class="c-pos">holds</span> (${(g * 100).toFixed(1)}bp)` : `<span class="c-warn">off by ${(g * 100).toFixed(1)}bp</span>`);
  return `<div class="rcc-card"><h3>THE U.S. 10-YEAR, SPLIT INTO ITS PARTS · <span class="c-3 w5">real yield plus breakeven inflation; expected average short rate plus term premium</span>${asOfBadge((c.nominal || {}).date, {lag: 1})}</h3>
    <div class="tbl-scroll"><table class="th-table stack-m"><tr><th>PART</th><th class="num">LATEST</th><th>AS OF</th><th class="num">1 MONTH</th><th class="num">12 MONTHS</th></tr>
      ${row("nominal 10-year (DGS10)", c.nominal)}${row("real yield (DFII10)", c.real)}${row("breakeven inflation (T10YIE)", c.breakeven)}
      ${row("term premium, Kim-Wright (THREEFYTP10)", c.term_premium_kw)}${row("term premium, ACM (New York Fed)", c.term_premium_acm)}${row("expected average short rate (10-year less Kim-Wright)", c.expected_short_rate)}</table></div>
    <div class="dd-body mt2"><div class="dd-wrap"><div class="mono t1 c-3">B1 · nominal = real + breakeven (the shaded band between the real yield and the nominal yield is the breakeven)</div><canvas id="gr-b1" height="230"></canvas></div>
      <div class="dd-wrap"><div class="mono t1 c-3">B2 · nominal = expected average short rate + term premium (the band is the Kim-Wright term premium; both term premiums as lines)</div><canvas id="gr-b2" height="230"></canvas></div></div>
    <div class="mono t1 c-2 mt1">${escText30(h.text || "")}</div>
    <div class="mono t1 c-3 mt1">identities on the latest common dates: nominal = real + breakeven on ${grDate(id.b1_date)}: ${idOk(id.b1_gap_pp)} · nominal = expected short rate + term premium on ${grDate(id.b2_date)}: ${idOk(id.b2_gap_pp)} (by construction)</div>
    <div class="chart-meta">${escText30(B.caption || "")}</div></div>`;
}
function renderGlobalRatesC(){
  const G = S.globalRates; const C = G && G.panel_c; if (!C) return "";
  const money = v => v == null ? "—" : "$" + (v / 1e9).toFixed(0) + "B";
  const rows = (C.last || []).map(r => { const k = r.comparison || {};
    return `<tr class="${r.weak ? "" : ""}"><td class="c-2">${r.date}</td><td class="c-1">${escText30(r.security)}</td><td class="num">${money(r.size)}</td><td class="num">${grPct(r.high_yield, 3)}</td>
      <td class="num">${r.bid_to_cover == null ? "—" : r.bid_to_cover.toFixed(2)} <span class="c-3 t1">(${k.btc_diff == null ? "—" : grSgn(k.btc_diff, 2)})</span></td>
      <td class="num">${r.indirect_share == null ? "—" : r.indirect_share.toFixed(1) + "%"} <span class="c-3 t1">(${k.indirect_diff_pp == null ? "—" : grSgn(k.indirect_diff_pp, 1, "pp")})</span></td>
      <td>${r.weak == null ? '<span class="c-3">fewer than six prior</span>' : r.weak ? `<span class="c-warn w6" title="${escText30(r.weak_why || "")}">weak</span>` : '<span class="c-3">—</span>'}</td></tr>`; }).join("");
  const up = (C.upcoming || []).map(u => `${u.date} ${escText30(u.security)}${u.size ? " (" + money(u.size) + ")" : ""}`).join(" · ");
  return `<div class="rcc-card"><h3>TREASURY AUCTIONS · <span class="c-3 w5">the last 12 note and bond auctions against the average of the prior six of the same maturity</span>${asOfBadge((C.last && C.last[0] && C.last[0].date) || null, {cadence: "weekly"})}</h3>
    <div class="tbl-scroll"><table class="th-table stack-m"><tr><th>DATE</th><th>SECURITY</th><th class="num">SIZE</th><th class="num">HIGH YIELD</th><th class="num">BID-TO-COVER (vs prior 6)</th><th class="num">INDIRECT (vs prior 6)</th><th>LABEL</th></tr>${rows}</table></div>
    <div class="mono t1 c-2 mt1">announced: ${up || "none listed"}${C.next_refunding ? ` · next quarterly refunding: <span class="c-1">${C.next_refunding.date}</span>` : ""}</div>
    <div class="chart-meta">${escText30(C.rule || "")} · indirect share of the competitive accepted amount · ${escText30(C.source || "")}, retrieved ${grDate(C.retrieved_at)}</div></div>`;
}
function renderGlobalRatesD(){
  const G = S.globalRates; const D = G && G.panel_d; if (!D) return "";
  const lab = {brent: "Brent spot (EIA via FRED)", brent_front: "Brent front-month (provider), same-day", usdjpy: "yen per dollar", jp10: "Japan 10-year", uk30: "UK 30-year (zero-coupon)", us2: "U.S. 2-year (expected Fed policy)", effr: "effective fed funds"};
  const val = x => x.value == null ? "—" : x.unit === "usd" ? "$" + x.value.toFixed(2) : x.unit === "fx" ? x.value.toFixed(2) : grPct(x.value, 3);
  const chg = x => x.chg_1m == null ? "—" : x.chg_1m_unit === "%" ? grSgn(x.chg_1m, 1, "%") : grBp(x.chg_1m);
  const cells = D.map(x => `<div class="gr-cell"><div class="mono t1 c-3">${lab[x.series] || x.series}</div><div class="mono t3 w7 c-1">${val(x)}</div><div class="mono t1 c-2">1 month ${chg(x)}</div><div class="mono t1 c-3">as of ${grDate(x.date)}${grStale(x.date, x.series === "brent" || x.series === "usdjpy" ? 10 : 5) ? ' <span class="c-warn">late</span>' : ""}</div></div>`).join("");
  return `<div class="rcc-card"><h3>DRIVERS · <span class="c-3 w5">the values the 6 October analysis linked to the rise; each with its one-month change and date</span></h3>
    <div class="gr-strip">${cells}</div><div class="chart-meta">${escText30((G.footnotes || {}).brent || "")}</div></div>`;
}
function renderGlobalRatesE(){
  const G = S.globalRates; const E = G && G.panel_e; if (!E) return "";
  const fmtV = s => s.measured == null ? "—" : s.unit === "bp" ? grSgn(s.measured, 0, "bp") : s.unit === "%" ? (s.id === "japan_above_3" ? Number(s.measured).toFixed(3) + "%" : grSgn(s.measured, 1, "%")) : s.measured;
  const thr = s => `${s.op} ${s.unit === "bp" ? s.threshold + "bp" : s.unit === "%" ? s.threshold + "%" : s.threshold}`;
  const line = s => `<tr><td><span class="es-badge ${s.present == null ? "c-3" : s.present ? "c-warn" : "c-pos"} w6">${s.present == null ? "n/a" : s.present ? "present" : "absent"}</span></td>
      <td class="c-2">${escText30(s.text)}</td><td class="num c-1 w6">${fmtV(s)}</td><td class="num c-3">${thr(s)}</td><td class="c-3">${grDate(s.as_of)}${s.also ? ` · same-day front-month ${grSgn(s.also.measured, 1, "%")} (${grDate(s.also.as_of)})` : ""}</td></tr>`;
  const tbl = (title, lst) => `<div class="mono t1 w6 c-2 mt2 ls08">${title}</div><div class="tbl-scroll"><table class="th-table stack-m"><tr><th>STATE</th><th>CONDITION</th><th class="num">MEASURED</th><th class="num">THRESHOLD</th><th>AS OF</th></tr>${lst.map(line).join("")}</table></div>`;
  return `<div class="rcc-card"><h3>SIGNALS OF WORSENING AND OF REVERSAL · <span class="c-3 w5">${escText30(E.heading || "")}</span></h3>
    ${tbl("WORSENING", E.worsening || [])}${tbl("REVERSAL", E.reversal || [])}
    <div class="chart-meta">${escText30(E.brent_note || "")} · thresholds in data/rates/global_rates_config.json</div></div>`;
}
// home: one line under the regime gauge
function renderRatesStrip(){
  const H = (S.globalRatesHome && S.globalRatesHome.home) || null; if (!H) return "";
  const short = {us10: "U.S. 10y", us_real10: "real", us_be10: "breakeven", us_tp_kw: "term premium", jp10: "Japan 10y", brent_front: "Brent front-month"};
  const cells = H.map(x => `<span class="nowrap"><span class="c-3">${short[x.series] || x.series}</span> <span class="c-1 w6">${x.unit === "usd" ? "$" + Number(x.value).toFixed(2) : grPct(x.value, x.series === "jp10" ? 3 : 2)}</span> <span class="c-2">${x.unit === "usd" ? grSgn(x.chg_1d, 2) : grBp(x.chg_1d)}</span> <span class="c-3 t1">${grDate(x.date).slice(5)}</span></span>`).join(' <span class="c-3">·</span> ');
  return `<div class="rates-strip mono t1 mt2">${cells} <a class="c-3 t1" href="bonds.html">· global rates on the bonds page</a></div>`;
}
function renderGlobalRatesCharts(){
  const G = S.globalRates; if (!G) return;
  const CV = CHARTS.colors();
  const pal = {US: CV.accent, DE: CV.info, GB: CV.warn, JP: CV.neg, FR: CV.pos, IT: CV.n1, CA: CV.n2};
  const ts = d => new Date(d + "T12:00:00Z").getTime();
  const xTime = {type: "linear", ticks: {callback: v => new Date(v).toISOString().slice(0, 7), maxTicksLimit: 7}};
  const make = (id, key, cfg) => { const ctx = document.getElementById(id); if (!ctx) return;
    if (S[key]) { try { S[key].destroy(); } catch(e){} }
    try { S[key] = CHARTS.make(ctx, cfg); } catch(e){ console.error("[global-rates]", id, e); } };
  const A = G.panel_a;
  if (A){
    const name = c => (A.rows.find(r => r.code === c) || {}).name || c;
    make("gr-a-levels", "grALevels", {type: "line", data: {datasets: Object.entries(A.chart || {}).map(([c, pts]) => ({label: name(c), data: pts.map(p => ({x: ts(p[0]), y: p[1]})), borderColor: pal[c], borderWidth: c === "US" ? 2 : 1.5, pointRadius: 0, tension: 0.1}))},
      options: {parsing: true, scales: {x: xTime, y: {ticks: {callback: v => Number(v).toFixed(1) + "%"}}}, plugins: {tooltip: {callbacks: {title: it => new Date(it[0].parsed.x).toISOString().slice(0, 10), label: c => ` ${c.dataset.label}: ${c.parsed.y.toFixed(2)}%`}}}}});
    make("gr-a-change", "grAChange", {type: "line", data: {datasets: Object.entries(A.change_since || {}).map(([c, o]) => ({label: name(c), data: o.points.map(p => ({x: ts(p[0]), y: p[1]})), borderColor: pal[c], borderWidth: c === "US" ? 2 : 1.5, pointRadius: 0, tension: 0.1}))},
      options: {scales: {x: xTime, y: {ticks: {callback: v => (v >= 0 ? "+" : "") + v + "bp"}}}, plugins: {tooltip: {callbacks: {title: it => new Date(it[0].parsed.x).toISOString().slice(0, 10), label: c => ` ${c.dataset.label}: ${c.parsed.y >= 0 ? "+" : ""}${Math.round(c.parsed.y)}bp`}}}}});
  }
  const B = G.panel_b;
  if (B){
    const pts = (o, k) => o.dates.map((d, i) => ({x: ts(d), y: o[k][i]})).filter(p => p.y != null);
    const fillA = c => CHARTS.alpha(c, 0.18);
    make("gr-b1", "grB1", {type: "line", data: {datasets: [
        {label: "real yield", data: pts(B.b1, "real"), borderColor: CV.info, backgroundColor: fillA(CV.info), fill: "origin", borderWidth: 1.5, pointRadius: 0},
        {label: "nominal 10-year", data: pts(B.b1, "nominal"), borderColor: CV.accent, backgroundColor: fillA(CV.warn), fill: {target: 0}, borderWidth: 2, pointRadius: 0},
        {label: "breakeven", data: pts(B.b1, "breakeven"), borderColor: CV.warn, borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false}]},
      options: {scales: {x: xTime, y: {ticks: {callback: v => Number(v).toFixed(1) + "%"}}}, plugins: {tooltip: {callbacks: {title: it => new Date(it[0].parsed.x).toISOString().slice(0, 10), label: c => ` ${c.dataset.label}: ${c.parsed.y.toFixed(2)}%`}}}}});
    make("gr-b2", "grB2", {type: "line", data: {datasets: [
        {label: "expected short rate", data: pts(B.b2, "expected_short_rate"), borderColor: CV.info, backgroundColor: fillA(CV.info), fill: "origin", borderWidth: 1.5, pointRadius: 0},
        {label: "nominal 10-year", data: B.b2.dates.map((d, i) => (B.b2.expected_short_rate[i] != null && B.b2.nominal[i] != null) ? {x: ts(d), y: B.b2.nominal[i]} : null).filter(Boolean), borderColor: CV.accent, backgroundColor: fillA(CV.neg), fill: {target: 0}, borderWidth: 2, pointRadius: 0},
        {label: "term premium (Kim-Wright)", data: pts(B.b2, "term_premium_kw"), borderColor: CV.neg, borderWidth: 1.5, pointRadius: 0, fill: false},
        {label: "term premium (ACM)", data: pts(B.b2, "term_premium_acm"), borderColor: CV.n1, borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false}]},
      options: {scales: {x: xTime, y: {ticks: {callback: v => Number(v).toFixed(1) + "%"}}}, plugins: {tooltip: {callbacks: {title: it => new Date(it[0].parsed.x).toISOString().slice(0, 10), label: c => ` ${c.dataset.label}: ${c.parsed.y.toFixed(2)}%`}}}}});
  }
}

function renderBondsCurve(){
  const s = S.bondsStates; if (!s || !s.curve) return `<div class="rcc-card"><h3>THE CURVE</h3><div class="mono t1 c-3">data/bonds/states.json not loaded</div></div>`;
  const c = s.curve; const clr = _CURVE_STATE_CLR[c.state] || "c-2";
  const mats = (c.maturities || []).map(m => `<tr><td class="mono t2 c-1 w6">${m.maturity}</td><td class="num c-2">${m.level_pct == null ? "<span class='c-3'>unavailable</span>" : _bpct(m.level_pct)}</td><td class="num c-3">${m.pctile_10y == null ? "—" : m.pctile_10y + "th"}</td></tr>`).join("");
  return `<div class="rcc-card"><h3>THE CURVE · <span class="c-3 w5">Treasury level and slope, and each maturity's place in its ten-year range</span>${asOfBadge(c.as_of || s.session_date, {lag: 1})}</h3>
    <div class="dd-body"><div class="dd-wrap"><canvas id="bonds-curve-chart" height="220"></canvas></div>
    <div class="stress-panel"><div class="fx-head mono t1 c-3">STATE · <span class="${clr} w6">${(c.state||"—").toUpperCase()}</span></div>
      <div class="mono t1 c-2 mt1">2s10s slope <span class="c-1 w6">${c.slope_2s10s_bps == null ? "—" : c.slope_2s10s_bps + "bp"}</span> · ${c.slope_2s10s_pctile_10y == null ? "—" : c.slope_2s10s_pctile_10y + "th percentile over ten years"}</div>
      <div class="mono t1 c-3 mt1">3m10y ${c.slope_3m10y_pct == null ? "—" : _bpct(c.slope_3m10y_pct)}</div>
      <table class="stress-table mt1"><tr><th>MATURITY</th><th class="num">YIELD</th><th class="num">10y %ILE</th></tr>${mats}</table>
    </div></div>
    <div class="chart-meta">${c.footnote || ""} · vintage: ${(s.vintage && s.vintage.store) || "—"}</div></div>`;
}

function renderBondsCurveChart(){
  const s = S.bondsStates; const ch = s && s.curve && s.curve.chart; const ctx = document.getElementById("bonds-curve-chart");
  if (!ch || !ctx) return;
  if (S.bondsCurveChart){ try { S.bondsCurveChart.destroy(); } catch(e){} }
  const CV = CHARTS.colors();
  const styles = [{c: CV.pos, w: 2.5, d: []}, {c: CV.info, w: 1.5, d: [4,3]}, {c: CV.neg, w: 1.5, d: [2,3]}];
  const datasets = (ch.series || []).map((ser, i) => ({
    label: ser.label, data: ser.yields.map(y => y == null ? null : y),
    borderColor: styles[i].c, borderWidth: styles[i].w, borderDash: styles[i].d,
    tension: 0.2, pointRadius: 3, pointBackgroundColor: styles[i].c, spanGaps: true, fill: false }));
  try {
    S.bondsCurveChart = CHARTS.make(ctx, {
      type: "line",
      data: { labels: ch.maturities, datasets },
      options: { plugins: { tooltip: { callbacks: { label: c => ` ${c.dataset.label}: ${c.parsed.y == null ? "n/a" : c.parsed.y.toFixed(2) + "%"}` } } },
        scales: { y: { ticks: { callback: v => Number(v).toFixed(1) + "%" } } } },
    });
  } catch(e){ console.error("[bonds-curve] Chart.js failed:", e); }
}

function renderBondsCredit(){
  const s = S.bondsStates; if (!s || !s.credit) return "";
  const c = s.credit; const leg = (x, name) => {
    const clr = _CREDIT_STATE_CLR[x.state] || "c-2";
    return `<div class="so-cell"><div class="k">${name}</div><div class="v ${clr}">${x.oas_bps == null ? "—" : x.oas_bps + "bp"}</div><div class="s">${x.pctile_10y == null ? "" : x.pctile_10y + "th percentile · " + (x.state || "")}</div></div>`;
  };
  return `<div class="rcc-card"><h3>CREDIT SPREADS · <span class="c-3 w5">investment grade and high yield against their own history (up to ten years; FRED's ICE BofA series start ${(c.hy && c.hy.pctile_window_from) || "2023-06"})</span>${asOfBadge(c.ig && c.ig.as_of || s.session_date, {lag: 1})}</h3>
    <div class="so-strip">${leg(c.ig, "IG OAS")}${leg(c.hy, "HY OAS")}</div>
    <div class="chart-meta">${c.duration_caveat || ""}</div>
    <div class="chart-meta">${c.footnote || ""}</div></div>`;
}

function renderBondsBreakeven(){
  const s = S.bondsStates; const r = s && s.real_nominal; if (!r) return "";
  return `<div class="rcc-card"><h3>REAL VS NOMINAL · <span class="c-3 w5">the 10-year breakeven as priced inflation, and the real yield</span>${asOfBadge(r.as_of || s.session_date, {lag: 1})}</h3>
    <div class="so-strip">
      <div class="so-cell"><div class="k">10Y BREAKEVEN</div><div class="v c-1">${_bpct(r.breakeven_10y_pct)}</div><div class="s">${r.breakeven_10y_pctile_10y == null ? "" : r.breakeven_10y_pctile_10y + "th percentile · priced inflation"}</div></div>
      <div class="so-cell"><div class="k">REAL 10Y YIELD</div><div class="v c-2">${r.real_10y_yield_pct == null ? "<span class='c-3'>unavailable</span>" : _bpct(r.real_10y_yield_pct)}</div><div class="s">${r.real_10y_yield_pct == null ? "DFII10 pending FRED fetch" : "DFII10"}</div></div>
      <div class="so-cell"><div class="k">5y5y FORWARD</div><div class="v c-2">${r.fwd_5y5y_infl_pct == null ? "<span class='c-3'>unavailable</span>" : _bpct(r.fwd_5y5y_infl_pct)}</div><div class="s">${r.fwd_5y5y_infl_pct == null ? "T5YIFR pending FRED fetch" : "T5YIFR"}</div></div>
    </div>
    <div class="chart-meta">${r.footnote || ""}</div></div>`;
}

function renderBondsRatesRegime(){
  const s = S.bondsStates; const rr = s && s.rates_regime; if (!rr) return "";
  return `<div class="rcc-card"><h3>THE RATES REGIME ${_diagChip()} · <span class="c-3 w5">a combined curve-plus-credit state, a diagnostic lens</span>${asOfBadge(s.session_date)}</h3>
    <div class="mono t2 c-1 w7">${(rr.state || "—").toUpperCase()}</div>
    <div class="mono t1 c-2 mt1">${rr.basis || ""} · favours ${rr.favors || ""}</div>
    <div class="mono t1 c-3 mt1">inputs: curve ${(rr.inputs && rr.inputs.curve_state) || "—"} · IG ${(rr.inputs && rr.inputs.credit_ig_state) || "—"} · HY ${(rr.inputs && rr.inputs.credit_hy_state) || "—"}</div>
    <div class="chart-meta c-warn">${rr.gate || ""}</div>
    <div class="chart-meta">registration: ${rr.registration || ""}</div></div>`;
}

function renderBondsAllocationReads(){
  const s = S.bondsStates; const a = s && s.allocation_questions; if (!a) return "";
  const card = (q) => q ? `<div class="th-pending-wrap"><div class="mono t1 w6 c-1">${q.question}</div><div class="mono t1 c-2 mt1">${q.read || ""}</div>${q.basis ? `<div class="mono t1 c-3 mt1">basis: ${q.basis}</div>` : ""}<div class="chart-meta">${q.note || ""}${(q.footnotes || []).map(f => ` · ${f}`).join("")}</div></div>` : "";
  return `<div class="rcc-card"><h3>THE ALLOCATION READS · <span class="c-3 w5">observable, evidence-based; each registered before it runs; no rate forecast</span>${asOfBadge(s.session_date)}</h3>
    ${card(a.duration)}${card(a.credit)}${card(a.real_vs_nominal)}</div>`;
}

function bondsSortBy(key){
  const cur = S._bondsSort || {key: "correlation_to_book", dir: 1};
  S._bondsSort = (cur.key === key) ? {key, dir: -cur.dir} : {key, dir: (key === "correlation_to_book" ? 1 : -1)};
  if (typeof render === "function") render();
}
function renderBondsSleeveMenu(){
  const m = S.bondsStates && S.bondsStates.book_integration && S.bondsStates.book_integration.menu; if (!m) return "";
  const sort = S._bondsSort || {key: "correlation_to_book", dir: 1};
  const rows = (m.sleeves || []).slice().sort((x, y) => {
    const a = x[sort.key], b = y[sort.key];
    if (a == null) return 1; if (b == null) return -1;
    return (a > b ? 1 : a < b ? -1 : 0) * sort.dir;
  });
  // order 1-Oct-2026 [R3.3]: the carry columns are curve-implied (yield, pickup over bills, the breakeven rise
  // that erases it); the trailing distribution yield stays, retitled; yield per unit of duration is gone
  const cols = [["ticker","SLEEVE"],["curve_implied_yield_pct","CURVE-IMPLIED"],["pickup_bp","PICKUP"],["breakeven_rise_bp","BE RISE"],["effective_duration","DURATION"],["distribution_yield_pct","TRAILING DIST."],["vol_126_ann","VOL 126"],["correlation_to_book","CORR→BOOK"]];
  const tips = {curve_implied_yield_pct: "CMT par yield at the sleeve's weighted-average maturity (plus the bucket OAS for credit)", pickup_bp: "curve-implied yield minus 3-month bills, bp",
                breakeven_rise_bp: "the parallel rise over a year that erases the pickup: pickup / duration (roll-down and convexity omitted)", distribution_yield_pct: "trailing distribution yield (income; lags rate moves)"};
  const head = cols.map(([k,l]) => `<th class="${k==="ticker"?"":"num"} ptr" title="${tips[k] || ""}" onclick="bondsSortBy('${k}')">${l}${sort.key===k?(sort.dir>0?" ▲":" ▼"):""}</th>`).join("");
  const body = rows.map(r => {
    const corr = r.correlation_to_book; const c = corr == null ? 0 : corr;
    const bar = `<span class="sleeve-bar"><span class="sleeve-zero"></span><span class="sleeve-fill ${c>=0?"bg-warn":"bg-pos"}" style="left:${c>=0?50:50+c*50}%;width:${Math.abs(c)*50}%"></span></span>`;
    return `<tr><td class="mono t2 c-1 w6" title="${r.role||""}">${r.ticker}</td>
      <td class="num c-1" title="${r.curve_implied_reason || ""}">${r.curve_implied_yield_pct != null ? _bpct(r.curve_implied_yield_pct,2) : (r.real_yield_pct != null ? `${_bpct(r.real_yield_pct,2)} real` : "—")}</td>
      <td class="num c-2">${r.pickup_bp != null ? r.pickup_bp.toFixed(0) + "bp" : "—"}</td>
      <td class="num c-2">${r.breakeven_rise_bp != null ? r.breakeven_rise_bp.toFixed(0) + "bp" : "—"}</td>
      <td class="num c-2">${_bnum(r.effective_duration,2)}</td>
      <td class="num c-3">${_bpct(r.distribution_yield_pct,2)}</td>
      <td class="num c-3">${r.vol_126_ann==null?"—":_bpct(r.vol_126_ann*100,1)}</td>
      <td class="num c-1">${corr==null?"—":corr.toFixed(2)} ${bar}</td></tr>`;
  }).join("");
  return `<div class="rcc-card"><h3>THE SLEEVE MENU · <span class="c-3 w5">sorted by correlation to the book — a sleeve's value here is its correlation with what is held, not its yield</span>${asOfBadge(S.bondsStates.session_date)}</h3>
    <div class="tbl-scroll"><table class="sleeves-table"><tr>${head}</tr>${body}</table></div>
    <div class="chart-meta">${m.note || ""} · curve-implied: the CMT par-yield curve at each sleeve's weighted-average maturity (semiannual basis; a fund's portfolio yield differs by coupon, convexity and composition); "real" marks TIP's real yield, excluded from nominal comparisons; a dash means no public curve or spread series matches the sleeve (hover for the reason) · trailing dist.: income paid over the past year, lags rate moves · click a header to sort</div></div>`;
}

function renderBondsConditional(){
  const cm = S.bondsStates && S.bondsStates.book_integration && S.bondsStates.book_integration.conditional_message; if (!cm) return "";
  const tn = cm.top_name || {};
  return `<div class="rcc-card"><h3>ADDING A SLEEVE TO THIS BOOK · <span class="c-3 w5">the marginal effect on volatility and stress loss, at the book's current concentration</span>${holdingsPill()}${intradayBadge(S.bondsStates)}</h3>
    ${cm.fires ? `<div class="mono t1 c-warn w5">${cm.message || ""}</div>` : `<div class="mono t1 c-2">Top-name risk share ${tn.risk_share==null?"—":(tn.risk_share*100).toFixed(0)+"%"} (below 40%): diversification effects are not concentration-limited.</div>`}
    <div class="chart-meta">${cm.note || ""}</div></div>`;
}

function renderBondsWholeStress(){
  const w = S.bondsStates && S.bondsStates.book_integration && S.bondsStates.book_integration.whole_portfolio_stress; if (!w) return "";
  const eq = (w.equity_scenarios || []).map(s => `<tr><td class="c-2">${s.label||s.id}</td><td class="num c-neg">${s.share_nav==null?"—":(s.share_nav*100).toFixed(1)+"%"}</td></tr>`).join("");
  const fi = (w.fixed_income && w.fixed_income.sleeves || []).map(r => `<tr><td class="mono t2 c-1 w6">${r.ticker}</td><td class="num c-neg">${r.rate_up_100bp==null?"—":(r.rate_up_100bp*100).toFixed(1)+"%"}</td><td class="num c-pos">${r.rate_down_100bp==null?"—":"+"+(r.rate_down_100bp*100).toFixed(1)+"%"}</td><td class="num c-neg">${r.spread_widen_return==null?"—":(r.spread_widen_return*100).toFixed(1)+"%"}</td></tr>`).join("");
  const sp = w.fixed_income && w.fixed_income.spread_shock || {};
  return `<div class="rcc-card"><h3>WHOLE-PORTFOLIO STRESS · <span class="c-3 w5">the equity book's scenarios beside each sleeve's rate and spread sensitivity — one portfolio</span>${holdingsPill()}${intradayBadge(S.bondsStates)}</h3>
    <div class="book-grid">
      <div><div class="fx-head mono t1 c-3">EQUITY BOOK (actual losses, share of NAV)</div>
        <table class="stress-table"><tr><th>SCENARIO</th><th class="num">OF NAV</th></tr>${eq}</table></div>
      <div><div class="fx-head mono t1 c-3">FIXED-INCOME SLEEVES (per-sleeve sensitivity)</div>
        <table class="stress-table"><tr><th>SLEEVE</th><th class="num">+100bp</th><th class="num">−100bp</th><th class="num">SPREAD→90th</th></tr>${fi}</table></div>
    </div>
    <div class="chart-meta">rate shock ±100bp via duration; spread shock to the 90th-percentile OAS (IG ${sp.ig&&sp.ig.current_bps}→${sp.ig&&sp.ig.p90_bps}bp, HY ${sp.hy&&sp.hy.current_bps}→${sp.hy&&sp.hy.p90_bps}bp) via spread duration. ${w.note || ""}</div></div>`;
}

// Fixed-income retirement registration (evidence page): the three bond tests are registered,
// not run; the rates-regime state stays DIAGNOSTIC until Test 1 passes its paired criterion.
function renderBondsRegistrationCard(){
  const rr = S.bondsStates && S.bondsStates.rates_regime; if (!rr) return "";
  return `<div class="rcc-card"><h3>FIXED-INCOME RETIREMENT TESTS ${_diagChip()} · <span class="c-3 w5">registered, not run — three rules by the method of the regime test</span></h3>
    <div class="mono t1 c-2">Rates-regime vs static duration and a constant-maturity ladder · a carry rule (highest yield-per-duration sleeve) vs equal-weight · credit-timing (add HY when spreads are wide, reduce when tight) vs static credit.</div>
    <div class="mono t1 c-3 mt1">Paired difference on common resampled paths (60-session blocks, 1,000 resamples), point-in-time yields and spreads, costs at one third of quoted bid-ask width. The rates-regime state (bonds page) is gated DIAGNOSTIC and drives no sizing until Test 1 passes; adoption is a separate written decision.</div>
    <div class="chart-meta">registration: ${rr.registration || "reports/bonds_retirement_registration_2026-09-16.md"}</div></div>`;
}

// ── Options lens: the event board (3.4) and the hedge selector (Phase 4), book page ──────
function renderEventBoard(){
  const L = S.optionsLens; if (!L || !L.names) return "";
  const b = S.book || {}; const pos = {}; (b.positions || []).forEach(p => { pos[p.ticker] = p; });
  const rows = Object.entries(L.names)
    .filter(([tk, o]) => (o.roles || []).includes("held") && o.event && o.event.days_to != null && o.event.days_to >= 0 && o.event.days_to <= 45)
    .sort((a, b) => a[1].event.days_to - b[1].event.days_to)
    .map(([tk, o]) => { const e = o.event, h = e.history || {}, l8 = h.last8 || {}; const p = pos[tk] || {};
      const dollars = (e.implied_move != null && p.value != null) ? e.implied_move * p.value : null;
      return `<tr><td class="mono t2 c-1 w6">${tk}</td><td class="c-2">${e.next_earnings} <span class="c-3">(${e.days_to}d, ${e.time_of_day ? e.time_of_day.replace("_", " ") : ""})</span></td>
        <td class="num c-1 w6">${e.implied_move != null ? "±" + optPct(e.implied_move) : "—"}</td><td class="num c-2">${dollars != null ? "±" + fmtMoney(dollars) : "—"}</td>
        <td class="num c-2">${optPct(h.median_abs)}</td><td class="num c-3">${optPct(h.max_abs)}</td>
        <td class="num c-2">${l8.n_exceeding_implied != null ? `${l8.n_exceeding_implied} of ${l8.n}` : "—"}</td>
        <td class="num c-1">${p.risk_share != null ? (p.risk_share * 100).toFixed(0) + "%" : "—"}</td></tr>`; }).join("");
  return `<div class="rcc-card"><h3>EVENT BOARD · <span class="c-3 w5">every held name with an earnings release in the next 45 days — where the next binary exposure sits and what the market prices for it</span>${holdingsPill()}${optionsAgeBadge(L.session_date)}</h3>
    ${rows ? `<div class="tbl-scroll"><table class="th-table stack-m"><tr><th>NAME</th><th>RELEASE</th><th class="num">IMPLIED MOVE</th><th class="num">ON THE POSITION</th><th class="num">MEDIAN PAST</th><th class="num">MAX PAST</th><th class="num">LAST 8 EXCEEDED</th><th class="num">SHARE OF BOOK RISK</th></tr>${rows}</table></div>`
           : `<div class="mono t1 c-3">no held name reports inside 45 days</div>`}
    <div class="chart-meta">implied move: bracketing method — the last expiry before the release against the first after it, event variance = post total variance − pre total variance − the pre-expiry base over the non-event sessions (fallback without a pre-event expiry flagged; lens definitions) · past reactions: close before the release to close after · descriptive; no directional implication</div></div>`;
}

function renderHedgeSelector(){
  const H = S.optionsHedges; if (!H || !H.positions) return "";
  const money = v => v == null ? "—" : (v < 0 ? "−" : "") + fmtMoney(Math.abs(v));
  const cards = Object.entries(H.positions).map(([tk, p]) => {
    const ctx = `spot $${p.spot} · ${p.shares} shares · risk share ${p.risk_share != null ? (p.risk_share * 100).toFixed(0) + "%" : "—"} · volatility ${p.volatility_state || "—"}${p.term_inverted ? " · term inverted" : ""}${p.next_earnings ? " · earnings " + p.next_earnings : ""}${p.implied_move != null ? " (market prices ±" + optPct(p.implied_move) + ")" : ""}${p.embedded_gain != null ? " · " + (p.embedded_gain >= 0 ? "+" : "") + (p.embedded_gain * 100).toFixed(0) + "% on cost" : ""}${p.impaired ? ' · <span class="c-warn">quotes impaired</span>' : ""}`;
    const tenors = (p.tenors || []).map(t => {
      const rows = (t.structures || []).map(s => { const sp = (s.stress || []).find(x => x.id === "spy_-20") || {}; const sm = (s.stress || []).find(x => x.id === "smh_-30") || {}; const s34 = (s.stress || []).find(x => x.id === "spy_-34") || {};
        const st = x => x.book_share_nav_with_structure != null ? (x.book_share_nav_with_structure * 100).toFixed(1) + "%" : "—";
        return `<tr class="${s.excluded ? "dim" : ""}"><td class="num c-3">${s.rank ?? "×"}</td><td class="c-2">${s.label}${s.quote_flags && s.quote_flags.includes("last") ? ' <span class="c-3 t1" title="a leg priced at the last trade, no live bid-ask">(last)</span>' : ""}</td>
          <td class="num ${s.net_kind === "credit" ? "c-pos" : "c-warn"}">${s.net_kind} $${Math.abs(s.net_per_share).toFixed(2)}</td><td class="num c-2">${money(s.net_on_position)}</td>
          <td class="num c-2">${s.floor != null ? "$" + s.floor : "—"}${s.floor_note ? ' <span class="c-3" title="' + s.floor_note + '">*</span>' : ""}</td><td class="num c-2">${s.cap != null ? "$" + s.cap : "—"}</td><td class="num c-3">$${s.breakeven}</td><td class="num c-3">${s.delta_change_per_share != null ? (s.delta_change_per_share >= 0 ? "+" : "") + s.delta_change_per_share.toFixed(2) : "—"}</td>
          <td class="num c-2" title="book loss, share of NAV, with the structure in place: SMH −30 / SPY −20 / SPY −34">${st(sm)} / ${st(sp)} / ${st(s34)}</td>
          <td class="c-3 t1">${(s.ranked_by || []).join("; ")}</td><td class="c-warn t1 w6" title="${s.diagnostic}">DIAGNOSTIC</td></tr>`; }).join("");
      const un = ((t.structures || [])[0] || {}).stress || []; const u = x => { const r = un.find(y => y.id === x); return r && r.book_share_nav_unhedged != null ? (r.book_share_nav_unhedged * 100).toFixed(1) + "%" : "—"; };
      return `<div class="mt2"><div class="mono t1 w6 c-2">${t.tenor.replace("_", " ").toUpperCase()} · ${t.expiry} (${t.days}d)${t.earnings_inside ? ' · <span class="c-warn">earnings inside the tenor</span>' : ""} · unhedged book loss SMH −30 / SPY −20 / SPY −34: ${u("smh_-30")} / ${u("spy_-20")} / ${u("spy_-34")}</div>
        <div class="tbl-scroll"><table class="th-table stack-m"><tr><th>#</th><th>STRUCTURE</th><th class="num">NET / SH</th><th class="num">ON POSITION</th><th class="num">FLOOR</th><th class="num">CAP</th><th class="num">BREAKEVEN</th><th class="num">Δ</th><th class="num">BOOK LOSS WITH STRUCTURE</th><th>RANKED BY</th><th></th></tr>${rows}</table></div></div>`; }).join("");
    return `<details class="mt2" open><summary class="mono t2 w7 c-1 ptr">${tk} <span class="mono t1 w5 c-3">· ${ctx}</span></summary>${p.embedded_gain_note ? `<div class="mono t1 c-3 mt1">${p.embedded_gain_note}</div>` : ""}${tenors}</details>`;
  }).join("");
  return `<div class="rcc-card"><h3>THE HEDGE SELECTOR <span class="mono t1 w6 r1 x2 c-warn ls06">DIAGNOSTIC</span> · <span class="c-3 w5">four structures priced and ranked on the live chain for each held name, at the first expiry beyond earnings and at about 90 days</span>${holdingsPill()}${optionsAgeBadge(H.session_date)}</h3>
    <div class="mono t1 c-warn">${H.label}</div>
    ${cards}
    <div class="chart-meta">${H.pricing} · ${H.stress_method} · selection rules fixed in data/options/hedge_rules.json (${(H.rules || []).length} rules, pre-registered) · ${H.note}</div></div>`;
}

// ═══ Order 30-Sept-2026: the daily brief (B1–B3), the news (B4), the events board (B5), the amber
//     holdings pill (C4), the house goal and the claims register (D1/D2), realized gains (D3), the
//     per-name insider and ownership blocks (E1/E2). Every panel is descriptive. ═══════════════════
function escText30(s){ return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;"); }
function etStamp30(iso){
  if (!iso) return "—";
  const d = new Date(iso); if (isNaN(d.getTime())) return String(iso).slice(0, 16);
  return d.toLocaleString("en-US", {timeZone: "America/New_York", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"});
}
// C4: "holdings as of {date}, manual" in amber on every panel that uses the holdings, until an export is ingested
function holdingsPill(){
  const hf = S.holdingsFile; if (!hf || !hf.as_of) return "";
  const manual = !/^brokerage export/i.test(String(hf.source || ""));
  return manual ? `<span class="mono t1 w6 r1 x2 c-warn ml2" title="${escText30(hf.source)}">holdings as of ${hf.as_of}, manual</span>` : "";
}
function briefColorCls(c){ return c === "RED" ? "c-neg" : c === "YELLOW" ? "c-warn" : "c-pos"; }
function briefEntryHtml(e, full){
  const cls = e.color || "GREEN";
  const rules = (e.rules_fired || []).map(r => `<span class="brief-rule mono t1" title="${escText30(r.text)} — ${escText30(r.evidence)}">${r.id}</span>`).join("");
  return `<div class="brief-entry ${cls}"><div class="flx gap2 x27"><span class="mono t1 w7 c-1">${e.session}</span><span class="mono t1 w6 ${briefColorCls(cls)}">${cls}</span><span class="mono t1 c-3">${e.text_source === "model" ? "model: " + (e.model || "") : "template"}${e.supersedes ? " · correction of " + e.supersedes : ""}</span></div>
    <div class="serif t2 c-1 lh16 mt1">${escText30(e.text)}</div>
    <div class="mt1">${rules || '<span class="mono t1 c-3">no rule fired</span>'}${full ? ` <span class="mono t1 c-3">· payload ${String(e.payload_sha256 || "").slice(0, 10)} · entry ${String(e.entry_sha256 || "").slice(0, 10)} · logged ${String(e.logged_at || "").slice(0, 16)}</span>` : ""}</div></div>`;
}
function renderBriefStrip(n){   // home: the vertical strip, newest first (B3)
  const L = Array.isArray(S.dailyLog) ? S.dailyLog : [];
  if (!L.length) return `<div class="rcc-card"><h3>THE DAILY BRIEF</h3><div class="mono t1 c-3">no entry yet (data/daily_log.jsonl is written by the nightly)</div></div>`;
  const last = L[L.length - 1];
  const rows = L.slice().reverse().slice(0, n || 10).map(e => briefEntryHtml(e, false)).join("");
  return `<div class="rcc-card brief-card"><h3>THE DAILY BRIEF · <span class="c-3 w5">one colour per session by pre-registered rule · one sentence from the facts payload, under a validator · append-only</span>${asOfBadge(last.session)}</h3>
    <div class="brief-strip">${rows}</div>
    <div class="chart-meta">the colour describes the state of the session; it is not a forecast · rules and thresholds: data/brief_rules.json · the payload behind the latest sentence: data/brief_facts.json · full history on the system page</div></div>`;
}
function renderBriefHistory(){   // system: the full log (B3)
  const L = Array.isArray(S.dailyLog) ? S.dailyLog : []; if (!L.length) return "";
  const R = S.briefRules || {};
  const rows = L.slice().reverse().map(e => briefEntryHtml(e, true)).join("");
  const counts = L.reduce((a, e) => { a[e.color] = (a[e.color] || 0) + 1; return a; }, {});
  return `<div class="rcc-card"><h3>THE DAILY BRIEF · FULL HISTORY · <span class="c-3 w5">${L.length} entries · RED ${counts.RED || 0} · YELLOW ${counts.YELLOW || 0} · GREEN ${counts.GREEN || 0} · entries are never edited; a correction is a new entry referencing the old</span>${asOfBadge(L[L.length - 1].session)}</h3>
    <div class="brief-strip">${rows}</div>
    <div class="chart-meta">rules frozen ${String(R.frozen_at || "").slice(0, 10)} (${(R.rules || []).length} rules: ${(R.rules || []).map(r => r.id).join(" ")}) · ${R.note || ""}</div></div>`;
}
function newsRowHtml(it){
  const tag = it.tier === 1 ? '<span class="tier-tag mono t1 w6 c-1">T1 primary</span>' : '<span class="tier-tag mono t1 w6 c-3">T2 secondary</span>';
  const tags = (it.tickers || []).concat(it.topics || []).join(" ");
  return `<tr class="${it.tier === 1 ? "" : "dim"}"><td class="mono t1 c-3">${etStamp30(it.timestamp)}</td><td>${tag}</td><td class="mono t1 c-2">${escText30(it.source)}</td>
    <td class="serif t1 c-1"><a href="${escText30(it.url)}" target="_blank" rel="noopener">${escText30(it.headline)}</a>${it.disclosure_lag_label ? ` <span class="mono t1 c-warn">· ${escText30(it.disclosure_lag_label)}</span>` : ""}</td><td class="mono t1 c-3">${escText30(tags)}</td></tr>`;
}
function renderNewsPanel(){   // home: the last 24 hours, Tier 1 first (B4)
  const N = S.news;
  if (!N || !N.items) return `<div class="rcc-card"><h3>NEWS</h3><div class="mono t1 c-3">data/news.json not published yet</div></div>`;
  const byId = {}; N.items.forEach(it => { byId[it.id] = it; });
  const items = (N.last24h || []).map(id => byId[id]).filter(Boolean);
  const ex = N.excluded || {}; const st = N.sources_status || {};
  const failed = Object.entries(st).filter(([k, v]) => /^(failed|skipped)/.test(String(v))).map(([k, v]) => `${k}: ${v}`);
  // every primary item shows; secondary items beyond the first six fold under a disclosure (the list ran to 30+ rows).
  // 1-Oct-2026: routine insider filings (Form 4) on names not held fold into one line — with the SEC contact
  // declared they ran to 15 of the 24 hours' items; filings on held names stay in the list.
  const heldSet = new Set(((S.holdingsFile && S.holdingsFile.holdings) || []).filter(h => (h.shares || 0) > 0).map(h => String(h.ticker).toUpperCase()));
  const routineF4 = it => it.source_id === "edgar" && /^Form 4\b/.test(it.headline || "") && !(it.tickers || []).some(t => heldSet.has(String(t).toUpperCase()));
  const f4 = items.filter(routineF4);
  const t1 = items.filter(it => it.tier === 1 && !routineF4(it)), t2 = items.filter(it => it.tier !== 1);
  const shown = t1.concat(t2.slice(0, 6)), more = t2.slice(6);
  const f4Count = {}; f4.forEach(it => (it.tickers && it.tickers.length ? it.tickers : ["?"]).forEach(t => { f4Count[t] = (f4Count[t] || 0) + 1; }));
  const f4Html = f4.length ? `<details class="mt1"><summary class="mono t1 w5 c-3 ptr ls05">${f4.length} insider filing${f4.length > 1 ? "s" : ""} (Form 4) on board names: ${Object.entries(f4Count).map(([t, n]) => n > 1 ? `${t} ${n}` : t).join(", ")}</summary><div class="tbl-scroll"><table class="th-table news-table">${f4.map(newsRowHtml).join("")}</table></div></details>` : "";
  return `<div class="rcc-card news-card"><h3>NEWS · <span class="c-3 w5">last ${N.window_hours || 24} hours · primary sources first, secondary labeled · bodies never stored, summaries system-written</span><span class="asof mono t1 w5 ls06 c-3 ml2">fetched ${etStamp30(N.fetched_at)} ET</span></h3>
    ${items.length ? `<div class="tbl-scroll"><table class="th-table news-table">${shown.map(newsRowHtml).join("")}</table></div>
      ${f4Html}
      ${more.length ? `<details class="mt1"><summary class="mono t1 w5 c-3 ptr ls05">${more.length} more secondary item${more.length > 1 ? "s" : ""}</summary><div class="tbl-scroll"><table class="th-table news-table">${more.map(newsRowHtml).join("")}</table></div></details>` : ""}` : '<div class="mono t1 c-3">no relevant item in the window</div>'}
    <details class="mt2"><summary class="mono t1 w5 c-3 ptr ls05">sources and exclusions</summary><div class="mono t1 c-3 mt1 lh17">${N.rule || ""}<br>withheld: vocabulary rule ${ex.vocabulary_rule || 0} · directive rule ${ex.directive_rule || 0} · irrelevant ${ex.irrelevant || 0}<br>${failed.length ? failed.join("<br>") : "every source responded"}</div></details></div>`;
}
function renderNameNews(tk){   // each held name's card: its last five items (B4)
  const N = S.news; if (!N || !N.items || !N.per_name) return "";
  const byId = {}; N.items.forEach(it => { byId[it.id] = it; });
  const items = (N.per_name[tk] || []).map(id => byId[id]).filter(Boolean).slice(0, 5);
  if (!items.length) return `<div class="name-block mono t1 c-3">news: no item on record for ${tk}</div>`;
  return `<div class="name-block"><div class="mono t1 w6 c-3 ls12 mb1">NEWS · LAST FIVE</div>${items.map(it => `<div class="mono t1 c-2 lh16"><span class="c-3">${etStamp30(it.timestamp)}</span> · ${it.tier === 1 ? '<span class="c-1">T1</span>' : '<span class="c-3">T2</span>'} ${escText30(it.source)} · <a href="${escText30(it.url)}" target="_blank" rel="noopener">${escText30(it.headline)}</a>${it.disclosure_lag_label ? ` <span class="c-warn">· ${escText30(it.disclosure_lag_label)}</span>` : ""}</div>`).join("")}</div>`;
}
function _mondayOf(iso){ const d = new Date(iso + "T12:00:00Z"); const wd = (d.getUTCDay() + 6) % 7; d.setUTCDate(d.getUTCDate() - wd); return d.toISOString().slice(0, 10); }
function _plusDays(iso, n){ const d = new Date(iso + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
function renderEventsBoard(){   // home, below the log: the next 45 days by week, clusters highlighted (B5)
  const cal = S.eventCal || {}; const ev = cal.events || []; if (!ev.length) return "";
  const today = _etDateISO(new Date()); const end = _plusDays(today, 45);
  const held = new Set(((S.holdingsFile && S.holdingsFile.holdings) || []).filter(h => (h.shares || 0) > 0).map(h => String(h.ticker).toUpperCase()));
  const lens = (S.optionsLens && S.optionsLens.names) || {}; const pos = {}; ((S.book && S.book.positions) || []).forEach(p => { pos[p.ticker] = p; });
  const clusters = {}; (cal.clusters || []).forEach(c => { clusters[c.date] = c; });
  const inWin = ev.filter(e => e.date >= today && e.date <= end && e.type !== "TREASURY" && e.type !== "REFUNDING");   // R6.3 (1-Oct-2026): the pre-R6 type set
  const weeks = {};
  inWin.forEach(e => { const k = _mondayOf(e.date); (weeks[k] = weeks[k] || []).push(e); });
  const imp = e => `<span class="imp imp-${e.impact || "medium"}">${(e.impact || "—").toUpperCase()}</span>`;
  const dayName = iso => new Date(iso + "T12:00:00Z").toLocaleDateString("en-US", {weekday: "short", timeZone: "UTC"});
  const body = Object.keys(weeks).sort().map(k => {
    const es = weeks[k].slice().sort((a, b) => a.date.localeCompare(b.date) || String(a.time_et || "").localeCompare(String(b.time_et || "")) || a.type.localeCompare(b.type));
    const boardEarn = es.filter(e => e.type === "EARNINGS" && !held.has(String(e.ticker).toUpperCase()));
    const rows = es.filter(e => !(e.type === "EARNINGS" && !held.has(String(e.ticker).toUpperCase()))).map(e => {
      const cl = clusters[e.date]; const isCl = cl && (e.impact === "high" || (e.type === "EARNINGS" && cl.earnings.includes(String(e.ticker).toUpperCase())));
      let detail = escText30(e.name || "");
      if (e.type === "EARNINGS") {
        const tk = String(e.ticker).toUpperCase(); const o = lens[tk]; const p = pos[tk] || {}; const em = o && o.event ? o.event : null;
        const dollars = (em && em.implied_move != null && p.value != null) ? em.implied_move * p.value : null;
        detail = `${tk} earnings${em && em.time_of_day ? " (" + em.time_of_day.replace("_", " ") + ")" : ""}${em && em.implied_move != null ? ` · market prices ±${optPct(em.implied_move)}${dollars != null ? " · ±" + fmtMoney(dollars) + " on the position" : ""}${em.fallback ? " (fallback method)" : ""}` : " · implied move unavailable"}`;
      }
      return `<tr class="${isCl ? "cluster" : ""}"><td class="mono t1 c-2">${dayName(e.date)} ${e.date.slice(5)}</td><td class="mono t1 c-3">${e.time_et ? e.time_et + " ET" : ""}</td><td class="mono t1 c-1 w6">${escText30(e.label || e.type)}</td><td>${imp(e)}</td><td class="serif t1 c-2">${detail}${isCl ? ` <span class="mono t1 w6 c-warn">· CLUSTER: ${cl.macro.join(", ")} with ${cl.earnings.join(", ")} earnings</span>` : ""}</td></tr>`;
    }).join("");
    const extra = boardEarn.length ? `<tr><td colspan="5" class="mono t1 c-3">+ ${boardEarn.length} other names' earnings (board and register): ${boardEarn.map(e => `${e.ticker} ${e.date.slice(5)}`).join(", ")}</td></tr>` : "";
    return `<tr><td colspan="5" class="ev-week">WEEK OF ${k}</td></tr>${rows}${extra}`;
  }).join("");
  return `<div class="rcc-card events-card"><h3>EVENTS · NEXT 45 DAYS · <span class="c-3 w5">scheduled releases by week with their impact level; held-name earnings with the options lens's implied move; a high-impact release on a held name's earnings date is a cluster</span>${holdingsPill()}${asOfBadge(cal.as_of)}${S.optionsLens ? optionsAgeBadge(S.optionsLens.session_date) : ""}</h3>
    <div class="tbl-scroll"><table class="th-table events-table"><tr><th>DATE</th><th>TIME</th><th>EVENT</th><th>IMPACT</th><th>DETAIL</th></tr>${body}</table></div>
    <div class="chart-meta">calendar from the agencies' published schedules (provenance per event in data/event_calendar.json) · earnings dates from the provider, estimated until confirmed · descriptive; no directional implication</div></div>`;
}
function renderHouseGoalCard(){   // book: D1
  const G = S.goals; const h = G && G.house_goal; if (!h) return `<div class="rcc-card"><h3>HOUSE GOAL</h3><div class="mono t1 c-3">data/goals.json not published yet</div></div>`;
  const brl = v => v == null ? "—" : "R$" + fmt(Math.round(v)); const usd = v => v == null ? "—" : "$" + fmt(Math.round(v));
  const pc = v => v == null ? "—" : (v * 100).toFixed(1) + "%";
  const cell = (k, v, s, cls) => `<div class="so-cell"><div class="k">${k}</div><div class="v ${cls || "c-1"}">${v}</div><div class="s">${s || ""}</div></div>`;
  const fx = h.fx || {};
  const sens = (h.fx_sensitivity || []).map(r => `<tr><td class="mono t1 c-2">${(+r.rate).toFixed(2)}</td><td class="num">${usd(r.target_usd)}</td><td class="num">${brl(r.book_brl)}</td><td class="num">${pc(r.share_of_target_book)}</td></tr>`).join("");
  const sav = (h.monthly_savings || []).map(s => `<tr><td class="mono t1 c-2">${(s.annual_return * 100).toFixed(0)}% a year</td><td class="num c-1 w6">${brl(s.monthly_brl)}</td><td class="num">${usd(s.monthly_usd_at_rate)}</td></tr>`).join("");
  return `<div class="rcc-card goal-card"><h3>HOUSE GOAL · <span class="c-3 w5">R$${fmt(h.target_brl)} by ${h.horizon_end} · in reais at the ${fx.mode === "intraday" ? "live" : "last"} rate</span>${holdingsPill()}${intradayBadge(G)}</h3>
    <div class="so-strip">
      ${cell("TOTAL BOOK IN REAIS", brl(h.book_brl), `${pc(h.share_of_target_book)} of the target · ${usd(h.book_usd)} at USDBRL ${fx.rate != null ? (+fx.rate).toFixed(4) : "—"} (${fx.as_of || "—"})`)}
      ${cell("CASH IN REAIS", brl(h.cash_brl), `${pc(h.share_of_target_cash)} of the target · ${usd(h.cash_usd)}`)}
      ${cell("THE TARGET IN DOLLARS", usd(h.target_usd_at_rate), `at the ${fx.mode === "intraday" ? "live" : "last"} rate · ${h.months_remaining} months remaining`)}
      ${cell("HORIZON", `${h.horizon_start} → ${h.horizon_end}`, "three years from 18 September 2026")}
    </div>
    <div class="goal-grid mt2">
      <div><div class="fx-head mono t1 c-3">FX SENSITIVITY · the target's dollar cost and the book's reais value at each rate</div>
        <div class="tbl-scroll"><table class="th-table"><tr><th>USDBRL</th><th class="num">TARGET IN USD</th><th class="num">BOOK IN REAIS</th><th class="num">SHARE OF TARGET</th></tr>${sens}</table></div></div>
      <div><div class="fx-head mono t1 c-3">REQUIRED MONTHLY SAVINGS · on the reais floor of ${brl(h.book_brl)} over ${h.months_remaining} months</div>
        <div class="tbl-scroll"><table class="th-table"><tr><th>ANNUAL RETURN</th><th class="num">PER MONTH</th><th class="num">IN DOLLARS</th></tr>${sav}</table></div></div>
    </div>
    <div class="chart-meta">${h.fx_sensitivity_note || ""} · ${h.savings_basis || ""} · ${h.note || "descriptive; no recommendation"}</div></div>`;
}
function renderClaimsCard(){   // book: D2
  const G = S.goals; const cl = (G && G.claims) || []; const reg = S.claimsReg;
  if (!cl.length && !reg) return "";
  const usd = v => v == null ? "—" : "$" + fmt(Math.round(v));
  const pc = (v, nd = 2) => v == null ? "—" : `<span class="${v >= 0 ? "c-pos" : "c-neg"}">${v >= 0 ? "+" : ""}${(v * 100).toFixed(nd)}%</span>`;
  const cell = (k, v, s, cls) => `<div class="so-cell"><div class="k">${k}</div><div class="v ${cls || "c-1"}">${v}</div><div class="s">${s || ""}</div></div>`;
  const cards = cl.map(c => `<div class="so-strip">
      ${cell("THE CLAIM · " + c.recorded, `${usd(c.start_value_usd)} → ${(c.target_annualized_return * 100).toFixed(0)}% a year for ${c.horizon_years} years`, escText30(c.text))}
      ${cell("SINCE START", pc(c.since_start_return), `${usd(c.nav_usd)} at the ${c.session} close · ${c.sessions_elapsed} sessions (${c.calendar_days_elapsed} days) elapsed`)}
      ${cell("ANNUALIZED EQUIVALENT", `<span class="${c.under_one_year ? "c-warn" : "c-1"}">${c.annualized_equivalent == null ? "—" : ((c.annualized_equivalent >= 0 ? "+" : "") + (c.annualized_equivalent * 100).toFixed(1) + "%")}</span>`, c.under_one_year ? escText30(c.annualized_caption) : "over one year")}
      ${cell("THE 29% PATH", usd(c.target_path_value_now_usd), `today's path value · gap ${c.gap_to_path_usd >= 0 ? "+" : "−"}${usd(Math.abs(c.gap_to_path_usd))} · ${(c.target_path || []).map(p => p.years + "y " + usd(p.value_usd)).join(" · ")}`)}
    </div>`).join("");
  return `<div class="rcc-card claims-card"><h3>CLAIMS REGISTER · <span class="c-3 w5">pre-registered by the operator · the record is never edited · progress computed against it</span>${holdingsPill()}${asOfBadge(G && G.session_date)}</h3>
    ${cards || '<div class="mono t1 c-3">no progress computed yet</div>'}
    <div class="chart-meta">record: data/claims_register.json (${reg ? (reg.claims || []).length : "—"} claim${reg && (reg.claims || []).length === 1 ? "" : "s"}) · ${reg && reg.note ? escText30(reg.note) : ""} · descriptive; no recommendation</div></div>`;
}
function renderRealizedGainsCard(){   // book: D3
  const g = S.gains; if (!g) return "";
  const money = v => v == null ? "—" : `<span class="${v >= 0 ? "c-pos" : "c-neg"}">${v < 0 ? "−" : ""}$${fmt(Math.round(Math.abs(v)))}</span>`;
  const years = Object.keys(g.years || {}).sort().reverse();
  const yrRows = years.map(y => { const r = g.years[y] || {}; return `<tr><td class="mono t2 c-1 w6">${y}${r.year_to_date ? ' <span class="c-3 t1">year to date</span>' : ""}</td><td class="num">${money(r.net)}</td><td class="num">${money(r.short_term)}</td><td class="num">${money(r.long_term)}</td><td class="num c-3">${r.n_lots == null ? "—" : r.n_lots}</td><td class="c-3 t1">${escText30(r.basis || (r.wash_sale_disallowed != null ? "wash-sale disallowed " + money(r.wash_sale_disallowed) : ""))}</td></tr>`; }).join("");
  const posRows = years.flatMap(y => ((g.years[y] || {}).by_position || []).slice(0, 12).map(p => `<tr><td class="mono t2 c-1 w6">${p.ticker}</td><td class="mono t1 c-3">${y}</td><td class="num c-3">${p.n_lots == null ? "—" : p.n_lots}</td><td class="num">${money(p.proceeds)}</td><td class="num">${money(p.cost_basis)}</td><td class="num">${money(p.gain_loss)}</td><td class="num">${money(p.short_term)}</td><td class="num">${money(p.long_term)}</td></tr>`)).join("");
  return `<div class="rcc-card gains-card"><h3>REALIZED GAINS · <span class="c-3 w5">by year and by position, short- and long-term · from the brokerage's realized gain/loss export · descriptive; no tax computation</span>${g.pending_export ? '<span class="mono t1 w6 r1 x2 c-warn ml2">operator report, pending export</span>' : ""}${asOfBadge(g.as_of, {cadence: "static"})}</h3>
    <div class="tbl-scroll"><table class="th-table"><tr><th>YEAR</th><th class="num">NET</th><th class="num">SHORT-TERM</th><th class="num">LONG-TERM</th><th class="num">LOTS</th><th>BASIS</th></tr>${yrRows}</table></div>
    ${posRows ? `<div class="tbl-scroll mt2"><table class="th-table stack-m"><tr><th>POSITION</th><th>YEAR</th><th class="num">LOTS</th><th class="num">PROCEEDS</th><th class="num">COST</th><th class="num">GAIN / LOSS</th><th class="num">SHORT</th><th class="num">LONG</th></tr>${posRows}</table></div>` : '<div class="mono t1 c-3 mt1">per-position detail arrives with the export (drop it in inbox/ and run scripts/ingest_inbox.py)</div>'}
    <div class="chart-meta">source: ${escText30(g.source || "")}${g.input_sha256 ? " · export " + String(g.input_sha256).slice(0, 12) : ""} · ${escText30(g.note || "descriptive; no tax computation")}</div></div>`;
}
function renderInsiderBlock(tk){   // each held name's card: opportunistic purchases in the last 90 days, the cluster flag (E1)
  const I = S.insiders; const n = I && I.names && I.names[tk];
  if (!n) return `<div class="name-block mono t1 c-3">insiders: ${I && I.status ? escText30(typeof I.status === "string" ? I.status : JSON.stringify(I.status)) : "no EDGAR data on record (the ownership job needs the declared contact, SEC_USER_AGENT)"}</div>`;
  const money = v => v == null ? "—" : "$" + fmt(Math.round(v));
  const buys = n.opportunistic_purchases_90d || [];
  const cl = n.cluster || {};
  const rows = buys.map(b => `<tr><td class="mono t1 c-3">${b.date || ""}</td><td class="c-2">${escText30(b.insider)}</td><td class="c-3 t1">${escText30(b.role || "")}</td><td class="num">${b.shares == null ? "—" : fmt(Math.round(b.shares))}</td><td class="num">${money(b.dollars)}</td><td class="mono t1 c-3" title="${escText30(b.classification_basis || "")}">${escText30(b.classification || "")}${b.filing_url ? ` · <a href="${escText30(b.filing_url)}" target="_blank" rel="noopener">Form 4</a>` : ""}</td></tr>`).join("");
  const sales = (n.sales_shown || []).map(s => `<tr class="dim"><td class="mono t1 c-3">${s.date || ""}</td><td class="c-2">${escText30(s.insider)}</td><td class="c-3 t1">${escText30(s.role || "")}</td><td class="num">−${s.shares == null ? "—" : fmt(Math.round(s.shares))}</td><td class="num">${money(s.dollars)}</td><td class="mono t1 c-3" title="${escText30(s.classification_basis || "")}">${escText30(s.classification || "")} · sale</td></tr>`).join("");
  const rex = n.routine_excluded; const rexN = rex == null ? null : (typeof rex === "number" ? rex : rex.purchases);
  const hc = I.history_coverage || {}; const reg = I.signal_registration || {};
  return `<div class="name-block"><div class="mono t1 w6 c-3 ls12 mb1">INSIDERS · OPPORTUNISTIC PURCHASES, LAST 90 DAYS${cl.flag ? ` <span class="c-warn">· CLUSTER: ${cl.n_distinct_buyers_30d} distinct buyers within 30 days (${cl.window_start || ""} → ${cl.window_end || ""})</span>` : ""}</div>
    ${rows || sales ? `<div class="tbl-scroll"><table class="th-table stack-m"><tr><th>DATE</th><th>INSIDER</th><th>ROLE</th><th class="num">SHARES</th><th class="num">DOLLARS</th><th>CLASSIFICATION</th></tr>${rows}${sales}</table></div>` : '<div class="mono t1 c-2">no opportunistic open-market purchase in the last 90 days</div>'}
    <div class="mono t1 c-3 mt1">routine vs opportunistic by the Cohen, Malloy and Pomorski rule (an insider who traded in the same calendar month in each of the prior three years is routine)${rexN != null ? ` · routine purchases excluded: ${rexN}` : ""}${sales ? ` · ${escText30(n.sales_shown_label || "sales are mostly compensation or diversification")}` : ""}${hc.complete === false ? ` · <span class="c-warn">history incomplete (${(hc.quarters_missing || []).length} quarters missing)</span>` : ""} · ${escText30(reg.status || "a candidate return signal registered for the Phase 5 validation on the union universe; it enters no score before it passes")}</div></div>`;
}
function renderOwnershipBlock(tk){   // each held name's card: 13F context only (E2)
  const H = S.holders13f; const n = H && H.names && H.names[tk];
  if (!n) return `<div class="name-block mono t1 c-3">13F context: ${H && H.status ? escText30(typeof H.status === "string" ? H.status : JSON.stringify(H.status)) : "no EDGAR data on record (the ownership job needs the declared contact, SEC_USER_AGENT)"}</div>`;
  const money = v => v == null ? "—" : "$" + fmt(Math.round(v));
  const chg = v => v == null ? "—" : `<span class="${v >= 0 ? "c-pos" : "c-neg"}">${v >= 0 ? "+" : "−"}${fmt(Math.round(Math.abs(v)))}</span>`;
  const nm = h => h.manager || h.name || "";
  const rows = (n.top_holders || []).map(h => `<tr><td class="c-2">${escText30(nm(h))}</td><td class="num">${h.shares == null ? "—" : fmt(Math.round(h.shares))}</td><td class="num">${chg(h.share_change)}</td><td class="num">${money(h.value_usd != null ? h.value_usd : h.value)}</td><td class="mono t1 c-3">as of ${h.as_of_quarter_end || "—"} · disclosed ${h.disclosed || "—"}</td></tr>`).join("");
  const nw = (n.new_positions_over_1b || n.new_positions || []).map(h => `${escText30(nm(h))} (as of ${h.as_of_quarter_end}, disclosed ${h.disclosed})`).join("; ");
  const ex = (n.full_exits_over_1b || n.exits || []).map(h => `${escText30(nm(h))} (as of ${h.as_of_quarter_end}, disclosed ${h.disclosed})`).join("; ");
  return `<div class="name-block"><div class="mono t1 w6 c-3 ls12 mb1">INSTITUTIONAL OWNERSHIP · CONTEXT ONLY</div>
    ${rows ? `<div class="tbl-scroll"><table class="th-table stack-m"><tr><th>HOLDER</th><th class="num">SHARES</th><th class="num">CHANGE ON THE QUARTER</th><th class="num">VALUE</th><th>DATES</th></tr>${rows}</table></div>` : '<div class="mono t1 c-2">no holder on record</div>'}
    <div class="mono t1 c-3 mt1">${escText30(n.caption || "")}${nw ? `<br>new positions among funds above $1 billion: ${nw}` : ""}${ex ? `<br>full exits among funds above $1 billion: ${ex}` : ""} · no signal, no score</div></div>`;
}

// ═══ Tournament Audit and Execution Order (30-Sept-2026): the mistakes ledger (T6), the selection audit
//     (T2/T3), the operator tier's not-comparable row (T3), the continuous twins and their logs (T4), the
//     monthly reviews (T7). Every panel is descriptive. ═══════════════════════════════════════════════
function renderMistakesLedger(){
  const L = Array.isArray(S.mistakes) ? S.mistakes : [];
  if (!L.length) return `<div class="rcc-card"><h3>THE MISTAKES LEDGER</h3><div class="mono t1 c-3">data/mistakes.jsonl has no entries</div></div>`;
  const byId = {}; L.forEach(e => { byId[e.entry_id] = e; });
  const whoCls = w => w === "system" ? "c-neg" : w === "advisor" ? "c-warn" : w === "operator" ? "c-info" : "c-2";
  const kindTag = k => k && k !== "failure" ? `<span class="tier-tag mono t1 w6 c-3">${escText30(k)}</span> ` : "";
  const ordered = L.slice().sort((a, b) => String(b.found || "").localeCompare(String(a.found || "")) || String(b.logged_at || "").localeCompare(String(a.logged_at || "")));
  const newest = ordered.length ? ordered[0].found : null;
  const rows = ordered.map(e => `<tr>
      <td class="mono t1 c-3">${e.found || ""}</td>
      <td class="mono t1 w6 ${whoCls(e.who)}">${escText30(e.who)}</td>
      <td class="serif t1 c-1">${kindTag(e.kind)}${escText30(e.error)}${e.refers_to ? ` <span class="mono t1 c-3">· refers to ${escText30(e.refers_to)}</span>` : ""}${e.stated_reason ? `<div class="mono t1 c-3">stated reason: ${escText30(e.stated_reason)}</div>` : ""}</td>
      <td class="c-2 t1">${escText30(e.detected_by)}</td>
      <td class="c-2 t1">${escText30(e.cost)}${e.horizon ? ` <span class="mono c-3">(+${e.horizon} sessions)</span>` : ""}</td>
      <td class="c-2 t1">${escText30(e.fix)}</td>
      <td class="mono t1 c-3">${escText30(e.referee_check)}</td>
      <td class="mono t1 c-3" title="${escText30(e.entry_sha256)}">${String(e.entry_sha256 || "").slice(0, 8)}</td></tr>`).join("");
  const counts = L.reduce((a, e) => { a[e.who] = (a[e.who] || 0) + 1; return a; }, {});
  return `<div class="rcc-card"><h3>THE MISTAKES LEDGER · <span class="c-3 w5">${L.length} entries · ${Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(" · ")} · newest first</span><span class="asof mono t1 w5 ls06 c-3 ml2">latest entry ${newest || "—"}</span></h3>
    <div class="tbl-scroll"><table class="th-table mistakes-table stack-m"><tr><th>FOUND</th><th>WHO</th><th>WHAT WAS WRONG</th><th>DETECTED BY</th><th>WHAT IT COST</th><th>THE FIX</th><th>REFEREE CHECK</th><th>HASH</th></tr>${rows}</table></div>
    <div class="chart-meta">append-only: no entry is ever edited, a correction is a new entry referencing the old, and the referee raises CRITICAL when an entry no longer matches its hash · operator decisions enter from the brokerage transactions export with the stated reason at the time and, 20 and 60 sessions later, the outcome against not trading · a lesson becomes a rule only through a registration and a prospective test</div></div>`;
}
function renderSelectionAudit(){   // tournament page: what the tournament does (T2), the noise indicator (T3)
  const A = S.tournamentAudit; if (!A) return "";
  const T = ["1_cap_pres", "2_balanced", "3_aggressive", "4_tactical"];
  const short = tid => (tierSpec(tid) || {}).short || tid;
  const pct = (v, nd = 0) => v == null ? "—" : (v * 100).toFixed(nd) + "%";
  const dates = (A.retention[T[0]] || []).map(x => x.date);
  const retRows = T.map(tid => `<tr><td class="mono t1 c-1 w6">${short(tid)}</td>${(A.retention[tid] || []).map(x => `<td class="num ${x.retention < 0.5 ? "c-warn" : "c-2"}">${x.kept}/${x.of}</td>`).join("")}<td class="num c-3">${A.intra_month_trades[tid]}</td></tr>`).join("");
  const sp = A.spells.per_tier;
  const spRows = T.map(tid => { const p = sp[tid]; const w = p.wilson_95 || [];
    return `<tr><td class="mono t1 c-1 w6">${short(tid)}</td><td class="num">${p.n_spells}</td><td class="num c-1">${pct(p.share_beat_spy)}</td><td class="num c-3">[${pct(w[0])}, ${pct(w[1])}]</td><td class="num ${p.mean_excess >= 0 ? "c-pos" : "c-neg"}">${p.mean_excess == null ? "—" : (p.mean_excess >= 0 ? "+" : "") + (p.mean_excess * 100).toFixed(1) + "%"}</td><td class="num c-warn w6">${p.effective_sample_decision_dates}</td><td class="num c-3">${pct(p.store_variant.share_beat_spy)}</td></tr>`; }).join("");
  const g = A.cash_gap; const gapRows = T.map(tid => `<tr><td class="mono t1 c-1 w6">${short(tid)}</td><td class="num">${g[tid].mean_abs_points}</td><td class="num">${g[tid].max_abs_points} <span class="c-3">(${g[tid].max_on})</span></td><td class="num">${g[tid].sessions_over_5_points} of ${g[tid].n_sessions}</td><td class="num">${g[tid]["on_2026-06-03"]}</td></tr>`).join("");
  const r = A.regime_label; const o = A.operator_tier;
  return `<div class="rcc-card"><h3>SELECTION AUDIT · <span class="c-3 w5">monthly batch reconstitution on ${(A.reconstitutions[T[0]] || []).length} dates; zero trades between them; the cash target recomputed daily and executed monthly</span>${asOfBadge(A.session_date)}</h3>
    <div class="goal-grid">
      <div><div class="fx-head mono t1 c-3">NAME RETENTION PER RECONSTITUTION · kept / previous N — the noise indicator</div>
        <div class="tbl-scroll"><table class="th-table"><tr><th>TIER</th>${dates.map(d => `<th class="num">${d.slice(5)}</th>`).join("")}<th class="num">INTRA-MONTH TRADES</th></tr>${retRows}</table></div>
        <div class="mono t1 c-3 mt1">a ranking that replaces most of its top names every month is dominated by noise, consistent with the measured information ratio near zero</div></div>
      <div><div class="fx-head mono t1 c-3">HOLDING SPELLS (${A.spells.n_spells}) · share that beat SPY over the same window</div>
        <div class="tbl-scroll"><table class="th-table"><tr><th>TIER</th><th class="num">SPELLS</th><th class="num">BEAT SPY</th><th class="num">WILSON 95%</th><th class="num">MEAN EXCESS</th><th class="num">DECISION DATES</th><th class="num">STORE VARIANT</th></tr>${spRows}</table></div>
        <div class="mono t1 c-3 mt1">${escText30(A.spells.note)}</div></div>
    </div>
    <div class="goal-grid mt2">
      <div><div class="fx-head mono t1 c-3">CASH GAP · target minus actual, points</div>
        <div class="tbl-scroll"><table class="th-table"><tr><th>TIER</th><th class="num">MEAN |GAP|</th><th class="num">MAX</th><th class="num">SESSIONS > 5</th><th class="num">3 JUNE</th></tr>${gapRows}</table></div></div>
      <div><div class="fx-head mono t1 c-3">LABEL, SHARE CLASSES, THE OPERATOR TIER</div>
        <div class="mono t1 c-2 lh17">regime label changes as published: <strong class="c-1">${r.label_changes_published}</strong> (${Object.entries(r.changes_by_month || {}).map(([k, v]) => k + " " + v).join(", ")}); entries into ELEVATED below the corridor's 0.32: <strong class="c-warn">${(r.entries_below_corridor_0_32 || []).length}</strong> (${(r.entries_below_corridor_0_32 || []).map(f => f.date.slice(5) + " at " + f.R).join(", ")}); the corridor over the same history: ${r.corridor_label_changes_same_history} changes · in force from ${escText30(r.corridor_in_force_from)}</div>
        <div class="mono t1 c-2 lh17 mt1">share classes held together: ${(A.share_classes_held_together || []).length ? A.share_classes_held_together.map(d => `${short(d.tier)} ${d.classes.join(" + ")} (${d.issuer}) ${d.combined_weight_pct}%`).join("; ") + " — collapsed at the next reconstitution" : "none"}</div>
        <div class="mono t1 c-2 lh17 mt1">operator tier: NAV $${fmt(o["nav_2026-09-15"])} on 2026-09-15 → $${fmt(o["nav_2026-09-29"])} on 2026-09-29 (${o["step_2026-09-15_to_29_pct"] != null ? (o["step_2026-09-15_to_29_pct"] >= 0 ? "+" : "") + o["step_2026-09-15_to_29_pct"].toFixed(1) + "%" : "—"}, a re-seed artifact, not a return) · <span class="c-warn">not comparable</span> until rebuilt from the brokerage transactions export</div>
        <div class="mono t1 c-3 mt1">sessions backfilled under the as-published convention: ${(A.backfilled_sessions || []).length}; missing now: ${(A.missing_sessions_now || []).length}</div></div>
    </div>
    <div class="chart-meta">${escText30(A.spells.convention)} · report: reports/tournament_audit_2026-09-30.md · ${escText30(A.note)}</div></div>`;
}
function renderTwinsCard(){   // tournament page: the continuous twins, a live contest (T4)
  const W = S.twins; if (!W || !W.twins) return `<div class="rcc-card"><h3>CONTINUOUS TWINS · LIVE CONTEST</h3><div class="mono t1 c-3">data/tournament/twins.json not published yet (the twins start with their first nightly)</div></div>`;
  const live = S.tournament && S.tournament.history && S.tournament.history.length ? S.tournament.history[S.tournament.history.length - 1] : null;
  const rows = Object.entries(W.twins).map(([id, w]) => { const hist = w.history || w.nav_history || []; const last = hist[hist.length - 1] || w; const first = hist[0] || {};
    const parent = w.parent_tier || w.parent; const pnav = (w.parent_nav_same_session != null) ? w.parent_nav_same_session : (live && parent && live.tiers[parent] ? live.tiers[parent].nav : null);
    const tr = w.trade_counts || w.trades_by_reason || {}; const gap = (last.target_cash_pct != null && last.actual_cash_pct != null) ? (last.target_cash_pct - last.actual_cash_pct) : null;
    return `<tr><td class="mono t2 c-1 w6">${escText30(id)}</td><td class="c-3 t1">${(tierSpec(parent) || {}).short || parent}</td><td class="num">$${fmt(last.nav)}</td><td class="num ${first.nav && last.nav >= first.nav ? "c-pos" : "c-neg"}">${first.nav ? ((last.nav / first.nav - 1) * 100).toFixed(2) + "%" : "—"}</td><td class="num c-3">${pnav ? "$" + fmt(pnav) : "—"}</td><td class="num">${last.n_positions != null ? last.n_positions : "—"}</td><td class="num ${gap != null && Math.abs(gap) > 5 ? "c-warn" : "c-2"}">${last.actual_cash_pct != null ? last.actual_cash_pct.toFixed(1) + "% vs " + last.target_cash_pct.toFixed(1) + "%" : "—"}</td><td class="mono t1 c-3">${Object.entries(tr).map(([k, v]) => k + " " + v).join(" · ") || "—"}</td></tr>`; }).join("");
  return `<div class="rcc-card"><h3>CONTINUOUS TWINS · LIVE CONTEST · <span class="c-3 w5">1c–4c: the same universe, scores, targets and costs as tiers 1–4, differing only in execution — evaluated daily, traded on bands (rank buffer, regime cash beyond 5 points, weight drift beyond 25 percent of target) · the monthly tiers stay as controls</span>${asOfBadge(W.session_date)}</h3>
    <div class="tbl-scroll"><table class="th-table stack-m"><tr><th>TWIN</th><th>PARENT</th><th class="num">NAV</th><th class="num">SINCE START</th><th class="num">PARENT NAV</th><th class="num">N</th><th class="num">CASH ACTUAL vs TARGET</th><th>TRADES BY REASON</th></tr>${rows}</table></div>
    <div class="chart-meta">started ${escText30(W.start_date || "")} with the same capital · rules: data/tournament/continuous_rules.json · trades and spells: data/tournament/trades.jsonl, spells.jsonl (per tier, newest first, in each tier's detail) · replacement of the monthly tiers only after the registered C6 comparison${S.c6Power ? " · power check: " + escText30(S.c6Power.verdict) : ""}</div></div>`;
}
function renderTierLogs(tid){   // in a tier's detail: its trades and spells, newest first (T4)
  const T = Array.isArray(S.trades) ? S.trades.filter(t => t.tier === tid) : [];
  const SP = Array.isArray(S.spells) ? S.spells.filter(s => s.tier === tid) : [];
  if (!T.length && !SP.length) return "";
  const money = v => v == null ? "—" : "$" + fmt(Math.round(v));
  const tRows = T.slice().sort((a, b) => String(b.session).localeCompare(String(a.session)) || String(b.trade_id).localeCompare(String(a.trade_id))).slice(0, 40).map(t => `<tr><td class="mono t1 c-3">${t.session}</td><td class="mono t1 c-1 w6">${escText30(t.ticker)}</td><td class="${t.action === "buy" ? "c-pos" : "c-neg"}">${t.action}</td><td class="num">${t.shares == null ? "—" : (+t.shares).toFixed(2)}</td><td class="num">${t.price == null ? "—" : "$" + (+t.price).toFixed(2)}</td><td class="num">${money(t.value)}</td><td class="num c-3">${t.cost == null ? "—" : "$" + (+t.cost).toFixed(2)}</td><td class="mono t1 c-2">${escText30(t.reason)}</td><td class="num c-3">${t.tier_rank != null ? "#" + t.tier_rank : "—"}${t.tier_composite != null ? " · " + (+t.tier_composite).toFixed(1) : ""}</td><td class="num c-3">${t.bq_score != null ? (+t.bq_score).toFixed(1) : "—"} / ${t.tn_score != null ? (+t.tn_score).toFixed(0) : "—"}</td><td class="mono t1 c-3">${t.regime_label || ""}${t.regime_R != null ? " " + (+t.regime_R).toFixed(2) : ""}</td></tr>`).join("");
  // spells: the latest event per spell id
  const latest = {}; SP.forEach(s => { const k = s.spell_id; if (!latest[k] || String(s.logged_at) >= String(latest[k].logged_at)) latest[k] = Object.assign({}, latest[k] || {}, s); });
  const fu = {}; SP.forEach(s => { if (s.event === "followup_20" || s.event === "followup_60") (fu[s.spell_id] = fu[s.spell_id] || {})[s.horizon] = s; });
  const pct = v => v == null ? "—" : `<span class="${v >= 0 ? "c-pos" : "c-neg"}">${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%</span>`;
  const sRows = Object.values(latest).sort((a, b) => String(b.exit_session || b.entry_session).localeCompare(String(a.exit_session || a.entry_session))).slice(0, 40).map(s => { const f = fu[s.spell_id] || {};
    return `<tr><td class="mono t1 c-1 w6">${escText30(s.ticker)}</td><td class="mono t1 c-3">${s.entry_session}</td><td class="mono t1 c-3">${s.exit_session || '<span class="c-warn">open</span>'}</td><td class="mono t1 c-2">${escText30(s.exit_reason || "")}</td><td class="num">${pct(s.return)}</td><td class="num">${pct(s.excess_vs_spy)}</td><td class="num">${pct(s.excess_vs_basket)}<span class="c-3 t1"> ${escText30(s.basket_thesis || "")}</span></td><td class="num">${f[20] ? pct(f[20].excess_vs_spy) : "—"}</td><td class="num">${f[60] ? pct(f[60].excess_vs_spy) : "—"}</td><td class="num c-3">${s.scores_at_entry && s.scores_at_entry.tier_rank != null ? "#" + s.scores_at_entry.tier_rank : "—"}</td></tr>`; }).join("");
  return `<div class="mt3"><div class="mono t1 w6 c-3 ls12 mb1">TRADES · newest first (${T.length})</div>
    ${tRows ? `<div class="tbl-scroll"><table class="th-table stack-m"><tr><th>SESSION</th><th>NAME</th><th>ACTION</th><th class="num">SHARES</th><th class="num">PRICE</th><th class="num">VALUE</th><th class="num">COST</th><th>REASON</th><th class="num">TIER RANK · SCORE</th><th class="num">BQ / TRADE-NOW</th><th>REGIME</th></tr>${tRows}</table></div>` : '<div class="mono t1 c-3">no trade logged</div>'}
    <div class="mono t1 w6 c-3 ls12 mb1 mt2">SPELLS · newest first (${Object.keys(latest).length})</div>
    ${sRows ? `<div class="tbl-scroll"><table class="th-table stack-m"><tr><th>NAME</th><th>ENTRY</th><th>EXIT</th><th>EXIT REASON</th><th class="num">RETURN</th><th class="num">vs SPY</th><th class="num">vs THESIS BASKET</th><th class="num">+20 vs SPY</th><th class="num">+60 vs SPY</th><th class="num">RANK AT ENTRY</th></tr>${sRows}</table></div>` : '<div class="mono t1 c-3">no spell logged</div>'}</div>`;
}
function renderReviewsCard(){   // system page: the monthly reviews (T7), generated and never edited
  const R = Array.isArray(S.reviews) ? S.reviews : []; if (!R.length) return "";
  const rows = R.slice().reverse().map(r => `<tr><td class="mono t1 c-1 w6">${escText30(r.month)}</td><td class="c-2 t1"><a href="${escText30(r.file)}" target="_blank" rel="noopener">${escText30(r.file)}</a></td><td class="mono t1 c-3">${String(r.generated_at || "").slice(0, 16)}</td><td class="mono t1 c-3">${r.effective_samples ? escText30(JSON.stringify(r.effective_samples)) : ""}</td><td class="mono t1 c-3" title="${escText30(r.sha256)}">${String(r.sha256 || "").slice(0, 8)}</td></tr>`).join("");
  return `<div class="rcc-card"><h3>MONTHLY REVIEWS · <span class="c-3 w5">generated from the ledgers each month, stored, never edited · findings stated with the effective sample size (decision dates, not spells) and a date-block bootstrap interval · a lesson becomes a rule only through a registration and a prospective test</span>${asOfBadge(R[R.length - 1].generated_at, {cadence: "monthly"})}</h3>
    <div class="tbl-scroll"><table class="th-table stack-m"><tr><th>MONTH</th><th>REPORT</th><th>GENERATED</th><th>EFFECTIVE SAMPLES</th><th>HASH</th></tr>${rows}</table></div></div>`;
}
