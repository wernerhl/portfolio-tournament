"use strict";
// screen.js — the screen view (relocated from portfolio-screener/index.html on 2026-09-16, order 6.3).
// Reads data/screen/*; adds the visibility registry and the reconciliation panel; descriptive throughout.
let SC = {data: null, status: null, visReg: null, recon: null, universeMeta: null, sort: {watch: null, book: null, vis: null}};

const CAT = {Growth: 'info', Compounder: 'pos', Core: '2', Cyclical: 'warn', Speculative: 'neg', Catalyst: 'accent'};
const catKind = c => CAT[c] || '2';
const badge = c => `<span class="badge sig-${catKind(c)}">${(c || 'Core').toUpperCase()}</span>`;
const HELD = '<span class="badge sig-pos" title="In the book (data/holdings.json)">HELD</span>';
const BB = '<span class="badge sig-neg" title="Broken base — price >10% below base with RSI<25 · technical score capped at 12/25">BB</span>';

const fmt = n => typeof n === 'number' ? n.toLocaleString('en-US', {minimumFractionDigits: 0, maximumFractionDigits: 0}) : '—';
const fmtD = n => typeof n === 'number' ? n.toFixed(2) : '—';
const fmtP = n => typeof n === 'number' ? (n >= 0 ? '+' : '') + n.toFixed(1) + '%' : '—';
const pnl = n => n >= 0 ? 'pos' : n < 0 ? 'neg' : 'neut';
const scoreCls = s => s >= 55 ? 'c-pos' : s >= 45 ? 'c-warn' : s >= 35 ? 'c-2' : 'c-neg';
const penCls = (v, red) => v == null ? 'c-3' : v < red ? 'c-neg' : v < 0 ? 'c-warn' : 'c-3';

// options lens (order 26-Sept-2026, 3.1): the board's third column — volatility state and the event line
const OPT_CLS = {cheap: 'c-pos', rich: 'c-warn', mixed: 'c-2'}, OPT_GL = {cheap: '◯', rich: '●', mixed: '◐'};
function optionsCell(tk){
  const o = SC.optionsLens && SC.optionsLens.names && SC.optionsLens.names[tk]; if (!o) return '<span class="c-3">—</span>';
  const v = o.volatility || {}, e = o.event || {};
  const soon = e.days_to != null && e.days_to >= 0 && e.days_to <= 30;
  const st = o.impaired ? '<span class="c-warn w6" title="fewer than 70% of front-expiry strikes carry live bid-ask quotes">IMPAIRED</span>'
                        : `<span class="${OPT_CLS[v.state] || 'c-3'} w6" title="IV30 ${v.iv30 != null ? (v.iv30 * 100).toFixed(1) + '%' : '—'} vs RV21 ${v.rv21 != null ? (v.rv21 * 100).toFixed(1) + '%' : '—'} / RV63 ${v.rv63 != null ? (v.rv63 * 100).toFixed(1) + '%' : '—'}">${OPT_GL[v.state] || ''} ${v.state || '—'}</span>`;
  const ev = e.next_earnings ? ` <span class="${soon ? 'c-warn' : 'c-3'}" title="earnings ${e.next_earnings}${e.implied_move != null ? '; market prices ±' + (e.implied_move * 100).toFixed(1) + '%' : ''}${e.history && e.history.median_abs != null ? '; median past reaction ' + (e.history.median_abs * 100).toFixed(1) + '%' : ''}">${soon ? '◎ ' : ''}${e.days_to != null && e.days_to >= 0 ? e.days_to + 'd' : e.next_earnings}${e.implied_move != null ? ' ±' + (e.implied_move * 100).toFixed(1) + '%' : ''}</span>` : '';
  return st + ev;
}

