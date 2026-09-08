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
function statusLabel(s){ return ({safe:"Safe",neutral:"Neutral",elevated:"Caution",crisis:"Crisis"})[s] || s; }

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
         + (S.expandedIndicator ? renderIndicatorDetail() : "");
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
  }).join("");
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
function formatIndicatorValue(key, val, fallbackStr){
  if (val == null) return fallbackStr || "—";
  // Match the precision of the EOD value_str roughly per indicator family.
  if (key === "skew" || key === "mfg_new_orders") return val.toFixed(0);
  if (key === "vvix" || key === "vix") return val.toFixed(2);
  if (key === "dxy") return val.toFixed(1);
  if (key === "vix_term") return val.toFixed(2);
  return (typeof val === "number") ? val.toFixed(2) : String(val);
}

function renderIndCard(i){
  const c = statusHex(i.status);
  const open = (S.expandedIndicator === i.key);
  const intradayVal = intradayValueFor(i.key);
  const displayedStr = intradayVal != null
    ? formatIndicatorValue(i.key, intradayVal, i.value_str)
    : (i.value_str || "—");
  const liveBadge = intradayVal != null
    ? ` <span title="Intraday snapshot" class="mono t1 w6 c-accent ls1 x1">·LIVE</span>`
    : "";
  return `<div class="ind-card ${i.status} ${open?"expanded":""}" data-ind="${i.key}">
    <div class="ind-lbl ${i.status}">${i.label}${liveBadge}</div>
    <div class="ind-val">${displayedStr}</div>
    <div class="ind-narr">${i.narrative || ""}</div>
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
    else interp = `Crisis-level reading. Z-score ${z} (${pct}th percentile). Strong contribution to risk score.`;
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
    DEPLOY:    "Full sizing; new entries OK; sell out-of-the-money premium.",
    CAUTIOUS:  "Reduce new entries to 75%; favour limit orders at lower levels.",
    DEFENSIVE: "Trim concentrated holdings; activate put spreads; raise cash to tier maximum.",
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
function _etDateISO(d){ return new Date(d.getTime() - 4*3600e3).toISOString().slice(0,10); }
function lastTradingSessionISO(){
  const now = new Date();
  const et = new Date(now.getTime() - 4*3600e3);
  let d = new Date(Date.UTC(et.getUTCFullYear(), et.getUTCMonth(), et.getUTCDate()));
  // Before the 16:00 ET close, today's session data can't exist yet.
  if (et.getUTCHours() < 16) d.setUTCDate(d.getUTCDate() - 1);
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
  while ([0,6].includes(d.getUTCDay()) || NYSE_HOLIDAYS.has(d.toISOString().slice(0,10)))
    d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0,10);
}
function isStaleAsOf(dateStr){
  if (!dateStr) return true;
  return String(dateStr).slice(0,10) < lastTradingSessionISO();
}
// Small chip rendered next to panel titles: grey when fresh, amber when stale.
function asOfBadge(dateStr){
  const d = dateStr ? String(dateStr).slice(0,10) : "—";
  if (isStaleAsOf(d)) {
    return `<span class="mono t1 w6 ls08 r1 c-warn ml2 x2">
      STALE · as of ${d}</span>`;
  }
  return `<span class="mono t1 w5 ls06 c-3 ml2">as of ${d}</span>`;
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
  if (a.critical && a.critical.length)
    parts.push(strip("neg",
      `✗ audit CRITICAL — ${a.critical.join(", ")} · served artifacts are the last good board (session ${st.session_date || "?"})`));
  else if (st.failure_reason)
    parts.push(strip("warn",
      `⚠ last run rejected: ${st.failure_reason} · served artifacts are the last good board (session ${st.session_date || "?"}; last success ${String(st.last_success || "").slice(0,16)})`));
  if (a.high && a.high.length)
    parts.push(strip("2",
      `audit: ${a.high.length} HIGH — ${a.high.join(", ")} <span class="c-3">(logged, non-blocking · ${String(a.ran_at || "").slice(0,16)})</span>`));
  // B3: cross-file findings are reported in both repositories' strips and block neither;
  // the other repository's CRITICALs are shown but never block this deploy.
  if (a.xfile && a.xfile.length)
    parts.push(strip("2",
      `cross-file: ${a.xfile.join(", ")} <span class="c-3">(reported in both repositories; blocks neither)</span>`));
  if (a.critical_other_repo && a.critical_other_repo.length)
    parts.push(strip("2",
      `other repository CRITICAL: ${a.critical_other_repo.join(", ")} <span class="c-3">(does not block this deploy)</span>`));
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
        The end-of-day regime below is <strong>STALE</strong> and does not reflect this move.
        Do not deploy new capital until the close.
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
  if (holes.length) parts.push(`${nNames} names unclassified across ${holes.length} tier${holes.length > 1 ? "s" : ""} (${holes.map(([tid, t]) => `${(tierSpec(tid)||{}).short || tid} ${(t.unclassified_share*100).toFixed(0)}%`).join(" · ")})`);
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
    "DEPLOY":     "Full sizing; new entries OK; sell out-of-the-money premium.",
    "CAUTIOUS":   "Trim sizing to 75%; require quality screens; tighten stops.",
    "DEFENSIVE":  "Trim sizing to 50%; raise cash; no new positions in cyclicals.",
    "CRISIS":     "Defensive: max cash, exit weak positions, hedge remaining longs.",
    "INTRADAY STRESS": "Do not deploy new capital until the close. Hedge or wait.",
    "COMPLACENT": "Cheap protection available; consider buying VIX/puts before re-deploying.",
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
    inputs.n_crisis > 0 ? `${inputs.n_crisis} crisis ch.` : null,
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
    <span class="c-neg">${cri} crisis</span></span>`;

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
  if (S.startsWith("SELL"))            return {cls:"exit",   color:"#f87171", icon:"▼",
                                                text:"Exit signal — stop or thesis triggered."};
  if (S.startsWith("TRIM"))            return {cls:"trim",   color:"#facc15", icon:"✂",
                                                text:"Trim signal — profit-take threshold crossed."};
  if (S.includes("HEDGE"))             return {cls:"hedge",  color:"#a78bfa", icon:"🛡",
                                                text:"Hedge signal — extended position, sell covered calls."};
  if (S.includes("MONITOR"))           return {cls:"monitor",color:"#94a3b8", icon:"—",
                                                text:"Monitor — multiple yellow flags but no exit."};
  if (S.startsWith("HOLD"))            return {cls:"hold",   color:"#737373", icon:"—",
                                                text:"Hold — no action."};
  if (S.startsWith("WAIT") || S.startsWith("WATCH"))
                                       return {cls:"wait",   color:"#facc15", icon:"⏸",
                                                text:"Wait for entry — not at the price the model wants."};
  // BUY / STRONG BUY → 4-quadrant divergence
  const hiQ = quality >= 38;
  const hiT = trade >= 70;
  if ( hiQ &&  hiT) return {cls:"clean", color:"#4ade80", icon:"★",
                            text:"Clean buy — top-tier business at a good entry."};
  if ( hiQ && !hiT) return {cls:"watch", color:"#facc15", icon:"⚠",
                            text:"Quality name, but NOT a good entry now — pullback watch-list."};
  if (!hiQ &&  hiT) return {cls:"momo",  color:"#60a5fa", icon:"↗",
                            text:"Decent entry on a middling business — momentum trade, lower conviction."};
  return                    {cls:"avoid", color:"#737373", icon:"·",
                            text:"Neither quality nor timing — pass."};
}
function tradeContext(s){
  // One short phrase that summarises the trade-now reading using existing data.
  if (!s) return "";
  if (s.mode === "position"){
    const p = s.position || {};
    if (s.signal && s.signal.startsWith("SELL")) return `stop triggered · ${p.gain_pct >= 0 ? "+" : ""}${p.gain_pct?.toFixed?.(0) || "?"}%`;
    if (s.signal && s.signal.startsWith("TRIM")) return `${p.gain_pct?.toFixed?.(0) || "?"}% gain · trim trigger`;
    if (s.signal && s.signal.includes("HEDGE")) return `+${p.gain_pct?.toFixed?.(0) || "?"}% · extended · ${s.hedge?.strike ? "sell $" + s.hedge.strike + " calls" : "hedge"}`;
    return `${p.gain_pct >= 0 ? "+" : ""}${p.gain_pct?.toFixed?.(0) || "?"}% gain · trail $${s.stops?.active_stop ?? "?"}`;
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
  const trade   = s.trade_now_strength != null ? +s.trade_now_strength : +s.signal_strength;
  const sig     = s.signal || "—";
  const note    = s.trade_now_note;
  const div     = divergenceState(quality, qPct, trade, sig);

  return `<div class="two-score">
    <div class="ts-row">
      <div class="ts-label">Business quality</div>
      ${twoScoreBar(quality, 50, qualityColor(quality))}
      <div class="ts-val">${quality.toFixed(1)}<span class="ts-of">/50</span></div>
      <div class="ts-sub">${qPct.toFixed(0)}th pct${rank === 1 ? " · #1 in universe" : rank ? " · rank #" + rank : ""}</div>
    </div>
    <div class="ts-row">
      <div class="ts-label">Trade now</div>
      ${twoScoreBar(trade, 100, tradeColor(trade))}
      <div class="ts-val"><span class="${cc(tradeColor(trade))}">${sig}</span> · ${trade}<span class="ts-of">/100</span></div>
      <div class="ts-sub">${note ? '<span class="c-warn">' + note + '</span>' : tradeContext(s)}</div>
    </div>
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
    <div class="event-today-cap">Regime read is conditional; vol moves expected; do not deploy fresh capital pre-print.</div>
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
function thesisColor(k){ return THESIS_COLORS[k] || "var(--cat8)"; }
function thesisLabel(k){
  const reg = S.thesisReg && S.thesisReg.theses;
  if (k === "unclassified") return "unclassified";
  if (k === "cash") return "cash";
  return (reg && reg[k] && reg[k].label) || k;
}

function renderThesisSection(){
  const td = S.thesis;
  if (!td) return "";
  const frozen = td.registry_frozen;
  const view = S.thesisView || "invested";
  const tab  = S.thesisTab || "live";
  const expKey = view === "total" ? "exposure_total" : "exposure_invested";

  // ---- B1: exposure stacked bars + N_eff + overlap ----
  const tierRows = Object.entries(td.tiers || {}).map(([tid, t]) => {
    const exp = t[expKey] || {};
    const segs = Object.entries(exp).map(([k, w]) =>
      `<div class="${cc(thesisColor(k),'bg')}" style="width:${(w*100).toFixed(1)}%"
        title="${thesisLabel(k)}: ${(w*100).toFixed(1)}%"></div>`).join("");
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
    const k = ks[c.thesis_id] || {};
    const status = k.met
      ? `<span class="cl-status c-neg">KILL CRITERIA MET ON ${k.date}</span>`
      : `<span class="cl-status c-pos">no kill criteria met</span>`;
    const log = (c.log || []).slice(-6).reverse().map(l =>
      l.type === "auto"
        ? `<div>${l.date} · ${l.event} · basket 1d ${(l.basket_ret_1d*100).toFixed(2)}%</div>`
        : `<div class="an">${l.date} · analyst entry · ${l.note || ""}${l.kill ? " · KILL" : ""}</div>`
    ).join("");
    return `<div class="th-claim">
      <div class="cl-head">
        <span class="cl-name ${cc(thesisColor(c.thesis_id))}">${thesisLabel(c.thesis_id)}</span>
        ${status}
      </div>
      <div class="cl-text">${c.claim}</div>
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

  const liveBody = `
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
    <div class="th-block">
      <h4>B3 · THESIS REGISTER — claims · kill criteria · log (auto = mechanical event-day entries; analyst = Werner)</h4>
      ${claimCards}
    </div>
    <div class="th-block">
      <h4>B4 · ATTRIBUTION — cash | allocation | selection (sums to active vs SPY; residual-defined)</h4>
      ${attrBlocks}
      <div class="th-caveat">${td.small_n_caveat} Components are arithmetic sums of daily effects; no CIs fabricated on ${td.sessions_since_inception} points.</div>
      <div class="th-caveat">"Selection" is measured against equal-weight thesis baskets; with coarse
        buckets, within-thesis composition (e.g. memory-semis vs megacap-AI) appears as selection.
        Finer sub-theses would reclassify part of it as allocation — a memory_semis sub-thesis
        proposal is in registry_proposals.json to demonstrate this bucket-dependence live.</div>
    </div>`;

  const btBody = `
    <div class="th-block">
      <h4>B5 · BACKTEST ATTRIBUTION — full walk-forward, ${(bt.tiers && Object.values(bt.tiers)[0] || {}).n_periods || "—"} monthly periods</h4>
      <table class="th-table">
        <tr><th>TIER</th><th>PERIODS</th><th>CUM ACTIVE</th><th>CASH</th><th>ALLOCATION</th><th>SELECTION</th><th class="tal">AVG TOP EXPOSURES</th></tr>
        ${btRows}
      </table>
      ${btCaveats}
    </div>`;

  return `<section class="thesis">
    <div class="thesis-head">
      <div>
        <h2>THESIS — EXPOSURE · FALSIFICATION · ATTRIBUTION${asOfBadge(td.session_date || td.as_of)}${!frozen ? '<span class="th-pending">REGISTRY v' + td.registry_version + ' PENDING APPROVAL</span>' : '<span class="mono t1 w5 c-3 ml2">registry v' + td.registry_version + ' frozen ' + (td.registry_frozen_at||"") + '</span>'}</h2>
        <div class="sub">the meso level: cross-sectional structure of the bets — risk accounting, not a return forecaster</div>
      </div>
      <span class="th-toggle">
        <button class="${tab==='live' ? 'on' : ''}" data-thesis-tab="live">LIVE</button>
        <button class="${tab==='backtest' ? 'on' : ''}" data-thesis-tab="backtest">BACKTEST</button>
      </span>
    </div>
    ${tab === "live" ? liveBody : btBody}
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
    const trade   = s.trade_now_strength != null ? +s.trade_now_strength : +s.signal_strength;
    const sig     = s.signal || "—";
    const div     = divergenceState(quality, qPct, trade, sig);
    // quad order: actionable buys + exits at the top, holds at the bottom
    const quadOrder = ({clean:9, exit:8, trim:7, watch:6, momo:5, hedge:4,
                        wait:3, monitor:2, hold:1, avoid:0})[div.cls] ?? 0;
    rows.push({tk, quality, qPct, rank, trade, sig, divCls:div.cls,
               divColor:div.color, divIcon:div.icon, quadOrder,
               mode:s.mode, note:s.trade_now_note});
  }
  return rows;
}
function scannerFilterFn(filter){
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
  if (sortKey === "trade")   return (a,b) => mult * (a.trade   - b.trade);
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
    {k:"clean",     lbl:`★ Clean buys (${rows0.filter(r=>r.divCls==="clean").length})`},
    {k:"watch",     lbl:`⚠ Pullback watch (${rows0.filter(r=>r.divCls==="watch").length})`},
    {k:"exit",      lbl:`▼ Exit signals (${rows0.filter(r=>r.divCls==="exit"||r.divCls==="trim").length})`},
    {k:"quality",   lbl:`Top quality (${rows0.filter(r=>r.quality>=38).length})`},
    {k:"positions", lbl:`Owned (${rows0.filter(r=>r.mode==="position").length})`},
  ];

  const tradeColorFor = t => tradeColor(t);
  const qColorFor     = q => qualityColor(q);

  let body = "";
  for (const r of rows){
    const qPct = Math.max(0, Math.min(100, r.quality / 50 * 100));
    const tPct = Math.max(0, Math.min(100, r.trade));
    body += `<tr class="row" data-scanner-tk="${r.tk}">
      <td class="tk">${r.tk}</td>
      <td class="bar-cell">
        <div class="minibar-wrap">
          <div class="minibar"><div class="minibar-fill ${cc(qColorFor(r.quality),'bg')}" style="width:${qPct.toFixed(0)}%"></div></div>
        </div>
      </td>
      <td class="val">${r.quality.toFixed(1)}<small class="c-3">/50</small>${r.rank===1 ? ' <span class="x25">#1</span>' : r.rank<=10 ? ` <span class="c-3">#${r.rank}</span>` : ''}</td>
      <td class="bar-cell">
        <div class="minibar-wrap">
          <div class="minibar"><div class="minibar-fill ${cc(tradeColorFor(r.trade),'bg')}" style="width:${tPct.toFixed(0)}%"></div></div>
        </div>
      </td>
      <td class="val"><span class="${cc(tradeColorFor(r.trade))}">${r.sig.length > 18 ? r.sig.substring(0,16) + "…" : r.sig}</span> · ${r.trade}</td>
      <td class="flag ${cc(r.divColor)}">${r.divIcon} ${r.divCls}</td>
    </tr>`;
  }

  return `<section class="scanner">
    <div class="scanner-head">
      <div>
        <h2>SCANNER — BUSINESS QUALITY × TRADE NOW${asOfBadge(S.signals && S.signals.updated)}</h2>
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
        <th class="${sortCls("trade")}"   data-scsort="trade">TRADE NOW</th>
        <th class="num"></th>
        <th class="${sortCls("quad")}"    data-scsort="quad">FLAG</th>
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
  if (sig.mode === "position") return renderPositionBox(sig);
  return renderEntryBox(sig);
}

function renderEntryBox(sig){
  const baseSig = sigVerb(sig.signal);
  const sc = SIG_COLORS[baseSig] || SIG_COLORS["HOLD"];
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
        <span class="mono t1 w5 c-3 ml2">${sig.category} · strength ${sig.signal_strength}/100</span>
      </div>
      <div class="mono t1 w5 c-3">
        R/R <strong class="${cc(rrc)}">${rr}:1</strong>
        <span class="ib wd2 ht2 r-round ${cc(rrc,'bg')} ml1 va-m"></span>
      </div>
    </div>

    <div class="gap2 mb3 x29">
      ${cell("ENTRY",
        `<div class="mono t3 w7 c-info">$${(sig.entry?.primary ?? 0).toFixed(2)}</div>`,
        `${sig.entry?.basis || ""}<br>2nd: $${(sig.entry?.secondary ?? 0).toFixed(2)}`)}
      ${cell("STOP",
        `<div class="mono t3 w7 c-neg">$${(sig.stop?.price ?? 0).toFixed(2)}</div>`,
        sig.stop?.category_rule || "")}
      ${cell("TARGET",
        `<div class="mono t3 w7 c-pos">$${(sig.target?.base ?? 0).toFixed(2)}</div>`,
        `Cons: $${(sig.target?.conservative ?? 0).toFixed(2)}<br>Aggr: $${(sig.target?.aggressive ?? 0).toFixed(2)}`)}
      ${cell("SIZE",
        `<div class="mono t3 w7 c-1">${fmtMoney(sig.size?.dollars)}</div>`,
        `${sig.size?.shares ?? 0} shares · ${sig.size?.pct_portfolio ?? 0}%<br>Max loss: ${fmtMoney(sig.size?.max_loss)}`)}
    </div>

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
        <div><span class="c-3 w7">BUY:</span> ${condList(sig.conditions?.buy)}</div>
        <div><span class="c-3 w7">STRONG:</span> ${condList(sig.conditions?.strong_buy)}</div>
        <div><span class="c-3 w7">SELL:</span> ${condList(sig.conditions?.sell)}</div>
      </div>
    </details>
  </div>`;
}

// -------- Position-mode signal box (owned stocks) --------
function renderPositionBox(sig){
  const p = sig.position, s = sig.stops;
  const baseSig = sigVerb(sig.signal);
  const sc = SIG_COLORS[baseSig] || SIG_COLORS["HOLD"];
  const gainColor = p.gain_pct >= 0 ? "#4ade80" : "#f87171";

  // Thesis dots
  const thesisRows = (sig.thesis || []).map(t => {
    const color = t.status === "green" ? "#4ade80" : t.status === "yellow" ? "#facc15" : "#f87171";
    const icon  = t.status === "green" ? "✓"      : t.status === "yellow" ? "⚠"      : "✗";
    return `<div class="serif t1 ${cc(color)} lh17">${icon} ${t.text}</div>`;
  }).join("");

  // Hedge callout
  const hedgeHtml = sig.hedge ? `
    <div class="mt3 r2 x31">
      <div class="mono t1 w6 c-info ls12 mb1">ACTION</div>
      <div class="serif t1 lh155 x32">${sig.hedge.text}</div>
    </div>` : "";

  // Trim status line
  const trimHtml = sig.trim ? `
    <div class="mono t1 c-3 mt2">
      Next trim: <strong class="c-2">${sig.trim.trim_pct}%</strong> at ${sig.trim.at_gain}
      ($${sig.trim.trigger_price} · ${sig.trim.distance >= 0 ? "+" : ""}${sig.trim.distance}% from here)
    </div>` : `
    <div class="mono t1 c-3 mt2">No upcoming trim trigger</div>`;

  const cell = (label, big, sub, color="var(--t1)") => `
    <div>
      <div class="mono t1 w6 c-3 ls16 mb1">${label}</div>
      <div class="mono t3 w7 ${cc(color)}">${big}</div>
      ${sub ? `<div class="mono t1 c-3 mt1">${sub}</div>` : ""}
    </div>`;

  return `<div class="sig-card ${sc.cls} r2 mb3 x26">
    <div class="flx mb3 gap3 x27">
      <div>
        <span class="sig-badge mono t1 w8 ls15 ${sc.cls} r1 x28">${sc.icon} ${sig.signal}</span>
        <span class="mono t1 w5 c-3 ml2">${sig.category} · ${p.weight_pct}% of portfolio</span>
      </div>
      <div class="mono t1 w5 c-3">POSITION MODE</div>
    </div>

    <div class="gap2 mb2 x29">
      ${cell("COST",    "$" + p.cost_basis.toFixed(2),    `${p.shares} shares`, "var(--t2)")}
      ${cell("CURRENT", "$" + p.current_price.toFixed(2), fmtMoney(p.position_value), "var(--t1)")}
      ${cell("GAIN",    (p.gain_pct >= 0 ? "+" : "") + p.gain_pct.toFixed(1) + "%",
                       (p.gain_dollars >= 0 ? "+" : "") + fmtMoney(p.gain_dollars), gainColor)}
      ${cell("ACTIVE STOP", "$" + s.active_stop.toFixed(2),
                            `${s.active_stop_type} · -${s.trail_pct}% from $${p.peak_price.toFixed(0)} peak`,
                            "#f87171")}
    </div>

    ${trimHtml}
    ${hedgeHtml}

    <div class="mt3">
      <div class="mono t1 w6 c-3 ls12 mb2">THESIS CHECK</div>
      ${thesisRows}
    </div>

    <div class="mt3">
      <span class="mono t1 w6 c-3 ls16">POSITION MANAGEMENT</span>
      <p class="c-2 lh16 mt1 x30">${sig.why || ""}</p>
    </div>

    <details class="mt2">
      <summary class="mono t1 w5 c-3 ptr ls05">Stop details</summary>
      <div class="mt2 mono t1 c-3 lh17">
        Trailing stop: $${s.trail_stop.toFixed(2)} (-${s.trail_pct}% from $${p.peak_price.toFixed(0)} peak, bracket ${s.trail_bracket}) ·
        Hard stop: $${s.hard_stop.toFixed(2)} (-${s.hard_stop_pct}% from cost) ·
        Active = higher of the two = <strong class="c-neg">$${s.active_stop.toFixed(2)}</strong>
      </div>
    </details>
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
  const fundCard = (label, val, unit="") => {
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
          ${fundCard("FWD P/E",   F.fwd_pe)}
          ${fundCard("TRAIL P/E", F.trail_pe)}
          ${fundCard("P/B",       F.pb)}
          ${fundCard("P/S",       F.ps)}
          ${fundCard("EV/EBITDA", F.ev_ebitda)}
          ${fundCard("PEG",       F.peg)}
          ${fundCard("REV GROWTH", F.rev_growth, "%")}
          ${fundCard("GROSS MGN",  F.gross_mgn, "%")}
          ${fundCard("OP MGN",     F.op_mgn, "%")}
          ${fundCard("ROE",        F.roe, "%")}
          ${fundCard("FCF",        F.fcf_B ? "$" + F.fcf_B + "B" : null)}
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
    "full":           "Buy SPY put spreads when R<sub>t</sub> > 0.6 (50% notional, 0.5%/q budget). Standing VIX call tail hedge.",
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
    <th>TICKER</th><th>SECTOR</th><th class="num">PRICE</th><th class="num">VALUE</th>
    ${tid==="5_werner" ? '<th class="num">COST</th><th class="num">GAIN</th>' : ''}
    <th class="num">WEIGHT</th><th></th>
  </tr>`;
  positions.forEach(p => {
    const sector = S.tickers && S.tickers[p.ticker] ? S.tickers[p.ticker].sector : "";
    const dim = (p.shares === 0 || p.value == null && tid==="5_werner");
    const open = (S.expandedTicker === p.ticker);
    h += `<tr class="tk-row ${open?"open":""}" data-tk="${p.ticker}"${dim ? ' class="dim"' : ''}>
      <td><strong class="c-1">${p.ticker}</strong></td>
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
      h += `<tr><td colspan="${tid==="5_werner"?8:6}" class="p0 x36">${renderTickerDetail(p.ticker)}</td></tr>`;
    }
  });
  h += `</table>`;
  if (S.holdings && S.holdings.turnover && S.holdings.turnover[tid] != null && tid !== "5_werner") {
    h += `<div class="mono t1 c-3 mt2 tar">
      monthly turnover (last rebalance): <strong class="c-2">${(S.holdings.turnover[tid]*100).toFixed(0)}%</strong>
    </div>`;
  }
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
function renderDrawdownCard(){      // P2.1: underwater chart, tier one
  const r = S.ddRange || "ALL";
  const btn = (p, t) => `<button class="period-btn ${r === p ? "on" : ""}" data-ddr="${p}">${t}</button>`;
  return `<div class="rcc-card dd-card">
    <div class="chart-head"><h3>DRAWDOWN FROM RUNNING PEAK · <span class="c-3 w5">all tiers and benchmarks, one axis</span></h3>
      <div class="periods">${btn("1M","1M")}${btn("3M","3M")}${btn("ALL","SINCE INCEPTION")}${btn("BT","BACKTEST")}</div></div>
    ${renderClaimSentence()}
    <div class="chart-wrap dd-wrap"><canvas id="dd-chart"></canvas></div>
    <div class="chart-meta" id="dd-meta"></div>
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
    let best = null, bw = 0, multi = 0;
    Object.entries(reg).forEach(([k, th]) => { const mw = th.members && th.members[p.ticker]; if (mw) { multi++; if (mw > bw) { bw = mw; best = k; } } });
    let provisional = false;
    if (!best && provNames.has(p.ticker) && ledger[p.ticker] && ledger[p.ticker].proposed) {
      const [k, mw] = Object.entries(ledger[p.ticker].proposed).sort((a, b) => b[1] - a[1])[0]; best = k; bw = mw; provisional = true;
    }
    const key = best || "unclassified";
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
  const W = 1000, H = 440, LBL = 16;
  const gitems = Object.entries(d.groups).map(([k, arr]) => ({key: k, area: arr.reduce((s, p) => s + p.w, 0)}));
  if (d.cashW > 0) gitems.push({key: "cash", area: d.cashW});
  const grects = squarify(gitems, 0, 0, W, H);
  let svg = "";
  grects.forEach(g => {
    const label = thesisLabel(g.key);
    svg += `<rect class="tm-group" x="${g.x.toFixed(1)}" y="${g.y.toFixed(1)}" width="${g.w.toFixed(1)}" height="${g.h.toFixed(1)}"></rect>`;
    if (g.key === "cash") {
      svg += `<rect class="tm-rect cash" x="${(g.x + 2).toFixed(1)}" y="${(g.y + 2).toFixed(1)}" width="${Math.max(0, g.w - 4).toFixed(1)}" height="${Math.max(0, g.h - 4).toFixed(1)}"><title>cash · ${(d.cashW * 100).toFixed(1)}% of NAV</title></rect>`;
      if (g.w > 60 && g.h > 24) svg += `<text class="tm-t" x="${(g.x + 8).toFixed(1)}" y="${(g.y + 18).toFixed(1)}">cash ${(d.cashW * 100).toFixed(0)}%</text>`;
      return;
    }
    if (g.w > 70 && g.h > LBL + 8) svg += `<text class="tm-glabel" x="${(g.x + 6).toFixed(1)}" y="${(g.y + 12).toFixed(1)}">${label.toUpperCase()} · ${(g.area * 100).toFixed(0)}%</text>`;
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
  return `<div class="rcc-card tm-card">
    <div class="chart-head"><h3>THESIS TREEMAP · <span class="c-3 w5">${sel === "5_werner" ? "the book" : (tierSpec(sel) || {}).short} · weight by area, one-day return by colour</span>${asOfBadge(d.date)}</h3>${selector}</div>
    <svg class="tm-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="thesis treemap">${svg}</svg>
    <div class="chart-meta">N<sub>eff</sub> = <strong class="c-1">${d.neff != null ? d.neff : "—"}</strong> effective bets across ${d.n} positions · grouped by thesis (largest membership) · dashed = provisional or partial membership · ${legend} · bounded ±3% daily</div>
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
    const cell = (k, v, s, cls) => `<div class="so-cell"><div class="k">${k}</div><div class="v ${cls || ""}">${v}</div><div class="s">${s}</div></div>`;
    strip = `<div class="so-strip">
      ${cell("REGIME INDEX · READING", `${rg.state || "—"} · R<sub>full</sub> ${rg.R_full != null ? (+rg.R_full).toFixed(3) : "—"}`, `tier-4 exposure ${rg.exposure != null ? (rg.exposure * 100).toFixed(0) + "%" : "—"} · as of ${rg.as_of || cp.session_date}`, cc(ewColor(rg.state)))}
      ${cell("10-MONTH SMA · MONTHLY", String(sm.state || "—").toUpperCase(), `P<sub>m</sub> ${sm.computed_from.P_m} vs SMA10 ${(+sm.computed_from.sma10).toFixed(2)} at ${sm.computed_from.month_end_date}${sm.evaluation && sm.evaluation.next_evaluation ? " · next " + sm.evaluation.next_evaluation : ""}`, expCls(sm.exposure))}
      ${cell("12-1 MOMENTUM · MONTHLY", String(tm.state || "—").toUpperCase(), `12-1 return ${(tm.computed_from.ret_12_1 * 100).toFixed(1)}% (${tm.computed_from.P_m_12_date} → ${tm.computed_from.P_m_1_date})${tm.evaluation && tm.evaluation.next_evaluation ? " · next " + tm.evaluation.next_evaluation : ""}`, expCls(tm.exposure))}
      ${cell("10% VOL TARGET · DAILY", `${(vt.exposure * 100).toFixed(0)}% exposure`, `σ<sub>60</sub> ${(vt.computed_from.sigma_ann * 100).toFixed(1)}% ann. through ${vt.computed_from.through} · min(1, 10% / σ)`, expCls(vt.exposure))}
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
  const hits = Object.entries(reg).filter(([k, t]) => t.members && t.members[tk]).sort((a, b) => b[1].members[tk] - a[1].members[tk]);
  if (!hits.length) return "unclassified";
  const [k, t] = hits[0]; return `${thesisLabel(k)}${t.members[tk] < 0.999 ? " · " + t.members[tk].toFixed(2) : ""}`;
}
function renderBookPanel(){
  const h = S.tournament && S.tournament.history; if (!h || !h.length) return "";
  const last = h[h.length - 1], prev = h.length > 1 ? h[h.length - 2] : null;
  const w = last.tiers && last.tiers["5_werner"]; if (!w) return "";
  const prevPx = {}; ((prev && prev.tiers && prev.tiers["5_werner"] && prev.tiers["5_werner"].positions) || []).forEach(p => { if (p.price) prevPx[p.ticker] = p.price; });
  const hf = S.holdingsFile; const acq = {}; ((hf && hf.holdings) || []).forEach(x => { acq[x.ticker] = x; });
  const pos = (w.positions || []).filter(p => p.value > 0).map(p => {
    const cost = p.cost_basis != null ? p.cost_basis : (acq[p.ticker] && acq[p.ticker].cost_basis);
    const pl = cost ? (p.price - cost) * p.shares : null, plPct = cost ? p.price / cost - 1 : null;
    const r1 = prevPx[p.ticker] ? p.price / prevPx[p.ticker] - 1 : null;
    return {...p, cost, pl, plPct, r1};
  }).sort((a, b) => b.value - a.value);
  const equity = pos.reduce((s, p) => s + p.value, 0), cash = w.cash || 0, nav = equity + cash;
  const costTot = pos.reduce((s, p) => s + (p.cost ? p.cost * p.shares : 0), 0);
  const plTot = pos.reduce((s, p) => s + (p.pl || 0), 0);
  const base1 = pos.reduce((s, p) => s + (p.r1 != null ? p.value / (1 + p.r1) : 0), 0);
  const r1Tot = base1 > 0 ? pos.reduce((s, p) => s + (p.r1 != null ? p.value - p.value / (1 + p.r1) : 0), 0) / base1 : null;
  const th = S.thesis && S.thesis.tiers && S.thesis.tiers["5_werner"];
  const exp = (th && th.exposure_invested) || {};
  const bars = Object.entries(exp).sort((a, b) => b[1] - a[1]).map(([k, v]) =>
    `<div class="th-exp-row"><span class="th-exp-k mono t1 c-2">${thesisLabel(k)}</span><span class="th-exp-bar"><span class="${cc(thesisColor(k), 'bg')}" style="width:${(v * 100).toFixed(1)}%"></span></span><span class="th-exp-v mono t1 c-1">${(v * 100).toFixed(0)}%</span></div>`).join("");
  const money = v => "$" + fmt(Math.round(Math.abs(v)));
  const pl = v => v == null ? "—" : `<span class="${v >= 0 ? "c-pos" : "c-neg"}">${v >= 0 ? "+" : "−"}${money(v)}</span>`;
  const pct = v => v == null ? "—" : `<span class="${v >= 0 ? "c-pos" : "c-neg"}">${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%</span>`;
  return `<div class="rcc-card book-panel"><h3>THE BOOK · <span class="c-3 w5">tier 5 · positions from data/holdings.json, the only holdings source</span>${asOfBadge(last.date)}</h3>
    <div class="tbl-scroll"><table class="book-table">
      <tr><th>TICKER</th><th class="num">WEIGHT</th><th class="num">SHARES</th><th class="num">COST</th><th class="num">PRICE</th><th class="num">UNREALIZED</th><th class="num">%</th><th class="num">1D</th><th>THESIS</th></tr>
      ${pos.map(p => `<tr><td class="mono t2 c-1 w6">${p.ticker}</td><td class="num">${(p.value / nav * 100).toFixed(1)}%</td><td class="num">${p.shares}</td><td class="num">${p.cost != null ? p.cost.toFixed(2) : "—"}</td><td class="num">${p.price.toFixed(2)}</td><td class="num">${pl(p.pl)}</td><td class="num">${pct(p.plPct)}</td><td class="num">${pct(p.r1)}</td><td class="c-3 t1">${thesisOf(p.ticker)}${acq[p.ticker] && acq[p.ticker].acquired ? " · acquired " + acq[p.ticker].acquired : ""}</td></tr>`).join("")}
      <tr class="book-total"><td class="mono t2 c-1 w6">TOTAL</td><td class="num">${(equity / nav * 100).toFixed(1)}%</td><td class="num">${pos.length} names</td><td class="num">${money(costTot)}</td><td class="num">${money(equity)}</td><td class="num">${pl(plTot)}</td><td class="num">${costTot ? pct(equity / costTot - 1) : "—"}</td><td class="num">${pct(r1Tot)}</td><td class="c-3 t1">cash ${money(cash)} · NAV ${money(nav)}</td></tr>
    </table></div>
    <div class="book-grid">
      <div><div class="fx-head mono t1 c-3">THESIS EXPOSURE · <span class="c-3">N<sub>eff</sub> ${th && th.n_eff != null ? th.n_eff : "—"} effective bets · invested ${th && th.invested_share != null ? (th.invested_share * 100).toFixed(0) + "%" : "—"} of NAV</span></div>
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
  const rows = acts.map(a => {
    const v = pub[a.session_date]; const rt = v && v.R_t_published != null && v.R_t_published !== "" ? (+v.R_t_published).toFixed(4) : "not published";
    return `<tr>
      <td><a class="c-info" href="data/regime_daily_published.csv" title="published vintage row ${a.session_date}: R_t ${rt}${v && v.no_publish_reason ? " · " + v.no_publish_reason : ""}">${a.session_date}</a></td>
      <td>${(tierSpec(a.tier) || {}).short || a.tier}</td>
      <td class="c-1">${(a.action || []).join(", ")}</td>
      <td class="c-3">${(a.entries || []).length ? "+" + a.entries.join(" ") : ""}${(a.exits || []).length ? " −" + a.exits.join(" ") : ""}</td>
      <td class="c-2" title="before: ${fmtW(a.weights_before)} · after: ${fmtW(a.weights_after)}">cash ${a.target_cash_pct_before}% → ${a.target_cash_pct_after}%</td>
      <td>${a.regime || "—"} · ${a.R_full != null ? a.R_full : "—"}</td>
      <td class="c-3 mono t1" title="sha256 of the input snapshot (prices, holdings, R_t)">${String(a.input_snapshot_sha256 || "").slice(0, 12)}</td>
    </tr>`; }).join("");
  return `<div class="rcc-card act-panel"><h3>ACTION LOG · <span class="c-3 w5">append-only · newest first · last 30 of ${(S.actions || []).length}</span></h3>
    ${rows ? `<div class="tbl-scroll"><table><tr><th>SESSION</th><th>TIER</th><th>ACTION</th><th>NAMES</th><th>SIZING</th><th>REGIME · R<sub>full</sub></th><th>INPUT HASH</th></tr>${rows}</table></div>`
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
  return `<div class="rcc-card cal-panel"><h3>V4 CALIBRATION · <span class="c-3 w5">reliability of ${win.replace("_", " ")}: in-sample vs out-of-fold, one axis</span>${asOfBadge(c.as_of)}</h3>
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
function renderCalendarCard(){
  const ev = (S.eventCal && S.eventCal.events) || [];
  const today = _etDateISO(new Date());
  const next = ev.filter(e => e && e.date >= today).slice(0, 8);
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

function render(){
  const a = document.getElementById("app");
  if (!S.config) { a.innerHTML = '<div class="ld">config.json missing</div>'; return; }

  const live = S.tournament && S.tournament.history && S.tournament.history.length > 0
    ? S.tournament.history[S.tournament.history.length-1] : null;
  const R = live ? live.R_t : null;
  const regime = live ? live.regime : "—";
  const updated = S.tournament && S.tournament.last_updated
    ? new Date(S.tournament.last_updated).toLocaleString("en-US",{timeZone:"America/New_York",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit"})
    : "—";

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
  let leader = null, leaderRet = -Infinity;
  Object.entries(tmMap).forEach(([tid, m]) => { if (m && m.total > leaderRet) { leaderRet = m.total; leader = tid; } });

  // ---- Slim header ----
  let h = `<div class="hd2">
    <div>
      <span class="hd-dot"></span><h1 class="inl">PORTFOLIO TOURNAMENT</h1>
      <span class="mono t1 c-3 ml2">v2.0</span>
      <a class="mono t1 c-info ml2" href="guide.html" title="How to read this — the guide page">how to read this →</a>
      <div class="hd2-sub">${updated} · 4 algo tiers + Werner · monthly rescore + regime overlay</div>
    </div>
  </div>`;

  // ---- 0. INTRADAY SHOCK / STALENESS BANNER — a live alert, stays above everything ----
  h += renderTopBanner();

  // ══ TIER ONE (P1.4): gauge with its moved-by line · the claim sentence · the drawdown chart ══
  const rv = renderRegimeCommandCenter(R);
  const statusStrip = renderStatusStrip();
  h += `<div class="tier tier-1"><h2 class="tier-title">REGIME</h2>
    ${statusStrip ? `<div class="only-mobile">${statusStrip}</div>` : ""}
    <div class="tier1-grid">${rv.gauge}${renderDrawdownCard()}</div></div>`;

  // ══ TIER TWO: leaderboard · treemap · regime-and-overlay · the book ══
  h += `<div class="tier tier-2"><h2 class="tier-title">TOURNAMENT &amp; BOOK</h2>`;

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
  const sorted = Object.entries(tmMap).filter(([_,m]) => m != null).sort((a,b) => {
    if (!condMode) return (b[1].total - a[1].total);
    const ca = condFor(a[0]); const cb = condFor(b[0]);
    return ((cb && cb.shrunk_ann_return) || -9e9) - ((ca && ca.shrunk_ann_return) || -9e9);
  });

  const toggleHtml = `<span class="cond-toggle">
    <button class="${!condMode ? "on" : ""}" data-cond-mode="off">UNCONDITIONAL</button>
    <button class="${condMode  ? "on" : ""}" data-cond-mode="on">CONDITIONAL · ${currentState || "—"}</button>
  </span>`;

  const sc = S.condScores || {};
  const sn = (sc.state_day_counts || {})[currentState] || 0;
  const condCap = condMode
    ? `<div class="cond-caption">CONDITIONAL on <strong class="c-accent">${currentState || "—"}</strong>: scores are James-Stein shrunk toward unconditional. Bucket n = ${sn} days. ${sc.caption || ""}</div>`
    : "";

  h += `<div class="lbtable">
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
    h += `<tr class="tier-row ${open?"open":""}" data-tid="${tid}">
      <td class="rank ${i===0?"first":""}">${i+1}</td>
      <td>
        <span class="tier-dot ${cc(t.color,'bg')}"></span>
        <span class="tier-name">${t.short}</span>
        <div class="tier-desc">${(t.description||"").substring(0,80)}${(t.description||"").length>80?"…":""}</div>
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

  // rest of tier two: treemap (P2.3) · retirement panel (P2.2) · regime & overlay · the book (P3.2)
  h += renderTreemapCard() + renderRetirementPanel();
  h += `<div class="tier2-grid">${renderRegimeOverlayPanel()}<div>${rv.timeline}${rv.deployment}</div></div>`;
  h += renderBookPanel();
  h += `</div>`;   // close tier two

  // ══ TIER THREE (reduced type and contrast): indicators · thesis register · v4 · status · records · calendar ══
  // P5.1: on mobile every tier-three panel sits under a disclosure control, closed by default;
  // on desktop the controls are open and their summaries hidden (CSS).
  const isMobile = window.matchMedia && window.matchMedia("(max-width: 820px)").matches;
  const d3 = (title, html) => html ? `<details class="t3-panel"${isMobile ? "" : " open"}><summary>${title}</summary>${html}</details>` : "";
  h += `<div class="tier tier-3"><h2 class="tier-title">RECORDS &amp; SIGNALS</h2>`;
  h += `<div class="only-desktop">${statusStrip}</div>` + renderRegistryBanner();
  h += d3("INDICATOR READINGS", rv.indicators);
  h += d3("THESIS REGISTER", renderThesisSection());
  h += d3("V4 RANKING PANEL", rv.v4);
  h += d3("SCANNER", renderScanner());
  h += d3("ACTION LOG", renderActionLog()) + d3("V4 CALIBRATION", renderCalibrationPanel()) + d3("CALENDAR", renderCalendarCard());

  // ---- Footer ----
  h += `<div class="ft">
    <span class="k">SCORING </span>4-factor cross-sectional model: technical (MA200 dist, RSI, 6m relative strength) + fundamental (Fwd P/E, rev growth, gross/op margins, ROE). Tier 3/4 double-weight 6m RS.<br>
    <span class="k">SELECTION </span>Monthly. Each tier picks top-N from its filtered universe — Tier 1 restricted to defensive sectors with GM>30% and FCF>0; Tiers 2-4 use the full universe.<br>
    <span class="k">REGIME </span>R<sub>t</sub> from 12 risk indicators z-scored over 252 days, mapped via Φ, equal-weight mean. Sizes cash sleeve per tier formula.<br>
    <span class="k">TIER 5 (WERNER) </span>Positions from data/holdings.json — the only holdings source, read by the screener too. Not backtested (no discretionary history). Updated when Werner trades.<br>
    <span class="k">DATA </span>Yahoo + FRED. Updated weekdays 6 pm ET (daily NAV) and 1st of month 10 am ET (rescore + reselect).
  </div>`;

  h += `</div>`;   // close tier three
  a.innerHTML = h;
  applyTweens();   // P1.5: value changes tween over --tween (200 ms; 0 under reduced motion)

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

  // Draw charts after DOM
  setTimeout(() => {
    renderRegimeTimeline();
    renderRopCurveChart();
    renderThesisRsChart();
    renderChart(allSeries, S.period);
    renderDrawdownChart();      // P2.1 (tier one)
    renderC3PathChart();        // P2.2 (tier two)
    renderCalibrationChart();   // P4.2 (tier three)
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

async function loadJSON(path){ try { const r = await fetch(path + "?" + Date.now()); if (r.ok) return await r.json(); } catch(e){} return null; }
async function loadCSV(path){
  try { const r = await fetch(path + "?" + Date.now()); if (!r.ok) return null;
    return Papa.parse(await r.text(), {header:true, dynamicTyping:true, skipEmptyLines:true}).data;
  } catch(e){ return null; }
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

async function init(){
  S.config     = await loadJSON("config.json");
  S.tournament = await loadJSON("data/tournament.json");
  S.holdings   = await loadJSON("data/tier_holdings.json");
  S.tickers    = await loadJSON("data/ticker_indicators.json");
  S.metrics    = await loadJSON("data/backtest_metrics.json");
  S.regime     = await loadJSON("data/regime_indicators.json");
  S.status     = await loadJSON("data/status.json");   // order item 6: pipeline + audit status strip
  S.regimeDaily = await loadCSV("data/regime_daily.csv");
  S.indicatorSeries = await loadJSON("data/indicator_series.json");
  S.signals    = await loadJSON("data/ticker_signals.json");
  S.regimeV4   = await loadCSV("data/regime_v4_daily.csv");
  S.v4Cal      = await loadJSON("data/v4_calibration.json");
  try { S.c2 = await loadJSON("data/c2_vintage_comparison.json"); } catch (e) { S.c2 = null; }   // memo §6 disclosure
  try { S.c3 = await loadJSON("data/c3_results.json"); } catch (e) { S.c3 = null; }             // memo §1 verdicts of record
  try { S.backtestDD = await loadJSON("data/backtest_drawdown.json"); } catch (e) { S.backtestDD = null; }   // P2.1 companion
  try { S.comparators = await loadJSON("data/comparators.json"); } catch (e) { S.comparators = null; }     // P2.2 second opinion
  try { S.c3Paths = await loadJSON("data/c3_drawdown_paths.json"); } catch (e) { S.c3Paths = null; }       // P2.2 C3 drawdown paths
  try { S.provLedger = await loadJSON("data/provisional_ledger.json"); } catch (e) { S.provLedger = null; } // P2.3 provisional memberships
  try { S.factors = await loadJSON("data/factor_exposure.json"); } catch (e) { S.factors = null; }         // P3.3 style-factor exposure
  try { S.holdingsFile = await loadJSON("data/holdings.json"); } catch (e) { S.holdingsFile = null; }      // P3.1 the only holdings source
  try {                                                                                                     // P4.1 action log (jsonl)
    const r = await fetch("data/actions.jsonl?" + Date.now());
    S.actions = r.ok ? (await r.text()).split("\n").filter(l => l.trim()).map(l => { try { return JSON.parse(l); } catch (e) { return null; } }).filter(Boolean) : [];
  } catch (e) { S.actions = []; }
  S.intraday   = await loadJSON("data/intraday.json");
  S.volRegime  = await loadJSON("data/vol_regime.json");
  S.condScores = await loadJSON("data/regime_conditional_scores.json");
  S.eventCal   = await loadJSON("data/event_calendar.json");
  S.regimePub  = await loadCSV("data/regime_daily_published.csv");
  S.thesis     = await loadJSON("data/thesis_daily.json");
  S.thesisReg  = await loadJSON("data/thesis_registry.json");
  S.thesisClaims = await loadJSON("data/thesis_claims.json");
  S.thesisBT   = await loadJSON("data/thesis_backtest.json");
  S.v4Attr     = await loadJSON("data/v4_delta_attribution.json");
  S.regProposals = await loadJSON("data/registry_proposals.json");
  const rows   = await loadCSV("data/backtest_equity_curves.csv");
  S.backtest   = rows ? {rows} : null;

  if (!S.config) {
    document.getElementById("app").innerHTML = '<div class="ld">config.json not found</div>';
    return;
  }
  if (!S.tournament && !S.backtest) {
    document.getElementById("app").innerHTML = `<div class="ld">No tournament data yet.</div>`;
    return;
  }
  render();
}
init();

// P5.1: re-render when the viewport crosses the mobile breakpoint (disclosure state, chart ticks)
(() => {
  const mq = window.matchMedia ? window.matchMedia("(max-width: 820px)") : null;
  if (!mq) return;
  let was = mq.matches, timer = null;
  window.addEventListener("resize", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { if (mq.matches !== was) { was = mq.matches; if (S.config) render(); } }, 150);
  });
})();
