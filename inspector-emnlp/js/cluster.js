/* ==========================================================================
   cluster.js — Clusters view: one cluster in depth (v5 design).
   Sidebar list + detail with badges, DF-by-year bars, position minimap, and
   all claims with per-year tabs, filter, paging, and CSV export.
   ========================================================================== */
'use strict';

window.ClusterView = (function () {
  let built = false;
  let currentCid = null;
  let currentYear = 'ALL';
  let claimsQuery = '';
  let claimsOrder = 'random';  // 'random' (default, unbiased sample) | 'new' (newest first)
  let shuffleSeed = 1;
  let claimsShown = 12;
  const CLAIMS_PAGE = 12;

  /* --------------------------- cluster list ----------------------------- */
  function listItem(c, extraStyle) {
    const item = document.createElement('div');
    item.className = 'legend-item' + (c.id === currentCid ? ' selected' : '');
    if (extraStyle) item.style.cssText = extraStyle;
    item.innerHTML =
      `<span class="legend-dot" style="background:${ACC.clusterColor(c)}"></span>` +
      `<span class="legend-name">${ACC.escapeHtml(c.label)}</span>` +
      `<span class="legend-arrow ${c.deltaPp >= 0 ? 'up' : 'down'}">${ACC.trendArrow(c)}</span>` +
      `<span class="legend-count">${c.size.toLocaleString()}</span>`;
    item.addEventListener('click', () => show(c.id));
    return item;
  }

  function renderList() {
    const list = document.getElementById('cluster-list');
    const cf = document.getElementById('cluster-filter').value.trim().toLowerCase();
    list.innerHTML = '';
    for (const c of ACC.state.sorted) {
      if (cf && !(c.label + ' ' + c.raw).toLowerCase().includes(cf)) continue;
      list.appendChild(listItem(c));
    }
    const nc = ACC.state.noiseCluster;
    if (nc && (!cf || ('unclustered noise ' + nc.label).toLowerCase().includes(cf))) {
      list.appendChild(listItem(nc, 'border-top:1px solid var(--line);margin-top:6px;padding-top:9px'));
    }
  }

  /* ------------------------------ detail -------------------------------- */
  function show(cid) {
    currentCid = cid;
    currentYear = 'ALL';
    claimsQuery = '';
    claimsOrder = 'random';
    shuffleSeed = (Math.random() * 2 ** 32) >>> 0;   // fresh unbiased order on each open
    claimsShown = CLAIMS_PAGE;
    renderList();
    const c = ACC.state.clusterById.get(cid);
    const isNoise = cid === -1;
    const years = ACC.state.data.meta.years;
    const dir = c.deltaPp >= 0 ? 'up-c' : 'down-c';
    const badge = (k, v, cls) => `<span class="badge">${k} <b class="${cls || ''}">${v}</b></span>`;
    const subtitle = isNoise
      ? '<div class="detail-raw">one-off claims that didn’t fit any cluster</div>'
      : `<div class="detail-raw">Key terms · ${ACC.escapeHtml(c.tfidfFull || c.raw)}</div>`;
    const detail = document.getElementById('cluster-detail');
    detail.innerHTML = `
      <div class="detail-wrap">
        <div class="detail-head">
          <div class="detail-title-row">
            <span class="detail-dot" style="background:${ACC.clusterColor(c)}"></span>
            <span class="detail-title">${ACC.escapeHtml(c.labelFull || c.label)}</span>
          </div>
          ${subtitle}
          <div class="detail-badges">
            ${badge('claims', c.size.toLocaleString())}
            ${badge('papers', c.papers.toLocaleString())}
            ${badge(years[0] + ' share', ACC.fmtPct(c.df[0]))}
            ${badge(years[years.length - 1] + ' share', ACC.fmtPct(c.df[c.df.length - 1]))}
            ${badge('Δ', ACC.fmtPp(c.deltaPp) + ' (' + ACC.fmtRel(c) + ')', dir)}
            <span style="flex:1"></span>
            <button class="btn-outline" id="detail-show-map">Show on map</button>
            <button class="btn-outline" id="detail-export" title="Download all claims of this cluster with paper links">Export CSV</button>
          </div>
        </div>
        <div class="detail-charts">
          <div class="detail-card">
            <div class="detail-card-title">Share of papers by year</div>
            <div id="detail-bars"></div>
          </div>
          <div class="detail-card">
            <div class="detail-card-title">Position on the map</div>
            <div id="detail-minimap"></div>
          </div>
        </div>
        <div class="detail-card detail-card-wide" id="detail-byconf-card">
          <div class="detail-card-title">By conference — where this topic lives</div>
          <div class="byconf-summary" id="detail-byconf-summary"></div>
          <div id="detail-byconf"></div>
        </div>
        <div class="claims-card">
          <div class="claims-head">
            <span class="ttl">Claims</span>
            <select class="select" id="claims-order" title="Order of the claim list">
              <option value="new">newest first</option>
              <option value="random">random order</option>
            </select>
            <button class="link" id="claims-reshuffle" hidden title="Draw a new random order">↻ reshuffle</button>
            <input type="text" class="field" id="claims-filter" placeholder="Filter claims…" style="margin-left:auto;width:220px">
          </div>
          <div class="year-tabs" id="claims-year-tabs"></div>
          <div class="claims-list" id="claims-list"></div>
        </div>
      </div>`;

    document.getElementById('detail-show-map').addEventListener('click', () => {
      MapView.isolate(cid);
      ACC.emit('switch-view', 'map');
    });
    document.getElementById('detail-export').addEventListener('click', () => exportCsv(c));
    const orderSel = document.getElementById('claims-order');
    const reshuffle = document.getElementById('claims-reshuffle');
    orderSel.value = claimsOrder;
    reshuffle.hidden = claimsOrder !== 'random';
    orderSel.addEventListener('change', () => {
      claimsOrder = orderSel.value;
      reshuffle.hidden = claimsOrder !== 'random';
      if (claimsOrder === 'random') shuffleSeed = (Math.random() * 2 ** 32) >>> 0;
      claimsShown = CLAIMS_PAGE;
      buildClaims(c);
    });
    reshuffle.addEventListener('click', () => {
      shuffleSeed = (Math.random() * 2 ** 32) >>> 0;
      claimsShown = CLAIMS_PAGE;
      buildClaims(c);
    });
    let timer = null;
    document.getElementById('claims-filter').addEventListener('input', e => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        claimsQuery = e.target.value.trim().toLowerCase();
        claimsShown = CLAIMS_PAGE;
        buildClaims(c);
      }, 200);
    });

    drawBars(c, years);
    drawMinimap(c);
    drawByConference(c);
    buildClaims(c);
  }

  /* -------------------------- by-conference ----------------------------- */
  // For the selected cluster, split its prevalence by source (venue): each
  // venue's share of ITS OWN papers that fall in this cluster, per year — so a
  // topic that is big in ACL but small in EMNLP reads correctly (not confounded
  // by the venues' different sizes).
  function venueBreakdown(cid) {
    const d = ACC.state.data, P = d.points, srcs = d.sources || [], years = d.meta.years;
    const yi = new Map(years.map((y, k) => [y, k]));
    const per = srcs.map(() => ({ papers: years.map(() => new Set()), claims: years.map(() => 0) }));
    const src = P.source || [];
    for (let i = 0; i < P.x.length; i++) {
      if (P.cluster[i] !== cid) continue;
      const si = src[i], k = yi.get(P.year[i]);
      if (si == null || k === undefined || !per[si]) continue;
      per[si].claims[k]++; per[si].papers[k].add(P.paper[i]);
    }
    return srcs.map((s, si) => {
      const ppy = s.papersPerYear || years.map(() => 0);
      const papersByYear = per[si].papers.map(st => st.size);
      const df = years.map((_, k) => ppy[k] ? +(100 * papersByYear[k] / ppy[k]).toFixed(3) : null);
      const nPapers = papersByYear.reduce((a, b) => a + b, 0);
      const nClaims = per[si].claims.reduce((a, b) => a + b, 0);
      const overallDf = s.nPapers ? 100 * nPapers / s.nPapers : 0;   // share of the venue's papers
      return { venue: s.venue, color: s.color, df, papersByYear, nPapers, nClaims, overallDf };
    }).filter(v => v.nClaims > 0);
  }

  function drawByConference(c) {
    const years = ACC.state.data.meta.years, p = ACC.pal();
    const rows = venueBreakdown(c.id);
    const totalClaims = rows.reduce((a, r) => a + r.nClaims, 0) || 1;
    // per-venue summary chips: composition (% of the cluster) + prevalence (% of the venue)
    document.getElementById('detail-byconf-summary').innerHTML = rows.map(r =>
      `<span class="byconf-chip" style="border-left-color:${r.color}">` +
      `<span class="byconf-v" style="color:${r.color}">${ACC.escapeHtml(r.venue)}</span>` +
      `<b>${(r.nClaims / totalClaims * 100).toFixed(0)}%</b> of cluster · ` +
      `<b>${r.overallDf.toFixed(1)}%</b> of its papers · ${r.nClaims.toLocaleString()} claims</span>`).join('');
    // per-venue prevalence over years (share of each venue's papers in this cluster).
    // Solid between consecutive covered years; ONLY the connectors that bridge
    // years the venue didn't run (df === null) are dashed — not the whole line.
    const traces = [];
    rows.forEach(r => {
      const covered = r.df.map(v => v != null);
      const g = ACC.gapBridge(years, r.df, covered);
      traces.push({
        type: 'scatter', mode: 'lines+markers', x: years, y: r.df, name: r.venue,
        connectgaps: false,
        line: { width: 2.4, color: r.color },
        marker: { size: 6, color: r.color },
        customdata: r.papersByYear,
        hovertemplate: `<b>${ACC.escapeHtml(r.venue)}</b><br>%{x}: %{y:.1f}% of its papers · %{customdata} here<extra></extra>`,
      });
      if (g.dashX.length) traces.push({
        type: 'scatter', mode: 'lines', x: g.dashX, y: g.dashY, connectgaps: false,
        line: { width: 2.4, dash: 'dot', color: r.color }, hoverinfo: 'skip', showlegend: false,
      });
    });
    Plotly.react(document.getElementById('detail-byconf'), traces, ACC.plBase({
      height: 250, margin: { l: 44, r: 10, t: 8, b: 28 },
      xaxis: { tickvals: years, tickfont: { size: 11, color: p.fnt }, gridcolor: p.line },
      yaxis: { title: { text: '% of the venue’s papers', font: { size: 10.5, color: p.mut } },
               rangemode: 'tozero', tickfont: { size: 10, color: p.fnt }, gridcolor: p.line, zerolinecolor: p.line2 },
      legend: { orientation: 'h', y: -0.16, font: { size: 10.5, color: p.ink2 } }, hovermode: 'closest',
    }), ACC.plConfig({ displayModeBar: false }));
  }

  /* ------------------------------ charts -------------------------------- */
  function drawBars(c, years) {
    const p = ACC.pal();
    Plotly.react(document.getElementById('detail-bars'), [{
      type: 'bar', x: years.map(String), y: c.df,
      marker: { color: ACC.clusterColor(c), opacity: 0.85 },
      text: c.df.map(v => v.toFixed(1) + '%'),
      textposition: 'outside', textfont: { size: 11, color: p.mut },
      customdata: c.df.map((_, yi) => [c.papersByYear ? c.papersByYear[yi] : '–', c.claims[yi]]),
      hovertemplate: '%{x}: <b>%{customdata[0]} papers</b> · %{customdata[1]} claims<extra></extra>',
      cliponaxis: false,
    }], ACC.plBase({
      height: 270,
      margin: { l: 42, r: 6, t: 16, b: 28 },
      yaxis: { title: { text: '% of papers', font: { size: 11, color: p.mut } }, rangemode: 'tozero',
               tickfont: { size: 10, color: p.fnt }, gridcolor: p.line, zerolinecolor: p.line2 },
      xaxis: { tickfont: { size: 11, color: p.fnt } },
    }), ACC.plConfig());
  }

  function drawMinimap(c) {
    const p = ACC.pal();
    const pts = ACC.state.data.points;
    const bx = [], by = [], cx = [], cy = [];
    for (let i = 0; i < pts.x.length; i++) {
      if (pts.cluster[i] === c.id) { cx.push(pts.x[i]); cy.push(pts.y[i]); }
      else if (i % 2 === 0) { bx.push(pts.x[i]); by.push(pts.y[i]); }
    }
    Plotly.react(document.getElementById('detail-minimap'), [
      { type: 'scattergl', mode: 'markers', x: bx, y: by, hoverinfo: 'skip',
        marker: { size: 2, color: p.dark ? 'rgba(150,155,165,0.18)' : 'rgba(150,145,130,0.22)' } },
      { type: 'scattergl', mode: 'markers', x: cx, y: cy, hoverinfo: 'skip',
        marker: { size: 4.5, color: ACC.clusterColor(c), opacity: 0.9 } },
    ], ACC.plBase({
      height: 270,
      margin: { l: 4, r: 4, t: 4, b: 4 },
      xaxis: { visible: false }, yaxis: { visible: false }, showlegend: false,
    }), { responsive: true, displayModeBar: false, staticPlot: true });
  }

  /* ------------------------------ claims -------------------------------- */
  /** Seeded Fisher–Yates (mulberry32) — stable across "Show more" pages. */
  function shuffleIdx(arr, seed) {
    const a = arr.slice();
    let s = seed >>> 0;
    const rnd = () => {
      s = s + 0x6D2B79F5 | 0;
      let t = Math.imul(s ^ s >>> 15, 1 | s);
      t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
      return ((t ^ t >>> 14) >>> 0) / 4294967296;
    };
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(rnd() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }

  function clusterClaimIdx(c, year) {
    const pts = ACC.state.data.points;
    const idx = [];
    for (let i = 0; i < pts.x.length; i++) {
      if (pts.cluster[i] === c.id && (year === 'ALL' || pts.year[i] === year)) idx.push(i);
    }
    idx.sort((a, b) => pts.year[b] - pts.year[a]);
    return idx;
  }

  function buildClaims(c) {
    const years = ACC.state.data.meta.years;
    const tabs = document.getElementById('claims-year-tabs');
    tabs.innerHTML = '';
    const mk = (label, val) => {
      const b = document.createElement('button');
      b.className = 'year-tab' + (val === currentYear ? ' active' : '');
      b.textContent = label;
      b.addEventListener('click', () => { currentYear = val; claimsShown = CLAIMS_PAGE; buildClaims(c); });
      tabs.appendChild(b);
    };
    mk('All years', 'ALL');
    years.forEach((y, yi) => mk(`${y} (${c.claims[yi]})`, y));

    let idx = clusterClaimIdx(c, currentYear);
    const pts = ACC.state.data.points, titles = ACC.state.data.titles;
    if (claimsQuery) idx = idx.filter(i => pts.claim[i].toLowerCase().includes(claimsQuery));
    if (claimsOrder === 'random') idx = shuffleIdx(idx, shuffleSeed);

    const listEl = document.getElementById('claims-list');
    listEl.innerHTML = '';
    const srcs = ACC.state.data.sources || [], psrc = pts.source || [];
    for (const i of idx.slice(0, claimsShown)) {
      const div = document.createElement('div');
      div.className = 'claim-row';
      const s = srcs[psrc[i]] || {};
      const vchip = s.venue
        ? `<span class="claim-venue" style="color:${s.color};border-color:${s.color}">${ACC.escapeHtml(s.venue)}</span> ` : '';
      div.innerHTML = ACC.escapeHtml(pts.claim[i]) +
        `<div class="claim-src">${vchip}<span class="yr">${pts.year[i]}</span> · ` +
        `<a href="${ACC.paperUrl(pts.paper[i])}" target="_blank">${ACC.escapeHtml(titles[pts.paper[i]])}</a></div>`;
      listEl.appendChild(div);
    }
    if (idx.length > claimsShown) {
      const more = document.createElement('button');
      more.className = 'btn-outline';
      more.style.alignSelf = 'flex-start';
      more.textContent = `Show more (${idx.length - claimsShown} left)`;
      more.addEventListener('click', () => { claimsShown += CLAIMS_PAGE * 2; buildClaims(c); });
      listEl.appendChild(more);
    }
  }

  /* ------------------------------ export -------------------------------- */
  function exportCsv(c) {
    const pts = ACC.state.data.points, titles = ACC.state.data.titles, papers = ACC.state.data.papers;
    const esc = s => '"' + String(s).replace(/"/g, '""') + '"';
    const rows = ['claim,year,paper_id,title,url'];
    for (const i of clusterClaimIdx(c, 'ALL')) {
      rows.push([esc(pts.claim[i]), pts.year[i], papers[pts.paper[i]],
                 esc(titles[pts.paper[i]]), ACC.paperUrl(pts.paper[i])].join(','));
    }
    const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (c.id === -1 ? 'unclustered' : `cluster_${c.id}`) + '_claims.csv';
    a.click();
    URL.revokeObjectURL(a.href);
  }

  /* ------------------------------- public ------------------------------- */
  function build() {
    if (built) return;
    built = true;
    renderList();
    document.getElementById('cluster-filter').addEventListener('input', renderList);
  }
  function activate() { build(); }
  function open(cid) { build(); show(cid); }

  function rebuildTheme() {
    if (!built) return;
    renderList();
    if (currentCid !== null) show(currentCid);
  }

  // Claim texts arrived (split payload): refresh the open cluster's claim list.
  ACC.on('claims-ready', () => {
    if (built && currentCid !== null) show(currentCid);
  });

  return { activate, open, rebuildTheme };
})();