// Order 2-Oct-2026 [E2]: the entry state on the board (DIAGNOSTIC until the registered validation reports)
const ES_CLS = {AVOID: 'c-neg', WATCH: 'c-warn', READY: 'c-pos', 'READY-HALF': 'c-pos'};
const esRec = tk => (SC.entryState && SC.entryState.names && SC.entryState.names[tk]) || null;
const esEsc = x => String(x == null ? '' : x).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
// Order 6-Oct-2026 (rules version 3): the flags that change a state or a size
function esFlags(e){
  const f = [];
  if (e.trend && e.trend.below_200d && e.trend.pass) f.push(['<200d', 'below the 200-day average (momentum positive): size halved']);
  if (e.ceiling_flag) f.push(['ceiling', `a multi-year ceiling at $${fmtD(((e.long_range || {}).ceiling || {}).level)} within 15% above: capped at WATCH`]);
  if (e.heavily_shorted) { const si = e.short_interest || {}; f.push(['shorted', `days-to-cover ${si.days_to_cover != null ? si.days_to_cover : '—'}, short interest ${si.short_pct_float != null ? (si.short_pct_float * 100).toFixed(1) + '% of the float' : '—'} (set by ${(e.heavily_shorted_by || []).join(' and ') || '—'}): size halved`]); }
  if ((e.earnings || {}).conflict) f.push(['date?', (e.earnings || {}).conflict_text || 'earnings date conflict']);
  if ((e.provider_flags || []).length) f.push(['data?', 'provider data suspect: ' + e.provider_flags.map(x => x.field + ' (' + x.reason + ')').join('; ')]);
  return f;
}
// phones: the board scrolls sideways, so the state also sits under the ticker
function esMini(tk){
  const e = esRec(tk);
  if (!e || !e.state) return '';
  const fl = esFlags(e).map(x => x[0]).join(' ');
  return `<span class="only-mobile t1 mt1"><span class="es-badge ${ES_CLS[e.state] || 'c-3'}">${e.state}</span><span class="c-warn"> ${esEsc(fl)}</span></span>`;
}
function esCells(tk){
  const e = esRec(tk);
  if (!e || !e.state) return `<td class="t1 c-3" title="${esEsc((e && e.reason) || 'not computed')}">—</td><td class="num c-3">—</td><td class="num c-3">—</td><td class="num c-3">—</td><td class="num c-3">—</td>`;
  const z = e.size || {};
  const fl = esFlags(e);
  const flags = fl.length ? fl.map(x => `<span class="c-warn" title="${esEsc(x[1])}">${esEsc(x[0])}</span>`).join(' ') : '<span class="c-3">—</span>';
  const size = z.shares != null ? `${z.shares}${e.size_factor != null && e.size_factor < 1 ? ` <span class="c-3">×${e.size_factor}</span>` : ''}` : '<span class="c-3">—</span>';
  const earn = e.sessions_to_earnings != null ? `<span class="${e.sessions_to_earnings <= 20 ? 'c-warn' : 'c-3'}">${e.sessions_to_earnings}</span>` : `<span class="c-3" title="${e.earnings_known ? 'no date ahead' : 'earnings date unknown'}">?</span>`;
  const why = e.state === 'AVOID' ? 'trend gate fails (below the 200-day with negative momentum)' : e.state === 'WATCH' ? (e.watch_reason || 'watch') : 'a passing trend gate';
  const tip = `${e.state} · ${why} · stop $${e.stop}${z.shares != null ? ' · ' + z.shares + ' shares, ' + ((z.risk_budget || 0.005) * 100).toFixed(3).replace(/0+$/, '') + '% of the account at risk' + (z.capped_by ? ', capped by ' + z.capped_by : '') : ''} · ${(SC.entryState && SC.entryState.label) || 'DIAGNOSTIC'}`;
  return `<td class="t1"><span class="es-badge ${ES_CLS[e.state] || 'c-3'} w6" title="${esEsc(tip)}">${e.state}</span></td><td class="t1">${flags}</td><td class="num ${e.state.startsWith('READY') ? 'c-neg' : 'c-3'}">$${fmtD(e.stop)}</td><td class="num">${size}</td><td class="num">${earn}</td>`;
}

