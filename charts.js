/* charts.js — the ONE Chart.js configuration for the tournament dashboard (order 9 Sept 2026, P1.3).
   Every chart on the page is built through CHARTS.make(); nothing calls `new Chart` directly.
   Binds: mono face for axes, serif for titles; sizes from the type scale; gridlines = hairline at
   1px; tooltips as surface cards with the hairline border; palette = the four semantic colours,
   the accent, two neutrals and the tier identities; legends off, replaced by direct labels at
   series ends; line weights 1.5 series / 1 benchmark / 2 headline; animation off after the first
   render (and off entirely under prefers-reduced-motion). The treemap is plain SVG (not here).
   The screener copies this file (not linked), so each site deploys independently. */
const CHARTS = (() => {
  const root = () => getComputedStyle(document.documentElement);
  const tok = name => root().getPropertyValue("--" + name).trim();
  const px = name => parseFloat(tok(name)) || 11;
  const reduced = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const hexToRgb = h => { h = h.replace("#", ""); if (h.length === 3) h = h.split("").map(c => c + c).join(""); const n = parseInt(h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
  const alpha = (color, a) => { const c = String(color).trim(); if (c.startsWith("#")) { const [r, g, b] = hexToRgb(c); return `rgba(${r},${g},${b},${a})`; } return c; };
  const TIER_TOKEN = {"1_cap_pres": "tier1", "2_balanced": "tier2", "3_aggressive": "tier3", "4_tactical": "tier4", "5_werner": "tier5"};
  const colors = () => ({
    pos: tok("pos"), neg: tok("neg"), warn: tok("warn"), info: tok("info"), accent: tok("accent"),
    n1: tok("text-2"), n2: tok("text-3"),                          // the two neutrals
    text1: tok("text-1"), surface: tok("surface"), surface2: tok("surface-2"), hairline: tok("hairline"), hairlineHi: tok("hairline-hi"), bg: tok("bg"),
    tier: Object.fromEntries(Object.entries(TIER_TOKEN).map(([tid, t]) => [tid, tok(t)])),
    bench: {spy: tok("text-2"), qqq: tok("text-3"), "60_40": tok("text-3"), sso: tok("hairline-hi")},
  });
  const WEIGHT = {series: 1.5, benchmark: 1, headline: 2};

  // Direct labels at the right end of each visible dataset (replaces legends). Simple vertical
  // de-collision: labels are pushed apart by one line height, in y order.
  const directLabels = {
    id: "directLabels",
    afterDatasetsDraw(chart, _args, opts) {
      if (opts && opts.enabled === false) return;
      const c = colors(); const ctx = chart.ctx; const area = chart.chartArea;
      const font = `${500} ${px("t1")}px ${tok("mono")}`;
      const entries = [];
      chart.data.datasets.forEach((ds, i) => {
        if (ds.directLabel === false || !chart.isDatasetVisible(i)) return;
        const meta = chart.getDatasetMeta(i); const pts = meta.data;
        if (!pts || !pts.length) return;
        let last = null; for (let j = pts.length - 1; j >= 0; j--) { const p = pts[j]; if (p && !p.skip && isFinite(p.y)) { last = p; break; } }
        if (!last) return;
        const label = ds.directLabel != null ? ds.directLabel : ds.label;
        if (!label) return;
        const color = typeof ds.borderColor === "string" ? ds.borderColor : c.n1;
        entries.push({y: last.y, x: last.x, label: String(label), color});
      });
      if (!entries.length) return;
      entries.sort((a, b) => a.y - b.y);
      const lh = px("t1") + 3;
      for (let i = 1; i < entries.length; i++) if (entries[i].y - entries[i - 1].y < lh) entries[i].y = entries[i - 1].y + lh;
      ctx.save(); ctx.font = font; ctx.textBaseline = "middle"; ctx.textAlign = "left";
      for (const e of entries) {
        const x = Math.min(e.x + 6, area.right + 2);
        const y = Math.max(area.top + lh / 2, Math.min(area.bottom - lh / 2, e.y));
        const w = ctx.measureText(e.label).width + 6;
        ctx.fillStyle = alpha(c.surface, 0.85); ctx.fillRect(x - 3, y - lh / 2, w, lh);
        ctx.fillStyle = e.color; ctx.fillText(e.label, x, y);
      }
      ctx.restore();
    },
  };
  // Animation only on the first render of a chart.
  const animateOnce = { id: "animateOnce", afterRender(chart) { if (chart.options.animation !== false) { chart.options.animation = false; } } };

  const base = () => {
    const c = colors();
    const tick = {color: c.n2, font: {family: tok("mono"), size: px("t1")}, maxRotation: 0, padding: 4};
    return {
      responsive: true, maintainAspectRatio: false,
      animation: reduced() ? false : {duration: 200},
      interaction: {mode: "nearest", axis: "x", intersect: false},
      layout: {padding: {right: 8}},
      elements: {line: {borderWidth: WEIGHT.series, tension: 0.1, borderCapStyle: "round"}, point: {radius: 0, hitRadius: 6, hoverRadius: 3}},
      scales: {
        x: {grid: {color: c.hairline, lineWidth: 1, drawTicks: false}, border: {color: c.hairlineHi}, ticks: {...tick}},
        y: {grid: {color: c.hairline, lineWidth: 1, drawTicks: false}, border: {display: false}, ticks: {...tick}},
      },
      plugins: {
        legend: {display: false},
        title: {display: false, color: c.text1, font: {family: tok("serif"), size: px("t3"), weight: "500"}},
        tooltip: {
          backgroundColor: c.surface, borderColor: c.hairlineHi, borderWidth: 1, cornerRadius: px("radius-1"),
          titleColor: c.text1, bodyColor: c.n1, padding: px("s2"), displayColors: false,
          titleFont: {family: tok("mono"), size: px("t1"), weight: "600"}, bodyFont: {family: tok("mono"), size: px("t1")},
        },
        directLabels: {enabled: true},
      },
    };
  };
  const isObj = v => v && typeof v === "object" && !Array.isArray(v) && !(v instanceof Function);
  const merge = (a, b) => { const out = {...a}; for (const k of Object.keys(b || {})) out[k] = (isObj(a[k]) && isObj(b[k])) ? merge(a[k], b[k]) : b[k]; return out; };

  let made = 0;
  function make(ctx, cfg) {
    const options = merge(base(), cfg.options || {});
    const data = cfg.data || {};
    (data.datasets || []).forEach(ds => {
      const role = ds.role || "series";
      ds.borderWidth = WEIGHT[role] != null ? WEIGHT[role] : WEIGHT.series;
      if (ds.pointRadius == null) ds.pointRadius = 0;
    });
    made++;
    return new Chart(ctx, {type: cfg.type, data, options, plugins: [directLabels, animateOnce, ...(cfg.plugins || [])]});
  }
  return {make, colors, alpha, tok, px, get count() { return made; }, WEIGHT};
})();
