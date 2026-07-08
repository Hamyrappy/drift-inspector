/* ==========================================================================
   compare.js — Compare view: thematic profiles of subsamples.
   A subsample (cohort) is defined by conference (venue), author, or keyword set,
   and can be narrowed to a range of years (independently per cohort).
   - When two cohorts are set, "Where they differ most" sits on top (the gap is
     the headline); each cohort's own profile follows below.
   - Each cohort gets its OWN profile diagram (ranked bars by default, treemap opt).
   - "Over time" shows a single subsample's drift across years (bump / stacked).
   - Clicking any cluster mark anywhere opens a side drawer listing the real
     claims of that cluster *within the picked subsample*, each linking straight
     to its paper on the ACL Anthology.
   One or two cohorts (leave B empty to study just one). All client-side.
   ========================================================================== */
'use strict';

window.CompareView = (function () {
  let built = false;
  let claims = null;            // unified claim stream across all sources
  let nameToId = null;          // author display name -> id
  let metric = 'mix';           // 'mix' = % of claims · 'df' = % of papers
  let scope = 'ALL';            // 'ALL' | <year> | 'overtime' (global year filter)
  let A = null, B = null;       // cohort definitions {type, value, y0, y1}
  const TOP_TREEMAP = 22, TOP_DIFF = 16, TOP_DRIFT = 8;
  const DRAWER_PAGE = 14;
  let profileMode = 'bars';      // 'bars' | 'treemap'  (ranked bars read better)
  let diffMode = 'diverging';    // 'diverging' | 'dumbbell' | 'scatter'
  let driftMode = 'bump';        // 'bump' | 'stacked'

  // claims drawer state
  let drawerCid = null;          // cluster currently shown in the drawer
  let drawerTab = 'A';           // which cohort's claims are listed
  let drawerShown = DRAWER_PAGE;
  let drawerQuery = '';
  let drawerYear = null;         // when set, drawer lists a single year (bump-chart click)
  let drawerFilterTimer = null;  // pending debounce for the drawer filter

  // A small segmented view-switcher; onPick(value) re-renders.
  function modeSeg(current, opts, onPick) {
    const seg = document.createElement('div');
    seg.className = 'seg cmp-modeseg';
    opts.forEach(([v, l]) => {
      const b = document.createElement('button');
      b.className = 'seg-btn' + (v === current ? ' active' : '');
      b.textContent = l;
      b.addEventListener('click', () => onPick(v));
      seg.appendChild(b);
    });
    return seg;
  }

  /* --------------------------- data assembly ---------------------------- */
  function sources() { return ACC.state.data.sources || []; }
  function venues() { return sources().map(s => s.venue); }
  function venueColor(v) { const s = sources().find(x => x.venue === v); return s ? s.color : ACC.pal().acc; }
  function allYears() { return ACC.state.data.meta.years; }

  function buildClaims() {
    const d = ACC.state.data, out = [];
    // All venues live in `points`, tagged by `points.source` (index into sources).
    const srcs = sources(), P = d.points, abp = d.authorsByPaper || [], src = P.source || [];
    for (let i = 0; i < P.x.length; i++) {
      const venue = (srcs[src[i]] || {}).venue || '?';
      out.push({ i, y: P.year[i], c: P.cluster[i], pk: src[i] + ':' + P.paper[i], venue,
                 aids: abp[P.paper[i]] || [], t: P.claim[i].toLowerCase() });
    }
    const idx = d.authorsIndex || {}, byName = {};
    for (const id in idx) { const [nm, n] = idx[id]; if (!byName[nm] || n > byName[nm][1]) byName[nm] = [id, n]; }
    nameToId = {}; for (const nm in byName) nameToId[nm] = byName[nm][0];
    return out;
  }

  /* ----------------------------- cohorts -------------------------------- */
  function predicate(cohort) {
    if (!cohort || cohort.type === 'none') return null;
    if (cohort.type === 'venue') return cl => cl.venue === cohort.value;
    if (cohort.type === 'author') { const id = cohort.value; return id ? (cl => cl.aids.includes(id)) : null; }
    if (cohort.type === 'keyword') {
      const terms = String(cohort.value || '').toLowerCase().split(/[,\s]+/).filter(Boolean);
      return terms.length ? (cl => terms.some(t => cl.t.includes(t))) : null;
    }
    return null;
  }
  function isSet(cohort) { return !!predicate(cohort); }

  // Inclusive [lo, hi] year bounds for a cohort (defaults to the full corpus span).
  function cohortRange(cohort) {
    const ys = allYears();
    const lo = cohort && cohort.y0 != null ? cohort.y0 : ys[0];
    const hi = cohort && cohort.y1 != null ? cohort.y1 : ys[ys.length - 1];
    return [Math.min(lo, hi), Math.max(lo, hi)];
  }
  function cohortYearList(cohort) {
    const [lo, hi] = cohortRange(cohort);
    return allYears().filter(y => y >= lo && y <= hi);
  }
  // Effective years for a cohort = its own range ∩ the global year filter.
  function effYears(cohort) {
    const [lo, hi] = cohortRange(cohort);
    if (scope !== 'ALL' && scope !== 'overtime') {
      return (scope >= lo && scope <= hi) ? [scope] : [];
    }
    return allYears().filter(y => y >= lo && y <= hi);
  }
  // Short human label for a cohort's active year window (its range ∩ global year).
  function windowLabel(cohort) {
    const ys = allYears();
    const eff = effYears(cohort);
    if (!eff.length) return '—';                                   // empty intersection
    const lo = eff[0], hi = eff[eff.length - 1];
    if (scope !== 'ALL' && scope !== 'overtime') return String(scope);
    if (lo === ys[0] && hi === ys[ys.length - 1]) return 'all years';
    return lo === hi ? String(lo) : (lo + '–' + hi);
  }

  function profileAt(cohort, year) {
    const pred = predicate(cohort);
    const [lo, hi] = cohortRange(cohort);
    const byC = new Map(), papers = new Set();
    let nClaims = 0;
    if (pred) for (const cl of claims) {
      if (year === 'ALL') { if (cl.y < lo || cl.y > hi) continue; }
      else { if (cl.y !== year || cl.y < lo || cl.y > hi) continue; }
      if (!pred(cl)) continue;
      nClaims++; papers.add(cl.pk);
      if (cl.c === -1) continue;
      if (metric === 'df') { if (!byC.has(cl.c)) byC.set(cl.c, new Set()); byC.get(cl.c).add(cl.pk); }
      else byC.set(cl.c, (byC.get(cl.c) || 0) + 1);
    }
    const denom = metric === 'df' ? papers.size : nClaims;
    const out = new Map();
    for (const [c, v] of byC) { const num = metric === 'df' ? v.size : v; out.set(c, denom ? num / denom * 100 : 0); }
    return { nPapers: papers.size, nClaims, byCluster: out };
  }

  function cohortLabel(cohort) {
    if (!cohort || cohort.type === 'none') return '—';
    if (cohort.type === 'venue') return cohort.value;
    if (cohort.type === 'author') { const idx = ACC.state.data.authorsIndex || {}; return cohort.value && idx[cohort.value] ? idx[cohort.value][0] : 'author?'; }
    if (cohort.type === 'keyword') return '“' + (cohort.value || '…') + '”';
    return '—';
  }
  function cohortColor(cohort) {
    if (cohort && cohort.type === 'venue') return venueColor(cohort.value);
    return cohort === A ? ACC.pal().acc : ACC.pal().mut;
  }
  function cohortTag(cohort) { return cohort === A ? 'A' : cohort === B ? 'B' : undefined; }
  function clusterLabel(c) { const cl = ACC.state.clusterById.get(c); return cl ? cl.label : ('cluster ' + c); }
  function metricWord() { return metric === 'df' ? '% of papers' : '% of claims'; }

  /* ------------------------------ render -------------------------------- */
  function draw() {
    const cohorts = [A, B].filter(isSet);
    drawSummary();
    if (scope === 'overtime') { drawDrift(cohorts); document.getElementById('compare-versus').innerHTML = ''; }
    else { drawVersus(); drawProfiles(cohorts); }
    refreshDrawer();
  }

  function drawSummary() {
    const el = document.getElementById('compare-summary');
    const gl = scope === 'ALL' ? 'all years' : (scope === 'overtime' ? 'over time' : scope);
    const chip = (cohort, tag) => {
      if (!isSet(cohort)) return '';
      const p = profileAt(cohort, scope === 'overtime' ? 'ALL' : scope);
      const warn = p.nPapers < 5 ? ' <span class="cmp-warn">small sample</span>' : '';
      return `<span class="cmp-chip" style="border-left-color:${cohortColor(cohort)}"><b>${tag}</b> ` +
        `${ACC.escapeHtml(cohortLabel(cohort))} · <span class="cmp-chip-yr">${windowLabel(cohort)}</span> · ` +
        `${p.nPapers.toLocaleString()} papers · ${p.nClaims.toLocaleString()} claims${warn}</span>`;
    };
    el.innerHTML = chip(A, 'A') + chip(B, 'B') +
      `<span class="cmp-note">${metricWord()} · global year: ${gl}</span>`;
  }

  /* -- per-cohort profile treemaps (each subsample's own diagram) --------- */
  function drawProfiles(cohorts) {
    const host = document.getElementById('profile-panels');
    host.innerHTML = '';
    host.style.display = 'flex'; host.style.flexDirection = 'column'; host.style.gap = '10px';
    if (!cohorts.length) { host.innerHTML = '<div class="cmp-empty">Pick a subsample to see its topic profile.</div>'; return; }
    const bar = document.createElement('div'); bar.className = 'panel-modes';
    bar.innerHTML = '<span class="ctl-label">TOPICS AS</span>';
    bar.appendChild(modeSeg(profileMode, [['bars', 'Ranked bars'], ['treemap', 'Treemap']],
      v => { profileMode = v; draw(); }));
    host.appendChild(bar);
    const grid = document.createElement('div'); grid.className = 'panel-grid';
    grid.style.gridTemplateColumns = cohorts.length === 2 ? '1fr 1fr' : '1fr';
    host.appendChild(grid);
    cohorts.forEach((cohort, k) => {
      const panel = document.createElement('div');
      panel.className = 'profile-panel';
      panel.innerHTML = `<div class="panel-h"><span class="panel-tag" style="background:${cohortColor(cohort)}">${k === 0 ? 'A' : 'B'}</span>` +
        `<span class="panel-ttl">${ACC.escapeHtml(cohortLabel(cohort))}</span></div><div class="panel-plot"></div>`;
      grid.appendChild(panel);
      (profileMode === 'bars' ? drawRankedBars : drawTreemap)(panel.querySelector('.panel-plot'), cohort);
    });
  }

  /* -- ranked horizontal bars (readable per-cohort profile) -------------- */
  function drawRankedBars(div, cohort) {
    const prof = profileAt(cohort, scope === 'overtime' ? 'ALL' : scope);
    const entries = [...prof.byCluster.entries()].sort((a, b) => b[1] - a[1]).slice(0, TOP_TREEMAP);
    if (!entries.length) { div.innerHTML = '<div class="cmp-empty">No claims in this subsample.</div>'; return; }
    const p = ACC.pal();
    const rows = entries.slice().reverse();   // largest on top
    Plotly.react(div, [{
      type: 'bar', orientation: 'h',
      y: rows.map(([c]) => clusterLabel(c)),
      x: rows.map(([, v]) => +v.toFixed(2)),
      marker: { color: rows.map(([c]) => ACC.clusterColor(ACC.state.clusterById.get(c) || { id: c })) },
      text: rows.map(([, v]) => v.toFixed(1) + '%'), textposition: 'outside',
      textfont: { size: 9.5, color: p.fnt }, cliponaxis: false,
      customdata: rows.map(([c]) => c),
      hovertemplate: `%{y}<br>%{x:.1f}% ${metric === 'df' ? 'of papers' : 'of claims'}<br><span style="font-size:10px">click for its papers →</span><extra></extra>`,
    }], ACC.plBase({
      height: Math.max(300, rows.length * 20 + 40),
      margin: { l: 190, r: 46, t: 6, b: 26 },
      xaxis: { gridcolor: p.line, tickfont: { size: 9.5, color: p.fnt }, rangemode: 'tozero', ticksuffix: '%' },
      yaxis: { tickfont: { size: 10.5, color: p.ink2 }, gridcolor: 'rgba(0,0,0,0)', automargin: true },
      bargap: 0.28,
    }), ACC.plConfig({ displayModeBar: false }));
    div.on('plotly_click', ev => {
      const c = ev.points && ev.points[0] && ev.points[0].customdata;
      openClaims(c, { tag: cohortTag(cohort) });
    });
  }

  function drawTreemap(div, cohort) {
    const prof = profileAt(cohort, scope === 'overtime' ? 'ALL' : scope);
    const entries = [...prof.byCluster.entries()].sort((a, b) => b[1] - a[1]);
    if (!entries.length) { div.innerHTML = '<div class="cmp-empty">No claims in this subsample.</div>'; return; }
    const top = entries.slice(0, TOP_TREEMAP), rest = entries.slice(TOP_TREEMAP);
    const labels = [], values = [], colors = [], cdata = [];
    for (const [c, v] of top) { labels.push(clusterLabel(c)); values.push(+v.toFixed(2)); colors.push(ACC.clusterColor(ACC.state.clusterById.get(c) || { id: c })); cdata.push(c); }
    if (rest.length) { labels.push('other (' + rest.length + ')'); values.push(+rest.reduce((a, [, v]) => a + v, 0).toFixed(2)); colors.push(ACC.pal().line2); cdata.push(-99); }
    const p = ACC.pal();
    Plotly.react(div, [{
      type: 'treemap', labels, values, parents: labels.map(() => ''), customdata: cdata,
      marker: { colors, line: { width: 1, color: p.plot } },
      textinfo: 'label+value', texttemplate: '%{label}<br>%{value:.1f}%',
      textfont: { size: 11, color: '#fff', family: "'IBM Plex Sans', sans-serif" },
      hovertemplate: `%{label}<br>%{value:.1f}% ${metric === 'df' ? 'of papers' : 'of claims'}<extra></extra>`,
      tiling: { pad: 1 }, branchvalues: 'remainder',
    }], ACC.plBase({ height: 360, margin: { l: 4, r: 4, t: 4, b: 4 } }),
      ACC.plConfig({ displayModeBar: false }));
    div.removeAllListeners && div.removeAllListeners('plotly_treemapclick');
    div.on('plotly_click', ev => {
      const c = ev.points && ev.points[0] && ev.points[0].customdata;
      openClaims(c, { tag: cohortTag(cohort) });
    });
  }

  /* -- two-cohort comparison: the biggest gaps (lifted above the profiles) - */
  function drawVersus() {
    const host = document.getElementById('compare-versus');
    if (!(isSet(A) && isSet(B))) { host.innerHTML = ''; return; }
    const pa = profileAt(A, scope === 'overtime' ? 'ALL' : scope);
    const pb = profileAt(B, scope === 'overtime' ? 'ALL' : scope);
    const ids = new Set([...pa.byCluster.keys(), ...pb.byCluster.keys()]);
    const rows = [...ids].map(c => {
      const a = pa.byCluster.get(c) || 0, b = pb.byCluster.get(c) || 0;
      return { c, a, b, d: a - b, label: clusterLabel(c) };
    }).sort((x, y) => Math.abs(y.d) - Math.abs(x.d)).slice(0, TOP_DIFF);

    host.innerHTML = '';
    const head = document.createElement('div'); head.className = 'versus-head';
    head.innerHTML = '<span class="versus-h">Where they differ most</span>';
    head.appendChild(modeSeg(diffMode,
      [['diverging', 'Diverging'], ['dumbbell', 'Dumbbell'], ['scatter', 'Scatter']],
      v => { diffMode = v; draw(); }));
    host.appendChild(head);
    const plot = document.createElement('div'); host.appendChild(plot);
    const hl = document.createElement('div'); hl.className = 'compare-headlines'; host.appendChild(hl);

    const cA = cohortColor(A), cB = cohortColor(B);
    if (diffMode === 'dumbbell') drawDumbbell(plot, rows, cA, cB);
    else if (diffMode === 'scatter') drawScatter(plot, rows, cA, cB);
    else drawDiverging(plot, rows, cA, cB);
    drawHeadlines(hl, rows, cA, cB);
  }

  function drawDiverging(div, rows, cA, cB) {
    const p = ACC.pal();
    const r = rows.slice().sort((x, y) => x.d - y.d);          // B-leaning at the bottom
    Plotly.react(div, [{
      type: 'bar', orientation: 'h', y: r.map(x => x.label), x: r.map(x => +x.d.toFixed(2)),
      marker: { color: r.map(x => x.d >= 0 ? cA : cB) },
      customdata: r.map(x => [x.a, x.b]),
      text: r.map(x => (x.d >= 0 ? '+' : '') + x.d.toFixed(1)), textposition: 'outside',
      textfont: { size: 9, color: p.fnt }, cliponaxis: false,
      hovertemplate: `<b>%{y}</b><br>${ACC.escapeHtml(cohortLabel(A))}: %{customdata[0]:.1f}%25 · ` +
        `${ACC.escapeHtml(cohortLabel(B))}: %{customdata[1]:.1f}%25<br>Δ %{x:+.1f} pp<br><span style="font-size:10px">click for its papers →</span><extra></extra>`,
    }], ACC.plBase({
      height: Math.max(280, r.length * 24 + 60), margin: { l: 200, r: 46, t: 8, b: 40 },
      xaxis: { title: { text: `◀ ${cohortLabel(B)}   ·   Δ ${metricWord()}   ·   ${cohortLabel(A)} ▶`, font: { size: 10, color: p.mut } },
               zeroline: true, zerolinecolor: p.line2, gridcolor: p.line, tickfont: { size: 9.5, color: p.fnt } },
      yaxis: { tickfont: { size: 10.5, color: p.ink2 }, gridcolor: 'rgba(0,0,0,0)', automargin: true },
      bargap: 0.3,
    }), ACC.plConfig({ displayModeBar: false }));
    div.on('plotly_click', ev => { const i = ev.points[0].pointIndex; if (r[i]) openClaims(r[i].c); });
  }

  function drawDumbbell(div, rows, cA, cB) {
    const p = ACC.pal();
    const r = rows.slice().sort((x, y) => x.d - y.d);
    const lx = [], ly = [];
    r.forEach(x => { lx.push(x.a, x.b, null); ly.push(x.label, x.label, null); });
    const mk = (key, color, tag) => ({ type: 'scatter', mode: 'markers',
      x: r.map(x => x[key]), y: r.map(x => x.label), marker: { size: 10, color }, name: tag,
      customdata: r.map(x => x.c),
      hovertemplate: `<b>%{y}</b><br>${ACC.escapeHtml(tag)}: %{x:.1f}%<br><span style="font-size:10px">click for its papers →</span><extra></extra>` });
    Plotly.react(div, [
      { type: 'scatter', mode: 'lines', x: lx, y: ly, line: { color: p.line2, width: 2 }, hoverinfo: 'skip', showlegend: false },
      mk('a', cA, cohortLabel(A)), mk('b', cB, cohortLabel(B)),
    ], ACC.plBase({
      height: Math.max(280, r.length * 24 + 70), margin: { l: 200, r: 24, t: 8, b: 42 },
      xaxis: { title: { text: metricWord(), font: { size: 10.5, color: p.mut } }, gridcolor: p.line, rangemode: 'tozero', tickfont: { size: 9.5, color: p.fnt }, ticksuffix: '%' },
      yaxis: { tickfont: { size: 10.5, color: p.ink2 }, gridcolor: 'rgba(0,0,0,0)', automargin: true },
      legend: { orientation: 'h', y: -0.14, font: { size: 10.5, color: p.ink2 } }, hovermode: 'closest',
    }), ACC.plConfig({ displayModeBar: false }));
    div.on('plotly_click', ev => {
      const c = ev.points && ev.points[0] && ev.points[0].customdata;
      openClaims(c);
    });
  }

  function drawScatter(div, rows, cA, cB) {
    const p = ACC.pal();
    const mx = Math.max(1, ...rows.map(r => Math.max(r.a, r.b)));
    Plotly.react(div, [
      { type: 'scatter', mode: 'lines', x: [0, mx], y: [0, mx], line: { color: p.line2, width: 1, dash: 'dot' }, hoverinfo: 'skip', showlegend: false },
      { type: 'scatter', mode: 'markers+text', x: rows.map(r => r.a), y: rows.map(r => r.b),
        text: rows.map(r => r.label), textposition: 'top center', textfont: { size: 8.5, color: p.fnt },
        marker: { size: 9, color: rows.map(r => r.d >= 0 ? cA : cB), line: { width: 0.5, color: p.plot } },
        customdata: rows.map(r => r.c),
        hovertemplate: `<b>%{text}</b><br>${ACC.escapeHtml(cohortLabel(A))}: %{x:.1f}%25 · ${ACC.escapeHtml(cohortLabel(B))}: %{y:.1f}%25<br><span style="font-size:10px">click for its papers →</span><extra></extra>` },
    ], ACC.plBase({
      height: 440, margin: { l: 52, r: 20, t: 10, b: 46 },
      xaxis: { title: { text: cohortLabel(A) + ' · ' + metricWord(), font: { size: 10.5, color: p.mut } }, gridcolor: p.line, rangemode: 'tozero', tickfont: { size: 9.5, color: p.fnt }, ticksuffix: '%' },
      yaxis: { title: { text: cohortLabel(B) + ' · ' + metricWord(), font: { size: 10.5, color: p.mut } }, gridcolor: p.line, rangemode: 'tozero', tickfont: { size: 9.5, color: p.fnt }, ticksuffix: '%' },
      hovermode: 'closest', showlegend: false,
    }), ACC.plConfig({ displayModeBar: false }));
    div.on('plotly_click', ev => { const c = ev.points[0].customdata; openClaims(c); });
  }

  function drawHeadlines(el, rows, cA, cB) {
    const aTop = rows.filter(r => r.d > 0).sort((x, y) => y.d - x.d).slice(0, 4);
    const bTop = rows.filter(r => r.d < 0).sort((x, y) => x.d - y.d).slice(0, 4);
    const list = arr => arr.length ? arr.map(r => `<li>${ACC.escapeHtml(r.label)} <span class="cmp-pp">${ACC.fmtPp(r.d)}</span></li>`).join('') : '<li class="cmp-dim">—</li>';
    el.innerHTML =
      `<div class="cmp-col"><div class="cmp-col-h" style="color:${cA}">${ACC.escapeHtml(cohortLabel(A))} leans toward</div><ul>${list(aTop)}</ul></div>` +
      `<div class="cmp-col"><div class="cmp-col-h" style="color:${cB}">${ACC.escapeHtml(cohortLabel(B))} leans toward</div><ul>${list(bTop)}</ul></div>`;
  }

  /* -- single-subsample drift over years --------------------------------- */
  function drawDrift(cohorts) {
    const host = document.getElementById('profile-panels');
    host.innerHTML = '';
    host.style.display = 'flex'; host.style.flexDirection = 'column'; host.style.gap = '10px';
    if (!cohorts.length) { host.innerHTML = '<div class="cmp-empty">Pick a subsample to see how it drifts over the years.</div>'; return; }
    const bar = document.createElement('div'); bar.className = 'panel-modes';
    bar.innerHTML = '<span class="ctl-label">DRIFT AS</span>';
    bar.appendChild(modeSeg(driftMode, [['bump', 'Bump chart'], ['stacked', 'Stacked area']],
      v => { driftMode = v; draw(); }));
    host.appendChild(bar);
    const grid = document.createElement('div'); grid.className = 'panel-grid';
    grid.style.gridTemplateColumns = cohorts.length === 2 ? '1fr 1fr' : '1fr';
    host.appendChild(grid);
    cohorts.forEach((cohort, k) => {
      const panel = document.createElement('div');
      panel.className = 'profile-panel';
      panel.innerHTML = `<div class="panel-h"><span class="panel-tag" style="background:${cohortColor(cohort)}">${k === 0 ? 'A' : 'B'}</span>` +
        `<span class="panel-ttl">${ACC.escapeHtml(cohortLabel(cohort))} · drift over ${windowLabel(cohort)}</span></div><div class="panel-plot"></div>`;
      grid.appendChild(panel);
      (driftMode === 'bump' ? drawBump : drawDriftPlot)(panel.querySelector('.panel-plot'), cohort);
    });
  }

  /* -- bump chart: how the top topics' RANKS move year to year ----------- */
  function drawBump(div, cohort) {
    const years = cohortYearList(cohort);
    const prof = years.map(y => profileAt(cohort, y));
    const perYear = prof.map(pp => pp.byCluster);
    const covered = prof.map(pp => pp.nPapers > 0);   // years the cohort actually ran
    const totals = new Map();
    perYear.forEach(mp => mp.forEach((v, c) => totals.set(c, (totals.get(c) || 0) + v)));
    if (!totals.size) { div.innerHTML = '<div class="cmp-empty">No claims in this subsample.</div>'; return; }
    const top = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, TOP_DRIFT).map(e => e[0]);
    const rankByYear = perYear.map(mp => {
      const rk = new Map();
      [...mp.entries()].sort((a, b) => b[1] - a[1]).forEach(([c], i) => rk.set(c, i + 1));
      return rk;
    });
    let maxRank = 1;
    top.forEach(c => years.forEach((_, i) => { const r = rankByYear[i].get(c); if (r) maxRank = Math.max(maxRank, r); }));
    // Label only real ranks (1..maxRank) — the single minimal tweak vs. the
    // original bump styling, so an autoranged axis never prints a 0/negative tick.
    const rankTicks = [];
    for (let r = 1; r <= maxRank; r++) rankTicks.push(r);
    const p = ACC.pal();
    // Solid between consecutive years; dashed ONLY across years the cohort didn't
    // run (e.g. a biennial venue), not across the whole line.
    const traces = [];
    top.forEach(c => {
      const color = ACC.clusterColor(ACC.state.clusterById.get(c) || { id: c });
      const yy = years.map((_, i) => rankByYear[i].get(c) || null);
      const g = ACC.gapBridge(years, yy, covered);
      traces.push({
        type: 'scatter', mode: 'lines+markers', x: years, connectgaps: false, y: yy,
        name: clusterLabel(c), customdata: years.map(() => c),
        line: { width: 2.4, shape: 'spline', color }, marker: { size: 7 },
        hovertemplate: `<b>${clusterLabel(c)}</b><br>%{x}: rank %{y}<br><span style="font-size:10px">click for its papers →</span><extra></extra>`,
      });
      const bridge = (bx, by, dash) => traces.push({
        type: 'scatter', mode: 'lines', x: bx, y: by, connectgaps: false,
        customdata: bx.map(() => c),
        line: { width: 2.4, shape: 'spline', dash, color }, showlegend: false,
        hovertemplate: `<b>${clusterLabel(c)}</b><br>%{x}: rank %{y}<extra></extra>`,
      });
      if (g.solidX.length) bridge(g.solidX, g.solidY, undefined);
      if (g.dashX.length) bridge(g.dashX, g.dashY, 'dot');
    });
    Plotly.react(div, traces, ACC.plBase({
      height: 380, margin: { l: 40, r: 150, t: 8, b: 30 },
      xaxis: { tickvals: years, tickfont: { size: 11, color: p.fnt }, gridcolor: p.line },
      // original autoranged reversed axis + default spline smoothing; only tickvals
      // (not dtick:1) differ, so a 0/negative rank is never labelled while the
      // spline can still overshoot freely (no clipping).
      yaxis: { title: { text: 'rank (1 = most common)', font: { size: 10, color: p.mut } },
               autorange: 'reversed', tickmode: 'array', tickvals: rankTicks,
               tickfont: { size: 10, color: p.fnt }, gridcolor: p.line },
      showlegend: true, legend: { font: { size: 9.5, color: p.ink2 }, x: 1.02, y: 1, xanchor: 'left' },
      hovermode: 'closest',
    }), ACC.plConfig({ displayModeBar: false }));
    div.on('plotly_click', ev => {
      const pt = ev.points && ev.points[0];
      if (!pt) return;
      // a bump point IS a (cluster, year) — show that year's claims specifically
      openClaims(pt.customdata, { tag: cohortTag(cohort), year: typeof pt.x === 'number' ? pt.x : +pt.x });
    });
  }

  function drawDriftPlot(div, cohort) {
    const yearsFull = cohortYearList(cohort);
    const profFull = yearsFull.map(y => profileAt(cohort, y));
    const coveredFull = profFull.map(pp => pp.nPapers > 0);
    const firstC = coveredFull.indexOf(true), lastC = coveredFull.lastIndexOf(true);
    if (firstC < 0) { div.innerHTML = '<div class="cmp-empty">No claims in this subsample.</div>'; return; }
    // trim leading/trailing years the cohort never covered (e.g. EMNLP has no 2026)
    const years = yearsFull.slice(firstC, lastC + 1);
    const prof = profFull.slice(firstC, lastC + 1);
    const covered = coveredFull.slice(firstC, lastC + 1);
    const perYear = prof.map(pp => pp.byCluster);
    const totals = new Map();
    perYear.forEach(mp => mp.forEach((v, c) => totals.set(c, (totals.get(c) || 0) + v)));
    if (!totals.size) { div.innerHTML = '<div class="cmp-empty">No claims in this subsample.</div>'; return; }
    const top = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, TOP_DRIFT).map(e => e[0]);
    const p = ACC.pal();
    const color = c => ACC.clusterColor(ACC.state.clusterById.get(c) || { id: c });
    const traces = [];
    if (metric === 'mix') {
      // topic mix is additive → a real filled stacked area. Plot only the covered
      // years so the fill stays continuous (it bridges any gap year linearly) and
      // never degrades into an unreadable pile of lines; hover the band for names.
      const ci = years.map((_, i) => i).filter(i => covered[i]);
      const cyears = ci.map(i => years[i]);
      top.forEach(c => traces.push({
        type: 'scatter', mode: 'lines', x: cyears, y: ci.map(i => +(perYear[i].get(c) || 0).toFixed(2)),
        connectgaps: true, name: clusterLabel(c), text: clusterLabel(c), customdata: cyears.map(() => c),
        hoveron: 'points+fills', line: { width: 0.5, color: color(c) }, stackgroup: 'one',
        hovertemplate: `<b>%{text}</b><br>%{x}: %{y:.1f}%<extra></extra>`,
      }));
    } else {
      // paper share is NOT additive (a paper can sit in several clusters) → stacking
      // would mislead. Readable lines+markers, dashed only across years the cohort
      // didn't run, and every segment carries its name so hover always labels it.
      top.forEach(c => {
        const col = color(c);
        const yy = years.map((_, i) => prof[i].nPapers ? +(perYear[i].get(c) || 0).toFixed(2) : null);
        const g = ACC.gapBridge(years, yy, covered);
        traces.push({
          type: 'scatter', mode: 'lines+markers', x: years, y: yy, connectgaps: false,
          name: clusterLabel(c), customdata: years.map(() => c),
          line: { width: 2.2, color: col }, marker: { size: 5, color: col },
          hovertemplate: `<b>${clusterLabel(c)}</b><br>%{x}: %{y:.1f}%<extra></extra>`,
        });
        const bridge = (bx, by, dash) => traces.push({
          type: 'scatter', mode: 'lines', x: bx, y: by, connectgaps: false,
          customdata: bx.map(() => c), line: { width: 2.2, dash, color: col },
          showlegend: false, hoverinfo: 'skip',   // visual connector; the base line carries hover
        });
        if (g.solidX.length) bridge(g.solidX, g.solidY, undefined);
        if (g.dashX.length) bridge(g.dashX, g.dashY, 'dot');
      });
    }
    Plotly.react(div, traces, ACC.plBase({
      height: 360, margin: { l: 46, r: 10, t: 8, b: 34 },
      xaxis: { tickvals: years, tickfont: { size: 11, color: p.fnt }, gridcolor: p.line },
      yaxis: { title: { text: metricWord(), font: { size: 11, color: p.mut } }, rangemode: 'tozero', tickfont: { size: 10, color: p.fnt }, gridcolor: p.line },
      legend: { orientation: 'h', y: -0.14, font: { size: 10, color: p.ink2 } },
      hovermode: 'closest',
      // paper-share lines aren't stacked, so make every line hoverable anywhere
      // (not just at vertices); the filled topic-mix relies on fill hover instead.
      hoverdistance: metric === 'mix' ? 20 : -1,
    }), ACC.plConfig({ displayModeBar: false }));
    div.on('plotly_click', ev => {
      const c = ev.points && ev.points[0] && ev.points[0].customdata;
      openClaims(c, { tag: cohortTag(cohort) });
    });
  }

  /* ------------------------- claims drawer (links) ---------------------- */
  // Point indices of a cluster's claims *within a cohort* (its predicate + its
  // effective year window), newest first.
  function claimsFor(cid, cohort, year) {
    const pred = predicate(cohort);
    if (!pred) return [];
    let yrs = effYears(cohort);
    if (year != null) yrs = yrs.includes(year) ? [year] : [];   // single-year (bump click)
    const yset = new Set(yrs);
    const out = [];
    for (const cl of claims) {
      if (cl.c !== cid || !yset.has(cl.y) || !pred(cl)) continue;
      out.push(cl.i);
    }
    const yr = ACC.state.data.points.year;
    out.sort((a, b) => yr[b] - yr[a]);
    return out;
  }

  function activeClaimCohorts() {
    return [['A', A], ['B', B]].filter(([, c]) => isSet(c));
  }

  // opts: { tag: 'A'|'B' (cohort the clicked mark belongs to), year: <number> (bump click) }
  function openClaims(cid, opts) {
    opts = opts || {};
    if (typeof cid !== 'number' || cid < 0) return;
    const act = activeClaimCohorts();
    if (!act.length) return;
    drawerCid = cid;
    drawerShown = DRAWER_PAGE;
    drawerQuery = '';
    drawerYear = (opts.year != null) ? opts.year : null;
    clearTimeout(drawerFilterTimer);   // drop a debounce still pending from a prior keystroke
    const filt = document.getElementById('cmp-drawer-filter');
    if (filt) filt.value = '';
    // default tab: the clicked mark's own cohort, else the side with more claims
    if (opts.tag && act.some(([t]) => t === opts.tag)) drawerTab = opts.tag;
    else if (act.length === 2) drawerTab = claimsFor(cid, B, drawerYear).length > claimsFor(cid, A, drawerYear).length ? 'B' : 'A';
    else drawerTab = act[0][0];
    renderDrawer();
    document.getElementById('cmp-drawer').classList.add('open');
    syncCompareLayout(true);
  }

  function closeDrawer() {
    const dr = document.getElementById('cmp-drawer');
    if (dr) dr.classList.remove('open');
    clearTimeout(drawerFilterTimer);
    drawerCid = null;
    drawerYear = null;
    drawerQuery = '';
    const filt = document.getElementById('cmp-drawer-filter');
    if (filt) filt.value = '';
    syncCompareLayout(false);
  }

  // Wide screens: slide the Compare content aside so the drawer never covers it
  // (below the breakpoint the drawer overlays and a click-outside dismisses it).
  function syncCompareLayout(open) {
    const view = document.getElementById('view-compare');
    if (!view) return;
    const was = view.classList.contains('drawer-open');
    view.classList.toggle('drawer-open', open);
    if (was !== open) setTimeout(() => {
      document.querySelectorAll('#view-compare .js-plotly-plot').forEach(d => { if (d.data) Plotly.Plots.resize(d); });
    }, 260);
  }

  // If cohorts/metric/scope changed while the drawer is open, keep it in sync.
  function refreshDrawer() {
    const dr = document.getElementById('cmp-drawer');
    if (!dr || drawerCid == null || !dr.classList.contains('open')) return;
    renderDrawer();
  }

  function renderDrawer() {
    const dr = document.getElementById('cmp-drawer');
    if (!dr || drawerCid == null) return;
    const act = activeClaimCohorts();
    if (!act.length) { closeDrawer(); return; }
    if (!act.some(([tag]) => tag === drawerTab)) drawerTab = act[0][0];

    const cid = drawerCid;
    document.getElementById('cmp-drawer-ttl').innerHTML =
      `<span class="cmp-drawer-dot" style="background:${ACC.clusterColor(ACC.state.clusterById.get(cid) || { id: cid })}"></span>` +
      ACC.escapeHtml(clusterLabel(cid));
    const cohort = drawerTab === 'A' ? A : B;
    document.getElementById('cmp-drawer-sub').innerHTML =
      `in <b>${ACC.escapeHtml(cohortLabel(cohort))}</b> · ${drawerYear != null ? drawerYear : windowLabel(cohort)}`;

    const tabsEl = document.getElementById('cmp-drawer-tabs');
    tabsEl.innerHTML = '';
    if (act.length === 2) {
      act.forEach(([tag, c]) => {
        const n = claimsFor(cid, c, drawerYear).length;
        const b = document.createElement('button');
        b.className = 'year-tab' + (tag === drawerTab ? ' active' : '');
        b.innerHTML = `<span class="cmp-tab-tag" style="background:${cohortColor(c)}">${tag}</span> ` +
          `${ACC.escapeHtml(cohortLabel(c))} <span class="cmp-tab-n">${n}</span>`;
        b.addEventListener('click', () => { drawerTab = tag; drawerShown = DRAWER_PAGE; renderDrawer(); });
        tabsEl.appendChild(b);
      });
      tabsEl.style.display = '';
    } else {
      tabsEl.style.display = 'none';
    }

    renderDrawerList();

    const foot = document.getElementById('cmp-drawer-foot');
    foot.innerHTML = '';
    const full = document.createElement('button');
    full.className = 'btn-outline';
    full.textContent = 'Open full cluster ↗';
    full.title = 'See this cluster across all sources and years, with CSV export';
    full.addEventListener('click', () => ACC.emit('open-cluster', cid));
    foot.appendChild(full);
  }

  function renderDrawerList() {
    const listEl = document.getElementById('cmp-drawer-list');
    const cohort = drawerTab === 'A' ? A : B;
    const pts = ACC.state.data.points, titles = ACC.state.data.titles, papers = ACC.state.data.papers;
    let idx = claimsFor(drawerCid, cohort, drawerYear);
    const total = idx.length;
    if (drawerQuery) idx = idx.filter(i => pts.claim[i].toLowerCase().includes(drawerQuery));
    listEl.innerHTML = '';

    const count = document.createElement('div');
    count.className = 'cmp-drawer-count';
    count.textContent = drawerQuery
      ? `${idx.length} of ${total} claims match`
      : `${total} claim${total === 1 ? '' : 's'} from this subsample${drawerYear != null ? ' · ' + drawerYear : ''}`;
    listEl.appendChild(count);

    if (!idx.length) {
      const empty = document.createElement('div');
      empty.className = 'cmp-empty';
      empty.style.padding = '24px 0';
      empty.textContent = total
        ? 'No claims match that filter.'
        : 'This subsample has no claims in this cluster' + (drawerYear != null ? ' in ' + drawerYear : '') + '.';
      listEl.appendChild(empty);
      return;
    }

    const srcs = ACC.state.data.sources || [], psrc = pts.source || [];
    for (const i of idx.slice(0, drawerShown)) {
      const s = srcs[psrc[i]] || {};
      const url = ACC.state.data.meta.anthologyBase + papers[pts.paper[i]];
      const vchip = s.venue
        ? `<span class="claim-venue" style="color:${s.color};border-color:${s.color}">${ACC.escapeHtml(s.venue)}</span> ` : '';
      const row = document.createElement('div');
      row.className = 'claim-row';
      row.innerHTML = ACC.escapeHtml(pts.claim[i]) +
        `<div class="claim-src">${vchip}<span class="yr">${pts.year[i]}</span> · ` +
        `<a href="${url}" target="_blank" rel="noopener">${ACC.escapeHtml(titles[pts.paper[i]] || 'source paper')} ↗</a></div>`;
      listEl.appendChild(row);
    }
    if (idx.length > drawerShown) {
      const more = document.createElement('button');
      more.className = 'btn-outline cmp-drawer-more';
      more.textContent = `Show more (${idx.length - drawerShown} left)`;
      more.addEventListener('click', () => { drawerShown += DRAWER_PAGE * 2; renderDrawerList(); });
      listEl.appendChild(more);
    }
  }

  /* --------------------------- controls UI ------------------------------ */
  function cohortControl(side) {
    const cohort = side === 'A' ? A : B;
    // patch-merge so year range survives type/value switches
    const set = patch => {
      const cur = side === 'A' ? A : B;
      const next = Object.assign({}, cur, patch);
      if (side === 'A') A = next; else B = next;
      draw(); renderControls();
    };
    const wrap = document.createElement('div');
    wrap.className = 'cohort-card';
    wrap.style.borderColor = isSet(cohort) ? cohortColor(cohort) : 'var(--line2)';

    const types = side === 'A'
      ? [['venue', 'Conference'], ['author', 'Author'], ['keyword', 'Keyword']]
      : [['none', '— none —'], ['venue', 'Conference'], ['author', 'Author'], ['keyword', 'Keyword']];
    const typeSel = document.createElement('select');
    typeSel.className = 'select';
    types.forEach(([v, lab]) => { const o = document.createElement('option'); o.value = v; o.textContent = lab; if (cohort.type === v) o.selected = true; typeSel.appendChild(o); });
    typeSel.addEventListener('change', () => {
      const t = typeSel.value;
      set({ type: t, value: t === 'venue' ? venues()[0] : '' });
    });

    const head = document.createElement('div');
    head.className = 'cohort-head';
    head.innerHTML = `<span class="cohort-tag" style="background:${isSet(cohort) ? cohortColor(cohort) : 'var(--fnt2)'}">${side}</span>`;
    head.appendChild(typeSel);
    wrap.appendChild(head);

    const val = document.createElement('div');
    val.className = 'cohort-val';
    if (cohort.type === 'venue') {
      const sel = document.createElement('select'); sel.className = 'select';
      venues().forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; if (cohort.value === v) o.selected = true; sel.appendChild(o); });
      sel.addEventListener('change', () => set({ type: 'venue', value: sel.value }));
      val.appendChild(sel);
    } else if (cohort.type === 'author') {
      const inp = document.createElement('input'); inp.className = 'field'; inp.setAttribute('list', 'cmp-authors'); inp.placeholder = 'Type an author name…';
      const idx = ACC.state.data.authorsIndex || {};
      if (cohort.value && idx[cohort.value]) inp.value = idx[cohort.value][0];
      inp.addEventListener('change', () => set({ type: 'author', value: nameToId[inp.value.trim()] || '' }));
      val.appendChild(inp);
      const quick = document.createElement('div'); quick.className = 'cohort-quick';
      [['christopher-d-manning', 'Manning'], ['hinrich-schutze', 'Schütze'], ['dan-jurafsky', 'Jurafsky']].forEach(([id, nm]) => {
        if (!idx[id]) return;
        const b = document.createElement('button'); b.className = 'chip-btn'; b.textContent = nm;
        b.addEventListener('click', () => set({ type: 'author', value: id }));
        quick.appendChild(b);
      });
      val.appendChild(quick);
    } else if (cohort.type === 'keyword') {
      const inp = document.createElement('input'); inp.className = 'field'; inp.placeholder = 'words, comma or space separated…'; inp.value = cohort.value || '';
      inp.addEventListener('change', () => set({ type: 'keyword', value: inp.value }));
      val.appendChild(inp);
    } else {
      val.innerHTML = '<span class="cohort-none">no second subsample — showing A only</span>';
    }
    wrap.appendChild(val);

    // per-cohort year range — applies to any subsample type (venue/author/keyword)
    if (cohort.type !== 'none') {
      const [lo, hi] = cohortRange(cohort);
      const yr = document.createElement('div'); yr.className = 'cohort-years';
      const lab = document.createElement('span'); lab.className = 'cohort-years-lab'; lab.textContent = 'YEARS';
      const mkSel = which => {
        const s = document.createElement('select'); s.className = 'select';
        allYears().forEach(y => { const o = document.createElement('option'); o.value = y; o.textContent = y; if (y === (which === 'from' ? lo : hi)) o.selected = true; s.appendChild(o); });
        s.addEventListener('change', () => {
          const [clo, chi] = cohortRange(cohort);
          let ny0 = which === 'from' ? +s.value : clo;
          let ny1 = which === 'to' ? +s.value : chi;
          if (ny0 > ny1) { if (which === 'from') ny1 = ny0; else ny0 = ny1; }   // keep from ≤ to
          set({ y0: ny0, y1: ny1 });
        });
        return s;
      };
      const dash = document.createElement('span'); dash.className = 'cohort-years-dash'; dash.textContent = '–';
      yr.appendChild(lab); yr.appendChild(mkSel('from')); yr.appendChild(dash); yr.appendChild(mkSel('to'));
      wrap.appendChild(yr);
    }
    return wrap;
  }

  function renderControls() {
    const row = document.getElementById('cohort-row');
    if (!row) return;
    row.innerHTML = '';
    row.appendChild(cohortControl('A'));
    const vs = document.createElement('div'); vs.className = 'cohort-vs'; vs.textContent = 'vs';
    row.appendChild(vs);
    row.appendChild(cohortControl('B'));
  }

  function build() {
    if (built) return;
    built = true;
    claims = buildClaims();
    const vs = venues();
    A = { type: 'venue', value: vs.find(v => v !== 'EMNLP') || vs[0] };
    B = { type: 'venue', value: 'EMNLP' };

    const yearOpts = ['ALL', ...allYears()].map(y =>
      `<option value="${y}">${y === 'ALL' ? 'all years' : y}</option>`).join('');

    document.getElementById('compare-body').innerHTML = `
      <div class="compare-head">
        <div class="compare-eyebrow">COMPARE</div>
        <h1 class="compare-h1">Thematic profiles of subsamples</h1>
        <p class="compare-lead">Pick a subsample — a conference, an author, or a keyword set — and optionally narrow it to a range of years. Add a second to compare them directly, or switch to <i>over time</i> to watch one subsample drift across the years. Click any topic in a chart to read its actual claims, each linking to the source paper.</p>
      </div>
      <div class="cohort-row" id="cohort-row"></div>
      <div class="compare-opts">
        <span class="ctl-label">MEASURE</span>
        <div class="seg" id="cmp-metric">
          <button class="seg-btn active" data-m="mix">topic mix</button>
          <button class="seg-btn" data-m="df">paper share</button>
        </div>
        <span class="ctl-divider"></span>
        <span class="ctl-label">VIEW</span>
        <div class="seg" id="cmp-view">
          <button class="seg-btn active" data-view="snapshot">Snapshot</button>
          <button class="seg-btn" data-view="overtime">Over time</button>
        </div>
        <span class="ctl-label">YEAR</span>
        <select class="select" id="cmp-year" title="Global year filter — intersected with each subsample's own year range">${yearOpts}</select>
      </div>
      <div class="compare-summary" id="compare-summary"></div>
      <div class="compare-versus" id="compare-versus"></div>
      <div class="profile-panels" id="profile-panels"></div>
      <datalist id="cmp-authors"></datalist>

      <aside class="cmp-drawer" id="cmp-drawer">
        <div class="cmp-drawer-head">
          <div class="cmp-drawer-titles">
            <div class="cmp-drawer-ttl" id="cmp-drawer-ttl"></div>
            <div class="cmp-drawer-sub" id="cmp-drawer-sub"></div>
          </div>
          <button class="cmp-drawer-x" id="cmp-drawer-x" title="Close (Esc)" aria-label="Close">✕</button>
        </div>
        <div class="cmp-drawer-tabs" id="cmp-drawer-tabs"></div>
        <div class="cmp-drawer-tools">
          <input type="text" class="field" id="cmp-drawer-filter" placeholder="Filter these claims…">
        </div>
        <div class="cmp-drawer-list" id="cmp-drawer-list"></div>
        <div class="cmp-drawer-foot" id="cmp-drawer-foot"></div>
      </aside>`;

    const dl = document.getElementById('cmp-authors');
    Object.values(ACC.state.data.authorsIndex || {}).sort((a, b) => b[1] - a[1]).forEach(([nm, n]) => {
      const o = document.createElement('option'); o.value = nm; o.label = n + ' papers'; dl.appendChild(o);
    });

    document.querySelectorAll('#cmp-metric .seg-btn').forEach(b =>
      b.addEventListener('click', () => {
        metric = b.dataset.m;
        document.querySelectorAll('#cmp-metric .seg-btn').forEach(x => x.classList.toggle('active', x === b));
        draw();
      }));
    const yearSel = document.getElementById('cmp-year');
    document.querySelectorAll('#cmp-view .seg-btn').forEach(b =>
      b.addEventListener('click', () => {
        document.querySelectorAll('#cmp-view .seg-btn').forEach(x => x.classList.toggle('active', x === b));
        const overtime = b.dataset.view === 'overtime';
        yearSel.style.display = overtime ? 'none' : '';
        scope = overtime ? 'overtime' : (yearSel.value === 'ALL' ? 'ALL' : +yearSel.value);
        draw();
      }));
    yearSel.addEventListener('change', () => {
      scope = yearSel.value === 'ALL' ? 'ALL' : +yearSel.value;
      draw();
    });

    // drawer wiring
    document.getElementById('cmp-drawer-x').addEventListener('click', closeDrawer);
    document.getElementById('cmp-drawer-filter').addEventListener('input', e => {
      const v = e.target.value;
      clearTimeout(drawerFilterTimer);
      drawerFilterTimer = setTimeout(() => { drawerQuery = v.trim().toLowerCase(); drawerShown = DRAWER_PAGE; renderDrawerList(); }, 160);
    });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && drawerCid != null) closeDrawer();
    });
    // click anywhere outside the drawer dismisses it — except on a chart mark,
    // whose own handler re-opens/updates the drawer (so no close→reopen flicker).
    document.addEventListener('mousedown', e => {
      const dr = document.getElementById('cmp-drawer');
      if (!dr || !dr.classList.contains('open')) return;
      if (dr.contains(e.target)) return;
      if (e.target.closest && e.target.closest('.js-plotly-plot')) return;
      closeDrawer();
    });

    renderControls();
    draw();
  }

  function activate() {
    build();
    document.querySelectorAll('#view-compare .js-plotly-plot').forEach(d => { if (d.data) Plotly.Plots.resize(d); });
  }
  function rebuildTheme() { if (built) { renderControls(); draw(); } }

  // Claim texts + author tables arrived (split payload): rebuild the claim
  // stream (keyword/author cohorts depend on it), refill the author
  // autocomplete, and redraw whatever is on screen.
  ACC.on('claims-ready', () => {
    if (!built) return;
    claims = buildClaims();
    const dl = document.getElementById('cmp-authors');
    if (dl) {
      dl.innerHTML = '';
      Object.values(ACC.state.data.authorsIndex || {}).sort((a, b) => b[1] - a[1]).forEach(([nm, n]) => {
        const o = document.createElement('option'); o.value = nm; o.label = n + ' papers'; dl.appendChild(o);
      });
    }
    renderControls();
    draw();
  });

  return { activate, rebuildTheme };
})();