const sbar = r => `<span class="sbar" style="--f:${r.fundamental ?? 0};--t:${r.technical ?? 0};--v:${r.visibility ?? 0}"><span class="bg-cat-2"></span><span class="bg-cat-7"></span><span class="bg-cat-3"></span></span><span class="t1 c-3 nowrap">F${r.fundamental} T${r.technical} V${r.visibility}</span>`;
const legend = full => `<div class="legend">
  <span><span class="sw bg-cat-2"></span>Fundamental</span>
  <span><span class="sw bg-cat-7"></span>Technical</span>
  <span><span class="sw bg-cat-3"></span>Visibility</span>
  <span>Scores: 0–25 per factor · 75 max composite · a ranking of names, not a forecast; name selection has no measured skill</span>${full ? `
  <span title="the board ranks names against the current book; held names are scored against the rest of the book">CORR = penalty for return overlap vs the book (weight-aware, held names vs rest-of-book) · n/a = failed, no penalty, reason recorded</span>
  <span>LEV = leverage penalty 0 to −5 (net-debt/EBITDA primary, D/E fallback) · financials exempt</span>
  <span>MR REF = the mean-reversion reference (the higher of the 50-day average and 5% below price), formerly "entry level"; a reference, not an entry signal · vs REF = the reference's distance from the price</span>
  <span>ENTRY STATE, rules version 3 (DIAGNOSTIC until its registered validation reports): AVOID below the 200-day with negative 12-month momentum · READY a passing trend gate, extended or pulling back (entry timing is information only) · READY-HALF the same with earnings inside 20 sessions · WATCH capped by a multi-year ceiling, or the size modifiers below a quarter · FLAGS &lt;200d (size ×½), shorted (days-to-cover 7+ or short interest 20%+ of the float, ×½), ceiling, date? (earnings date conflict), data? (provider data suspect) · STOP the 40-session low less 1 ATR · SIZE shares at 0.5% of the account at risk × the modifiers, capped below 40% of the book's risk · EARN sessions to earnings · a rule output, not an instruction${SC.entryState && SC.entryState.validation ? ' · validation: ' + esEsc(SC.entryState.validation.summary || '') : ''}</span>` : ''}
</div>`;

function sortBy(data, key, dir){
  return [...data].sort((a, b) => { let va = a[key], vb = b[key];
    if (typeof va === 'string') return dir * va.localeCompare(vb);
    if (va == null) return 1; if (vb == null) return -1; return dir * (va - vb); });
}
const th = (tbl, k, label, num) => { const s = SC.sort[tbl];
  const cls = [num ? 'num' : '', k && s && s.k === k ? (s.dir > 0 ? 'sort asc' : 'sort') : ''].filter(Boolean).join(' ');
  return `<th${cls ? ` class="${cls}"` : ''}${k ? ` data-tbl="${tbl}" data-k="${k}"` : ''}>${label}</th>`; };
const ordered = (tbl, rows) => { const s = SC.sort[tbl]; return s ? sortBy(rows, s.k, s.dir) : rows; };

function renderStrips(D){
  const st = SC.status || {};
  const strip = (kind, txt) => `<div class="strip strip-${kind}">${txt}</div>`;
  let b = '';
  const sd = D.session_date;
  // 1-Oct-2026: the same freshness rule as every other page (common.js freshnessOf): a close is
  // pending until 09:30 ET the next session, stale only once that publish was due and missed.
  if (sd) {
    const f = freshnessOf(sd);
    if (f === 'stale') b += strip('warn', `⚠ The board is as of ${sd}; the ${prevSessionISO(dueSessionISO(), 0)} session's run did not publish${st.failure_reason ? ' — ' + st.failure_reason : ''}`);
    else if (f === 'pending') b += strip('2', `◷ The board is as of ${sd}; the ${lastTradingSessionISO()} close is published overnight`);
  }
  if (st.failure_reason && !b) b += strip('2', `ℹ board is current (session ${sd}); a later redundant run was rejected (${st.failure_reason}) — served board unaffected`);
  const au = st.audit || {};
  if (au.critical?.length) b += strip('neg', `✗ audit CRITICAL — ${au.critical.join(', ')} · served board is the last good one`);
  if (au.high?.length) b += strip('2', `audit: ${au.high.length} HIGH — ${au.high.join(', ')} <span class="c-3">(logged, non-blocking)</span>`);
  if (typeof D.corr_coverage_pct === 'number' && D.corr_coverage_pct < 90) b += strip('warn', `⚠ correlation coverage ${D.corr_coverage_pct}% — ${(D.corr_impaired || []).length} names impaired (reasons in data)`);
  const hp = (D.provenance || {}).holdings_source || {};
  if (hp.as_of) b += strip('2', `book: holdings.json as of <strong class="c-1">${hp.as_of}</strong> · ${hp.mode || ''} · ${hp.n_holdings || 0} positions`);
  return b;
}

