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

const sbar = r => `<span class="sbar" style="--f:${r.fundamental ?? 0};--t:${r.technical ?? 0};--v:${r.visibility ?? 0}"><span class="bg-cat-2"></span><span class="bg-cat-7"></span><span class="bg-cat-3"></span></span><span class="t1 c-3 nowrap">F${r.fundamental} T${r.technical} V${r.visibility}</span>`;
const legend = full => `<div class="legend">
  <span><span class="sw bg-cat-2"></span>Fundamental</span>
  <span><span class="sw bg-cat-7"></span>Technical</span>
  <span><span class="sw bg-cat-3"></span>Visibility</span>
  <span>Scores: 0–25 per factor · 75 max composite · a ranking of names, not a forecast; name selection has no measured skill</span>${full ? `
  <span title="the board ranks names against the current book; held names are scored against the rest of the book">CORR = penalty for return overlap vs the book (weight-aware, held names vs rest-of-book) · n/a = failed, no penalty, reason recorded</span>
  <span>LEV = leverage penalty 0 to −5 (net-debt/EBITDA primary, D/E fallback) · financials exempt</span>
  <span>LEVEL = the screen's base level (the higher of the 50-day average and 5% below price) · GAP = distance from that level to the price (negative = below)</span>` : ''}
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
  if (sd) {
    const now = new Date(new Date().toLocaleString('en-US', {timeZone: 'America/New_York'}));
    const past = (now.getHours() > 16) || (now.getHours() === 16 && now.getMinutes() >= 15);
    const HOL = new Set(["2025-01-01","2025-01-09","2025-01-20","2025-02-17","2025-04-18","2025-05-26","2025-06-19","2025-07-04","2025-09-01","2025-11-27","2025-12-25",
      "2026-01-01","2026-01-19","2026-02-16","2026-04-03","2026-05-25","2026-06-19","2026-07-03","2026-09-07","2026-11-26","2026-12-25",
      "2027-01-01","2027-01-18","2027-02-15","2027-03-26","2027-05-31","2027-06-18","2027-07-05","2027-09-06","2027-11-25","2027-12-24"]);
    const iso = x => new Date(x.getTime() - x.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
    const isSess = x => x.getDay() >= 1 && x.getDay() <= 5 && !HOL.has(iso(x));
    let d = new Date(now);
    if (!(isSess(d) && past)) { do { d.setDate(d.getDate() - 1); } while (!isSess(d)); }
    const exp = iso(d);
    if (sd < exp) b += strip('warn', `⚠ as of ${sd}; today's run did not publish${st.failure_reason ? ' — ' + st.failure_reason : ''}`);
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
  const head = `<div class="lb-h"><h2>THE BOARD</h2><div class="lb-h-sub">top ${nTop} of ${U.total || 0} by composite${nHeld ? ` + ${nHeld} held name${nHeld === 1 ? '' : 's'} outside the top 40 (always on the board)` : ''} · HELD = in the book · descriptive ranking</div></div>`;
  if (!W.length) return `<div class="lbtable">${head}<div class="note">No board data</div></div>`;
  return `<div class="lbtable">${head}
  <div class="tbl-scroll"><table><thead><tr>
    ${th('watch', 'rank', '#', 1)}${th('watch', 'ticker', 'TICKER')}${th('watch', 'name', 'NAME')}${th('watch', 'sector', 'SECTOR')}${th('watch', 'composite', 'SCORE', 1)}${th('watch', null, 'BREAKDOWN')}${th('watch', 'corr_penalty', 'CORR', 1)}${th('watch', 'leverage_penalty', 'LEV', 1)}${th('watch', 'current_price', 'PRICE', 1)}${th('watch', 'entry_level', 'LEVEL', 1)}${th('watch', null, 'GAP', 1)}${th('watch', 'category', 'CAT')}
  </tr></thead><tbody>
    ${rows.map(r => {
      const gap = r.entry_level && r.current_price ? ((r.entry_level / r.current_price - 1) * 100) : 0;
      const gapCls = gap <= -2 ? 'pos' : gap >= 2 ? 'neg' : 'neut';
      const corrT = r.corr_status === 'unavailable' ? 'correlation unavailable — computation failed, no penalty applied' : (r.max_corr_with ? `highest overlap ${r.max_corr_with} |ρ|=${r.max_corr ?? '—'} · vs book ρ=${r.portfolio_corr ?? '—'}` : '');
      const levT = r.lev_status === 'financial_na' ? 'financial — leverage n/a by construction' : r.lev_status === 'unavailable' ? 'leverage unavailable — no penalty applied' : r.nd_ebitda != null ? `net-debt/EBITDA ${r.nd_ebitda}` : (r.lev_status || '');
      return `<tr${r.on_board_as === 'held' ? ' class="dim"' : ''}>
      <td class="num c-3">${r.rank ?? ''}</td>
      <td class="tk">${r.ticker}${r.held ? ' ' + HELD : ''}${r.broken_base ? ' ' + BB : ''}</td>
      <td class="nm">${r.name}</td>
      <td class="t1 c-3">${(r.sector || '').substring(0, 18)}</td>
      <td class="num w7 ${scoreCls(r.composite)}">${r.composite}</td>
      <td>${sbar(r)}</td>
      <td class="num ${penCls(r.corr_penalty, -4)}" title="${corrT}">${r.corr_penalty == null ? 'n/a' : r.corr_penalty}</td>
      <td class="num ${penCls(r.leverage_penalty, -3)}" title="${levT}">${r.leverage_penalty == null ? 'n/a' : r.leverage_penalty}</td>
      <td class="num">$${fmtD(r.current_price)}</td>
      <td class="num c-info">$${fmtD(r.entry_level)}</td>
      <td class="num ${gapCls}">${gap.toFixed(1)}%</td>
      <td>${badge(r.category)}</td>
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
  document.querySelectorAll('th[data-k]').forEach(el => el.addEventListener('click', () => {
    const t = el.dataset.tbl, k = el.dataset.k; const cur = SC.sort[t];
    if (cur && cur.k === k) cur.dir *= -1; else SC.sort[t] = {k, dir: -1};
    render();
  }));
}

async function init(){
  await loadFiles(['screen', 'screenStatus', 'visReg', 'reconciliation', 'universeMeta'], SC);
  SC.data = SC.screen; SC.status = SC.screenStatus; SC.recon = SC.reconciliation;
  render();
}
init();
(() => { const mq = window.matchMedia ? window.matchMedia('(max-width: 820px)') : null; if (!mq) return; let was = mq.matches, timer = null;
  window.addEventListener('resize', () => { clearTimeout(timer); timer = setTimeout(() => { if (mq.matches !== was) { was = mq.matches; if (SC.data) render(); } }, 150); }); })();