function renderWatchlist(W, U){
  const rows = ordered('watch', W);
  const nTop = W.filter(r => r.on_board_as !== 'held').length, nHeld = W.length - nTop;
  const head = `<div class="lb-h"><h2>THE BOARD${SC.optionsLens ? optionsAgeBadge(SC.optionsLens.session_date) : ''}</h2><div class="lb-h-sub">top ${nTop} of ${U.total || 0} by composite${nHeld ? ` + ${nHeld} held name${nHeld === 1 ? '' : 's'} outside the top 40 (always on the board)` : ''} · HELD = in the book · descriptive ranking</div></div>`;
  if (!W.length) return `<div class="lbtable">${head}<div class="note">No board data</div></div>`;
  return `<div class="lbtable">${head}
  <div class="tbl-scroll"><table class="board-table"><thead><tr>
    ${th('watch', 'rank', '#', 1)}${th('watch', 'ticker', 'TICKER')}${th('watch', 'name', 'NAME')}${th('watch', 'sector', 'SECTOR')}${th('watch', 'composite', 'SCORE', 1)}${th('watch', null, 'BREAKDOWN')}${th('watch', 'corr_penalty', 'CORR', 1)}${th('watch', 'leverage_penalty', 'LEV', 1)}${th('watch', 'current_price', 'PRICE', 1)}<th title="entry state, DIAGNOSTIC">ENTRY STATE</th><th title="flags that change a state or a size">FLAGS</th><th class="num">STOP</th><th class="num">SIZE</th><th class="num">EARN</th>${th('watch', 'entry_level', 'MR REF', 1)}${th('watch', null, 'vs REF', 1)}${th('watch', 'category', 'CAT')}${th('watch', null, 'OPTIONS')}
  </tr></thead><tbody>
    ${rows.map(r => {
      const gap = r.entry_level && r.current_price ? ((r.entry_level / r.current_price - 1) * 100) : 0;
      const gapCls = 'neut';   // 2-Oct-2026: the reference is not coloured as a place to enter
      const corrT = r.corr_status === 'unavailable' ? 'correlation unavailable — computation failed, no penalty applied' : (r.max_corr_with ? `highest overlap ${r.max_corr_with} |ρ|=${r.max_corr ?? '—'} · vs book ρ=${r.portfolio_corr ?? '—'}` : '');
      const levT = r.lev_status === 'financial_na' ? 'financial — leverage n/a by construction' : r.lev_status === 'unavailable' ? 'leverage unavailable — no penalty applied' : r.nd_ebitda != null ? `net-debt/EBITDA ${r.nd_ebitda}` : (r.lev_status || '');
      return `<tr${r.on_board_as === 'held' ? ' class="dim"' : ''}>
      <td class="num c-3">${r.rank ?? ''}</td>
      <td class="tk">${r.ticker}${r.held ? ' ' + HELD : ''}${r.broken_base ? ' ' + BB : ''}${esMini(r.ticker)}</td>
      <td class="nm">${r.name}</td>
      <td class="t1 c-3">${(r.sector || '').substring(0, 18)}</td>
      <td class="num w7 ${scoreCls(r.composite)}">${r.composite}</td>
      <td>${sbar(r)}</td>
      <td class="num ${penCls(r.corr_penalty, -4)}" title="${corrT}">${r.corr_penalty == null ? 'n/a' : r.corr_penalty}</td>
      <td class="num ${penCls(r.leverage_penalty, -3)}" title="${levT}">${r.leverage_penalty == null ? 'n/a' : r.leverage_penalty}</td>
      <td class="num">$${fmtD(r.current_price)}</td>
      ${esCells(r.ticker)}
      <td class="num c-3" title="mean-reversion reference; not an entry signal">$${fmtD(r.entry_level)}</td>
      <td class="num ${gapCls}">${gap.toFixed(1)}%</td>
      <td>${badge(r.category)}</td>
      <td class="t1 nowrap">${optionsCell(r.ticker)}</td>
    </tr>`; }).join('')}
  </tbody></table></div>
  ${legend(true)}
  </div>`;
}

function renderDrawdownWatch(DW){
  const head = `<div class="lb-h"><h2>DRAWDOWN WATCH — QUALITY NAMES IN A BROKEN TECHNICAL STATE</h2><div class="lb-h-sub">${DW.length} name${DW.length === 1 ? '' : 's'} · fundamental ≥ 18 and visibility ≥ 15 with a broken base · technical score capped · descriptive</div></div>`;
  if (!DW.length) return `<div class="lbtable">${head}<div class="note">None today — no quality name is in a broken technical state.</div></div>`;
  return `<div class="lbtable">${head}
  <div class="tbl-scroll"><table><thead><tr>
    <th class="num">#</th><th>TICKER</th><th>NAME</th><th class="num">F</th><th class="num">V</th><th class="num">T (CAPPED)</th><th class="num">BELOW BASE</th><th class="num">RSI</th><th class="num">CORR</th>
  </tr></thead><tbody>
    ${DW.map((r, i) => `<tr>
      <td class="num c-3">${i + 1}</td>
      <td class="tk">${r.ticker} ${BB}</td>
      <td class="nm">${r.name || ''}</td>
      <td class="num">${r.fundamental ?? '—'}</td><td class="num">${r.visibility ?? '—'}</td>
      <td class="num c-3">${r.technical_capped ?? '—'}</td>
      <td class="num neg">${r.depth_below_base_pct ?? '—'}%</td>
      <td class="num">${r.rsi ?? '—'}</td>
      <td class="num" title="${r.max_corr_with ? `highest overlap ${r.max_corr_with} · vs book ρ=${r.portfolio_corr ?? '—'}` : ''}">${r.corr_penalty == null ? 'n/a' : r.corr_penalty}</td>
    </tr>`).join('')}
  </tbody></table></div>
  <div class="note">Technical state: broken (score capped). Ranked by business quality and visibility only. Timing has no validated expectancy.</div>
  </div>`;
}

function renderUniverse(U, D){
  const total = U.total || 0;
  const dist = (map, kind) => { const es = Object.entries(map || {}).sort((a, b) => b[1] - a[1]); const max = es.length ? Math.max(1, es[0][1]) : 1;
    return es.map(([k, n]) => `<div class="th-exp-row mono t1 c-1"><span class="dist-lbl" title="${k}">${k}</span><div class="th-exp-bar"><span class="${kind === 'cat' ? 'bg-' + catKind(k) : 'bg-info'}" style="width:${(n / max * 100).toFixed(1)}%"></span></div><span class="th-exp-v">${n}</span></div>`).join(''); };
  const um = SC.universeMeta;
  return `<div class="lbtable">
    <div class="lb-h"><h2>UNIVERSE STATISTICS</h2><div class="lb-h-sub">${total} tickers scored · composite 0–75 · session ${D.session_date || '—'}${um ? ` · one universe of ${um.union_size} (tournament ∪ screen ∪ midcaps ∪ held)` : ''}</div></div>
    <div class="panel-body">
      <div class="stats">
        <div class="stat-cell"><div class="k">TICKERS</div><div class="v">${fmt(total)}</div><div class="s">scored this session</div></div>
        <div class="stat-cell"><div class="k">MEDIAN SCORE</div><div class="v">${U.median_score ?? '—'}</div><div class="s">mean ${U.mean_score ?? '—'}</div></div>
        <div class="stat-cell"><div class="k">TOP SCORE</div><div class="v">${U.max_score ?? '—'}</div><div class="s">of 75</div></div>
        <div class="stat-cell"><div class="k">LOWEST SCORE</div><div class="v">${U.min_score ?? '—'}</div><div class="s">of 75</div></div>
      </div>
      <div class="dist-grid">
        <div><div class="dist-head">BY SECTOR</div>${dist(U.sectors, 'sec') || '<div class="note">—</div>'}</div>
        <div><div class="dist-head">BY CATEGORY</div>${dist(U.categories, 'cat') || '<div class="note">—</div>'}</div>
      </div>
    </div>
  </div>`;
}

// the visibility registry, every provenance field shown
function renderVisibilityRegistry(){
  const V = SC.visReg; if (!V) return '';
  const es = Object.entries(V.entries || {}).map(([tk, e]) => ({ticker: tk, ...e}));
  const rows = ordered('vis', es).map(e => `<tr>
    <td class="tk">${e.ticker}</td><td class="num w7">${e.value}</td><td class="num c-3">${e.sector_prior ?? '—'}<span class="t1"> ${e.delta_vs_prior != null ? '(' + (e.delta_vs_prior >= 0 ? '+' : '') + e.delta_vs_prior + ')' : ''}</span></td>
    <td class="nm" title="${(e.rationale || '').replace(/"/g, "'")}">${e.rationale || ''}</td>
    <td class="t1 c-3">${e.source || ''}</td><td class="t1 c-3">${e.as_of || ''}</td><td class="t1 c-3">${e.cadence || ''}</td><td class="t1 c-3">${e.next_earnings || '—'}</td>
    <td class="t1 ${e.review_by && e.review_by < (SC.data && SC.data.session_date || '') ? 'c-warn' : 'c-3'}">${e.review_by || '—'}</td>
    <td class="t1 c-3">${e.falsification ? (e.falsification.claim || '') + (e.falsification.hard_triggers ? ' · triggers: ' + e.falsification.hard_triggers : '') : ''}</td>
  </tr>`).join('');
  const retired = (V.retired || []).map(r => `<div class="mono t1 c-3">${r.ticker} · value ${r.value} · retired ${r.retired_at} (${r.reason})</div>`).join('');
  const pol = V.policy || {};
  return `<div class="lbtable">
    <div class="lb-h"><h2>VISIBILITY REGISTRY</h2><div class="lb-h-sub">v${V.version} · frozen ${V.frozen_at || 'PENDING'} · ${es.length} entries · every provenance field · ${V.approval || ''}</div></div>
    <div class="tbl-scroll"><table><thead><tr>${th('vis', 'ticker', 'TICKER')}${th('vis', 'value', 'VALUE', 1)}${th('vis', 'sector_prior', 'PRIOR', 1)}${th('vis', 'rationale', 'RATIONALE')}${th('vis', 'source', 'SOURCE')}${th('vis', 'as_of', 'AS OF')}${th('vis', 'cadence', 'CADENCE')}${th('vis', 'next_earnings', 'NEXT EARNINGS')}${th('vis', 'review_by', 'REVIEW BY')}<th>FALSIFICATION</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="legend"><span>review: ${pol.review || ''}</span><span>decay: ${pol.decay || ''}</span><span>retirement: ${pol.retirement || ''}</span><span>fallback cap ${pol.fallback_cap ?? ''}</span></div>
    ${retired ? `<div class="panel-body"><div class="dist-head">RETIRED</div>${retired}</div>` : ''}
  </div>`;
}

// the reconciliation panel: rank correlation between the two scoring views and the ten largest divergences with attributed cause
function renderReconciliation(){
  const R = SC.recon; if (!R) return `<div class="lbtable"><div class="lb-h"><h2>RECONCILIATION</h2><div class="lb-h-sub">data/screen/reconciliation.json not published yet (written nightly by scripts/screen/reconcile_views.py)</div></div></div>`;
  const rho = R.spearman || {}; const top = R.divergences || R.top_divergences || [];
  const pc = v => v == null ? '' : ` (${(+v).toFixed(0)}th pct)`;
  const rows = top.map((d, i) => { const T = d.tournament || {}, Sc = d.screen || {}; const comp = (d.components || {})[d.cause] || {};
    return `<tr>
    <td class="num c-3">${i + 1}</td><td class="tk">${d.ticker}<div class="t1 c-3 nm">${d.name || ''}</div></td>
    <td class="num">${T.rank ?? '—'}<span class="t1 c-3"> of ${T.n ?? '—'}${pc(T.pct)}</span></td>
    <td class="num">${Sc.rank ?? '—'}<span class="t1 c-3"> of ${Sc.n ?? '—'}${pc(Sc.pct)}</span></td>
    <td class="num w7">${d.divergence_pct_points != null ? (+d.divergence_pct_points).toFixed(0) + ' pts' : '—'}</td>
    <td class="c-1">${String(d.cause || '—').replace(/_/g, ' ')}${d.cause_rank_points != null ? ` <span class="t1 c-3">(${(+d.cause_rank_points).toFixed(0)} rank pts, ${d.cause_share_of_divergence != null ? (d.cause_share_of_divergence * 100).toFixed(0) + '% of the gap' : ''})</span>` : ''}</td>
    <td class="t1 c-3">${d.direction || ''}${Sc.broken_base ? ' · broken base (technical capped ' + Sc.technical_precap + '→' + Sc.technical + ')' : ''}${Sc.leverage_penalty ? ' · leverage ' + Sc.leverage_penalty : ''}${Sc.corr_penalty ? ' · correlation ' + Sc.corr_penalty : ''}${Sc.registry_override ? ' · visibility override ' + Sc.visibility + ' vs prior ' + Sc.sector_prior : ''}</td>
  </tr>`; }).join('');
  return `<div class="lbtable">
    <div class="lb-h"><h2>RECONCILIATION — THE TWO SCORING VIEWS</h2><div class="lb-h-sub">rank correlation of the tournament's composite (technical + fundamental, 0–50) and the screen's composite (fundamental + technical + visibility − penalties, 0–75) on ${R.n_common ?? R.n ?? '—'} common names · session ${R.session_date || '—'}</div></div>
    <div class="panel-body"><div class="stats">
      <div class="stat-cell"><div class="k">SPEARMAN · COMPOSITE</div><div class="v">${rho.composite != null ? (+rho.composite).toFixed(3) : (R.rho != null ? (+R.rho).toFixed(3) : '—')}</div><div class="s">n ${R.n_common ?? R.n ?? '—'}</div></div>
      <div class="stat-cell"><div class="k">SPEARMAN · TECHNICAL</div><div class="v">${rho.technical != null ? (+rho.technical).toFixed(3) : '—'}</div><div class="s">tech score vs technical</div></div>
      <div class="stat-cell"><div class="k">SPEARMAN · FUNDAMENTAL</div><div class="v">${rho.fundamental != null ? (+rho.fundamental).toFixed(3) : '—'}</div><div class="s">fund score vs fundamental</div></div>
      <div class="stat-cell"><div class="k">DIVERGENCES SHOWN</div><div class="v">${top.length}</div><div class="s">largest percentile-rank gaps</div></div>
    </div></div>
    <div class="tbl-scroll"><table><thead><tr><th class="num">#</th><th>TICKER</th><th class="num">TOURNAMENT RANK</th><th class="num">SCREEN RANK</th><th class="num">GAP</th><th>ATTRIBUTED CAUSE</th><th>DETAIL</th></tr></thead><tbody>${rows}</tbody></table></div>
    <div class="note">${R.method || 'cause = the screen-only component (visibility override, correlation penalty, leverage penalty, broken-base cap) that moves the name most in rank points; otherwise the larger of the technical and fundamental disagreements'}</div>
  </div>`;
}

function renderBook(P){
  const H = P.holdings || [];
  const costBasis = H.reduce((s, h) => s + h.cost * h.shares, 0);
  const totalGain = H.reduce((s, h) => s + (h.current_price - h.cost) * h.shares, 0);
  const gainPct = costBasis ? totalGain / costBasis * 100 : null;
  const rows = ordered('book', H);
  const table = H.length ? `<div class="tbl-scroll"><table><thead><tr>
    ${th('book', 'ticker', 'TICKER')}${th('book', 'name', 'NAME')}${th('book', 'shares', 'SHARES', 1)}${th('book', 'cost', 'COST', 1)}${th('book', 'current_price', 'PRICE', 1)}${th('book', 'market_value', 'VALUE', 1)}${th('book', 'gain_pct', 'GAIN', 1)}${th('book', 'composite', 'SCORE', 1)}${th('book', null, 'BREAKDOWN')}${th('book', 'category', 'CAT')}
  </tr></thead><tbody>
    ${rows.map(r => `<tr>
      <td class="tk">${r.ticker}</td><td class="nm">${r.name}</td><td class="num">${r.shares}</td><td class="num">$${fmtD(r.cost)}</td><td class="num">$${fmtD(r.current_price)}</td><td class="num">$${fmt(r.market_value)}</td>
      <td class="num ${pnl(r.gain_pct)}">${fmtP(r.gain_pct)}</td><td class="num w7 ${scoreCls(r.composite)}">${r.composite}</td><td>${sbar(r)}</td><td>${badge(r.category)}</td>
    </tr>`).join('')}
  </tbody></table></div>${legend(false)}` : `<div class="note">No holdings data</div>`;
  return `<div class="lbtable">
    <div class="lb-h"><h2>THE BOOK, AS THE SCREEN SEES IT</h2><div class="lb-h-sub">${H.length} position${H.length === 1 ? '' : 's'} + cash · holdings from data/holdings.json · the book's analytics are on book.html</div></div>
    <div class="panel-body"><div class="stats">
      <div class="stat-cell"><div class="k">TOTAL VALUE</div><div class="v">$${fmt(P.total_value)}</div><div class="s">${H.length} positions + cash</div></div>
      <div class="stat-cell"><div class="k">EQUITY</div><div class="v">$${fmt(P.total_equity)}<small>${P.equity_pct || 0}%</small></div><div class="s">${H.length} positions</div></div>
      <div class="stat-cell"><div class="k">CASH</div><div class="v">$${fmt(P.cash)}<small>${P.cash_pct || 0}%</small></div><div class="s">cash</div></div>
      <div class="stat-cell"><div class="k">UNREAL. P&amp;L</div><div class="v ${pnl(totalGain)}">${totalGain >= 0 ? '+' : ''}$${fmt(Math.abs(totalGain))}</div><div class="s">${gainPct == null ? '—' : fmtP(gainPct) + ' on cost'}</div></div>
    </div></div>
    ${table}
  </div>`;
}

function render(){
  const a = document.getElementById('app');
  if (!SC.data) { a.innerHTML = renderNav('screen') + '<div class="ld">No screen data (data/screen/scores.json).</div>'; return; }
  const D = SC.data, P = D.portfolio || {}, W = D.watchlist || [], U = D.universe || {}, DW = D.drawdown_watch || [];
  const asOf = D.computed_at ? new Date(D.computed_at).toLocaleString('en-US', {timeZone: 'America/New_York', month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit'}) + ' ET' : '—';
  const isMobile = window.matchMedia && window.matchMedia('(max-width: 820px)').matches;
  const d3 = (title, html) => html ? `<details class="t3-panel"${isMobile ? '' : ' open'}><summary>${title}</summary>${html}</details>` : '';
  let h = renderNav('screen') + pageHeader('THE SCREEN', `${U.total || 0} tickers scored · 4-factor model · daily refresh · as of ${asOf}${D.session_date ? ` · session ${D.session_date}` : ''}`);
  h += `<section class="tier tier-1">${renderStrips(D)}</section>`;
  h += `<section class="tier tier-2"><h2 class="tier-title">THE BOARD</h2>${renderWatchlist(W, U)}${renderDrawdownWatch(DW)}</section>`;
  h += `<section class="tier tier-3"><h2 class="tier-title">REGISTRY, RECONCILIATION, UNIVERSE</h2>
    ${d3('VISIBILITY REGISTRY', renderVisibilityRegistry())}
    ${d3('RECONCILIATION', renderReconciliation())}
    ${d3('UNIVERSE STATISTICS', renderUniverse(U, D))}
    ${d3('THE BOOK', renderBook(P))}
    <div class="ft">
      <span class="k">MODEL </span>4-factor: Fundamental (FCF yield, growth, margins, ROIC) + Technical (200-DMA, RSI, rel str, support) + Visibility (registered backlog overrides, sector prior capped) + Correlation penalty vs the book + Leverage penalty<br>
      <span class="k">SCHEDULE </span>Nightly re-score in the single workflow, after the canonical closes and the fundamentals artifact · holdings from data/holdings.json · the universe from data/universe.txt<br>
      <span class="k">READING </span>A ranking of names by the model's factors; descriptive. Name selection has no measured skill.
    </div>
  </section>`;
  a.innerHTML = h;
  phoneTidy();
  document.querySelectorAll('th[data-k]').forEach(el => el.addEventListener('click', () => {
    const t = el.dataset.tbl, k = el.dataset.k; const cur = SC.sort[t];
    if (cur && cur.k === k) cur.dir *= -1; else SC.sort[t] = {k, dir: -1};
    render();
  }));
}

async function init(){
  await loadFiles(['screen', 'screenStatus', 'visReg', 'reconciliation', 'universeMeta', 'optionsLens', 'entryState'], SC);
  SC.data = SC.screen; SC.status = SC.screenStatus; SC.recon = SC.reconciliation;
  render();
}
init();
(() => { const mq = window.matchMedia ? window.matchMedia('(max-width: 820px)') : null; if (!mq) return; let was = mq.matches, timer = null;
  window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(() => { if (mq.matches !== was) { was = mq.matches; if (SC.data) render(); } }, 150); }); })();
