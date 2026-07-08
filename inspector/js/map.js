/* ==========================================================================
   map.js — the Map view: WebGL scatter of all claims across sources.
   Every display source (jointly-clustered or overlaid) is an equal "layer":
   independently shown/hidden, coloured by cluster, hover-labelled by cluster,
   and optionally highlighted in its own colour. Cluster labels are layout
   annotations. Plotly.react rebuilds on every filter/colour/source/theme change
   (uirevision keeps the viewport unless Auto-fit is on).
   ========================================================================== */
'use strict';

window.MapView = (function () {
  let gd = null, wrap = null;
  let built = false;
  let showLabels = true, showNoise = true, autoFit = false;
  let searchQ = '';
  let pinEl = null;
  let visibleSources = null;            // Set of source ids drawn on the map
  let highlightSources = new Set();     // sources drawn in their own colour

  /* ----------------------------- layers --------------------------------- */
  // All venues are jointly clustered and live together in `points`, tagged by
  // `points.source` (index into `sources`). A layer is that venue's slice — so
  // every source is equal: independently shown/hidden, cluster-coloured, and
  // optionally highlighted in its own colour. Memoised (points are static).
  let _layers = null;
  function sourceLayers() {
    if (_layers) return _layers;
    const d = ACC.state.data, P = d.points, src = P.source || [];
    const layers = (d.sources || []).map(s => ({
      id: s.id, venue: s.venue, color: s.color, base: !!s.base,
      x: [], y: [], year: [], cluster: [], claim: [], paper: [],
      papers: d.papers, titles: d.titles }));
    if (layers.length) {
      for (let i = 0; i < P.x.length; i++) {
        const l = layers[src[i]] || layers[0];
        l.x.push(P.x[i]); l.y.push(P.y[i]); l.year.push(P.year[i]);
        l.cluster.push(P.cluster[i]); l.claim.push(P.claim[i]); l.paper.push(P.paper[i]);
      }
    }
    _layers = layers;
    return layers;
  }
  function visibleLayers() { return sourceLayers().filter(l => visibleSources.has(l.id)); }

  function layerIndices(layer) {
    const sel = ACC.state.selectedClusters, yr = ACC.state.year;
    const pts = [], noise = [];
    for (let i = 0; i < layer.x.length; i++) {
      if (yr !== 'ALL' && layer.year[i] !== yr) continue;
      const cid = layer.cluster[i];
      if (cid === -1) { if (showNoise) noise.push(i); continue; }
      if (sel.size && !sel.has(cid)) continue;
      pts.push(i);
    }
    return { pts, noise };
  }

  function clusteredColors(layer, idx) {
    if (highlightSources.has(layer.id)) return idx.map(() => layer.color);
    const drift = ACC.state.colorMode === 'drift';
    return idx.map(i => {
      const c = ACC.state.clusterById.get(layer.cluster[i]);
      return drift ? ACC.driftColor(c) : ACC.clusterColor(c);
    });
  }

  /* ---------------------------- tooltips -------------------------------- */
  function tipFor(layer, i) { return overlayTip(layer, i); }   // cluster-led + venue
  function overlayTip(layer, i) {
    const p = ACC.pal();
    const c = ACC.state.clusterById.get(layer.cluster[i]);
    const tc = c && c.deltaPp >= 0 ? p.up : p.down;
    const claim = ACC.wrapHtml(layer.claim[i], 64);
    const title = ACC.wrapHtml(layer.titles[layer.paper[i]] || '', 64);
    return `<b style='font-size:12.5px'>${c ? ACC.escapeHtml(c.label).toUpperCase() : 'UNCLUSTERED'}</b> ` +
      (c ? `<span style='color:${tc}'><b>${ACC.fmtPp(c.deltaPp)}</b> since ${ACC.state.data.meta.years[0]}</span>` : '') + '<br>' +
      `<span style='color:${p.fnt};font-size:10px'>From a ${layer.year[i]} ${ACC.escapeHtml(layer.venue)} paper</span><br>` +
      `<span>${claim}</span><br>` +
      `<span style='color:${p.fnt2};font-size:10px'><i>${title}</i></span>`;
  }

  /* --------------------------- annotations ------------------------------ */
  function labelAnnotations() {
    const p = ACC.pal();
    const pts = ACC.state.data.points;
    return ACC.state.sorted.slice(0, 15).map(c => {
      const xs = [], ys = [];
      for (let i = 0; i < pts.x.length; i++) {
        if (pts.cluster[i] === c.id) { xs.push(pts.x[i]); ys.push(pts.y[i]); }
      }
      xs.sort((a, b) => a - b); ys.sort((a, b) => a - b);
      return {
        x: xs[xs.length >> 1], y: ys[ys.length >> 1], xref: 'x', yref: 'y',
        text: ACC.escapeHtml(c.label), showarrow: false,
        bgcolor: p.labelBg, bordercolor: ACC.clusterColor(c), borderwidth: 1.2, borderpad: 3,
        font: { size: 11.5, color: p.ink, family: "'IBM Plex Sans', sans-serif", weight: 600 },
      };
    });
  }

  /* ------------------------------ search -------------------------------- */
  function searchMatches() {
    if (searchQ.length < 3) return null;
    const lq = searchQ.toLowerCase();
    const sel = ACC.state.selectedClusters, yr = ACC.state.year;
    const xs = [], ys = [], per = new Map();
    let hidden = 0;
    for (const layer of visibleLayers()) {
      for (let i = 0; i < layer.x.length; i++) {
        const tit = layer.titles[layer.paper[i]] || '';
        if (!(layer.claim[i].toLowerCase().includes(lq) || tit.toLowerCase().includes(lq))) continue;
        const cid = layer.cluster[i];
        let vis = !(yr !== 'ALL' && layer.year[i] !== yr);
        vis = vis && (cid === -1 ? showNoise : (!sel.size || sel.has(cid)));
        if (!vis) { hidden++; continue; }
        xs.push(layer.x[i]); ys.push(layer.y[i]);
        per.set(cid, (per.get(cid) || 0) + 1);
      }
    }
    return { xs, ys, per, hidden };
  }

  function updateSearchUi() {
    const m = searchMatches();
    const countEl = document.getElementById('map-search-count');
    const box = document.getElementById('search-top');
    if (!m) { countEl.textContent = ''; box.hidden = true; box.innerHTML = ''; return; }
    countEl.textContent = m.xs.length + ' match' + (m.xs.length === 1 ? '' : 'es') +
      (m.hidden ? ` (+${m.hidden} filtered out)` : '');
    const top = [...m.per.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
    if (!top.length) { box.hidden = true; box.innerHTML = ''; return; }
    box.innerHTML = '<div class="pop-head">TOP CLUSTERS BY MATCHES</div>';
    for (const [cid, n] of top) {
      const c = cid === -1 ? null : ACC.state.clusterById.get(cid);
      const item = document.createElement('div');
      item.className = 'legend-item';
      item.innerHTML =
        `<span class="legend-dot" style="background:${ACC.clusterColor(c || { id: -1 })}"></span>` +
        `<span class="legend-name">${c ? ACC.escapeHtml(c.label) : 'Unclustered'}</span>` +
        `<span class="legend-count">${n}</span>`;
      item.title = 'click: isolate on map · double-click: details';
      item.addEventListener('click', () => isolate(cid));
      item.addEventListener('dblclick', () => ACC.emit('open-cluster', cid));
      box.appendChild(item);
    }
    box.hidden = false;
  }

  /* ------------------------------- traces ------------------------------- */
  function mapTraces() {
    const p = ACC.pal();
    const traces = [];
    for (const layer of visibleLayers()) {
      const { pts, noise } = layerIndices(layer);
      const hl = highlightSources.has(layer.id);
      if (noise.length) {
        traces.push({ type: 'scattergl', mode: 'markers',
          x: noise.map(i => layer.x[i]), y: noise.map(i => layer.y[i]),
          text: noise.map(i => tipFor(layer, i)), customdata: noise.map(i => [layer.id, i]),
          hoverinfo: 'text', name: layer.venue + ' · unclustered',
          marker: { symbol: 'circle-open', size: 3, color: hl ? layer.color : p.noise } });
      }
      traces.push({ type: 'scattergl', mode: 'markers',
        x: pts.map(i => layer.x[i]), y: pts.map(i => layer.y[i]),
        text: pts.map(i => tipFor(layer, i)), customdata: pts.map(i => [layer.id, i]),
        hoverinfo: 'text', name: layer.venue,
        marker: { size: layer.base ? 5.5 : 6, opacity: hl ? 0.95 : 0.88,
                  symbol: hl ? 'diamond' : 'circle', color: clusteredColors(layer, pts),
                  line: hl ? { width: 0.5, color: p.plot } : { width: 0 } } });
    }
    const m = searchMatches();
    traces.push({ type: 'scattergl', mode: 'markers', x: m ? m.xs : [], y: m ? m.ys : [],
      visible: !!(m && m.xs.length), hoverinfo: 'skip', customdata: null,
      marker: { symbol: 'circle-open', size: 13, color: p.ink, line: { width: 2.5, color: p.ink } } });
    return traces;
  }

  /** Current viewport, or null before the first plot. */
  function currentRanges() {
    if (!gd || !gd._fullLayout || !gd._fullLayout.xaxis) return null;
    return { x: gd._fullLayout.xaxis.range.slice(),
             y: gd._fullLayout.yaxis.range.slice() };
  }

  function draw() {
    const keep = autoFit ? null : currentRanges();
    const layout = ACC.plBase({
      showlegend: false,
      margin: { l: 8, r: 8, t: 8, b: 8 },
      xaxis: Object.assign({ visible: false },
        keep ? { range: keep.x, autorange: false } : {}),
      yaxis: Object.assign({ visible: false },
        keep ? { range: keep.y, autorange: false } : {}),
      annotations: showLabels ? labelAnnotations() : [],
      dragmode: 'pan', uirevision: 'keep',
    });
    Plotly.react(gd, mapTraces(), layout,
      ACC.plConfig({ scrollZoom: true, displayModeBar: true }));
    if (autoFit) Plotly.relayout(gd, { 'xaxis.autorange': true, 'yaxis.autorange': true });
    updateSearchUi();
  }
  function refresh() { draw(); }

  /* ------------------------------ pin card ------------------------------ */
  function dismissPin() { if (pinEl) { pinEl.remove(); pinEl = null; } }

  function pinCard(layer, i, px, py) {
    dismissPin();
    const cid = layer.cluster[i];
    const c = cid === -1 ? null : ACC.state.clusterById.get(cid);
    const years = ACC.state.data.meta.years;
    const pid = layer.papers[layer.paper[i]];
    const url = ACC.state.data.meta.anthologyBase + pid;
    const card = document.createElement('div');
    card.className = 'pin-card';
    card.dataset.pin = '1';
    let html = '<div class="pin-head">' +
      `<span class="pin-label">${c ? ACC.escapeHtml(c.label) : 'Unclustered claim'}</span>`;
    if (c) {
      const dc = c.deltaPp >= 0 ? 'up-c' : 'down-c';
      html += `<span class="pin-delta ${dc}" title="how this cluster's share of papers changed, ${years[0]}→${years[years.length - 1]}">` +
        `${c.deltaPp >= 0 ? '▲ ' : '▼ '}${ACC.fmtPp(c.deltaPp)} since ${years[0]}</span>`;
    }
    html += '</div>';
    html += '<div class="pin-meta">' +
      `<span class="pin-src" style="border-color:${layer.color};color:${layer.color}">${ACC.escapeHtml(layer.venue)}</span>` +
      ` From a ${layer.year[i]} paper</div>`;
    html += `<div class="pin-claim">${ACC.escapeHtml(layer.claim[i])}</div>`;
    html += `<div class="pin-title">${ACC.escapeHtml(layer.titles[layer.paper[i]] || '')}</div>`;
    html += '<div class="pin-actions">' +
      `<a href="${url}" target="_blank">Open in Anthology ↗</a>` +
      `<span class="link pin-goto">${c ? 'Cluster details' : 'Unclustered details'} →</span></div>`;
    card.innerHTML = html;
    const rect = wrap.getBoundingClientRect();
    card.style.left = Math.max(8, Math.min(px + 14, rect.width - 360)) + 'px';
    card.style.top = Math.max(8, Math.min(py + 10, rect.height - 250)) + 'px';
    wrap.appendChild(card);
    pinEl = card;
    card.querySelector('.pin-goto')
      .addEventListener('click', () => { dismissPin(); ACC.emit('open-cluster', cid); });
  }

  /* ------------------------------ legend -------------------------------- */
  function renderLegend() {
    const list = document.getElementById('legend-list');
    const lf = document.getElementById('legend-filter').value.trim().toLowerCase();
    const sel = ACC.state.selectedClusters;
    list.innerHTML = '';
    for (const c of ACC.state.sorted) {
      if (lf && !(c.label + ' ' + c.raw).toLowerCase().includes(lf)) continue;
      const isSel = sel.has(c.id);
      const item = document.createElement('div');
      item.className = 'legend-item' + (isSel ? ' selected' : (sel.size ? ' dimmed' : ''));
      item.title = `${c.label} · ${c.size.toLocaleString()} claims · ` +
        `${ACC.fmtPp(c.deltaPp)} since ${ACC.state.data.meta.years[0]} — click: isolate · ctrl/cmd-click: add · double-click: details`;
      item.innerHTML =
        `<span class="legend-dot" style="background:${ACC.clusterColor(c)}"></span>` +
        `<span class="legend-name">${ACC.escapeHtml(c.label)}</span>` +
        `<span class="legend-arrow ${c.deltaPp >= 0 ? 'up' : 'down'}">${ACC.trendArrow(c)}</span>` +
        `<span class="legend-count">${c.size.toLocaleString()}</span>`;
      item.addEventListener('click', e => {
        if (e.ctrlKey || e.metaKey) { sel.has(c.id) ? sel.delete(c.id) : sel.add(c.id); }
        else if (sel.size === 1 && sel.has(c.id)) sel.clear();
        else { sel.clear(); sel.add(c.id); }
        renderLegend(); refresh();
      });
      item.addEventListener('dblclick', () => ACC.emit('open-cluster', c.id));
      list.appendChild(item);
    }
  }

  /* --------------------------- sources menu ----------------------------- */
  function renderSourcesPop() {
    const pop = document.getElementById('sources-pop');
    const sources = ACC.state.data.sources || [];
    pop.innerHTML = '<div class="pop-head">SOURCE · SHOW / HIGHLIGHT</div>';
    for (const s of sources) {
      const row = document.createElement('label');
      row.className = 'src-row';
      const vis = document.createElement('input');
      vis.type = 'checkbox'; vis.checked = visibleSources.has(s.id);
      vis.addEventListener('change', () => {
        if (vis.checked) visibleSources.add(s.id); else visibleSources.delete(s.id);
        refresh();
      });
      const lab = document.createElement('span');
      lab.className = 'src-label';
      lab.innerHTML =
        `<span class="src-dot" style="background:${s.color}"></span>${ACC.escapeHtml(s.venue)}` +
        `<br><span class="sub">${s.role === 'clustered' ? 'clustered' : 'overlaid'} · ${(s.nClaims || 0).toLocaleString()} claims</span>`;
      const hl = document.createElement('button');
      hl.type = 'button';
      hl.className = 'src-hl' + (highlightSources.has(s.id) ? ' on' : '');
      hl.title = 'highlight this source in its own colour';
      hl.textContent = '◑'; hl.style.color = s.color;
      hl.addEventListener('click', e => {
        e.preventDefault();
        if (highlightSources.has(s.id)) highlightSources.delete(s.id); else highlightSources.add(s.id);
        hl.classList.toggle('on');
        refresh();
      });
      row.appendChild(vis); row.appendChild(lab); row.appendChild(hl);
      pop.appendChild(row);
    }
  }

  function buildSourcesPop() {
    const btn = document.getElementById('sources-btn');
    const pop = document.getElementById('sources-pop');
    if (!btn || !pop) return;
    const sources = ACC.state.data.sources || [];
    if (sources.length <= 1) { btn.parentElement.hidden = true; return; }
    renderSourcesPop();
    btn.addEventListener('click', () => { pop.hidden = !pop.hidden; });
    document.addEventListener('mousedown', e => {
      if (!pop.hidden && !pop.contains(e.target) && !btn.contains(e.target)) pop.hidden = true;
    });
  }

  /* ------------------------------ controls ------------------------------ */
  function buildControls() {
    const years = ACC.state.data.meta.years;

    const yb = document.getElementById('year-buttons');
    const mkYear = (label, val) => {
      const b = document.createElement('button');
      b.className = 'seg-btn' + (val === ACC.state.year ? ' active' : '');
      b.textContent = label;
      b.addEventListener('click', () => {
        ACC.state.year = val;
        yb.querySelectorAll('.seg-btn').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        refresh();
      });
      yb.appendChild(b);
    };
    years.forEach(y => mkYear(String(y), y));
    mkYear('All', 'ALL');

    const cb = document.getElementById('color-buttons');
    [['Topics', 'cluster'], ['Drift', 'drift']].forEach(([label, val]) => {
      const b = document.createElement('button');
      b.className = 'seg-btn' + (val === ACC.state.colorMode ? ' active' : '');
      b.textContent = label;
      b.addEventListener('click', () => {
        ACC.state.colorMode = val;
        cb.querySelectorAll('.seg-btn').forEach(x => x.classList.remove('active'));
        b.classList.add('active');
        refresh();
      });
      cb.appendChild(b);
    });

    const dBtn = document.getElementById('display-btn');
    const dPop = document.getElementById('display-pop');
    dBtn.addEventListener('click', () => { dPop.hidden = !dPop.hidden; });
    document.addEventListener('mousedown', e => {
      if (!dPop.hidden && !dPop.contains(e.target) && !dBtn.contains(e.target)) dPop.hidden = true;
    });
    document.getElementById('toggle-labels').addEventListener('change', e => {
      showLabels = e.target.checked;
      Plotly.relayout(gd, { annotations: showLabels ? labelAnnotations() : [] });
    });
    document.getElementById('toggle-noise').addEventListener('change', e => {
      showNoise = e.target.checked; refresh();
    });
    document.getElementById('toggle-autofit').addEventListener('change', e => {
      autoFit = e.target.checked;
      if (autoFit) Plotly.relayout(gd, { 'xaxis.autorange': true, 'yaxis.autorange': true });
    });

    buildSourcesPop();

    let timer = null;
    const search = document.getElementById('map-search');
    if (ACC.state.claimsPending) search.placeholder = 'Search titles… (claim texts loading)';
    search.addEventListener('input', e => {
      clearTimeout(timer);
      const q = e.target.value.trim();
      timer = setTimeout(() => { searchQ = q; refresh(); }, 250);
    });

    document.getElementById('legend-filter').addEventListener('input', renderLegend);
    document.getElementById('legend-reset').addEventListener('click', () => {
      ACC.state.selectedClusters.clear(); renderLegend(); refresh();
    });

    const overlay = document.getElementById('intro-overlay');
    const openIntro = () => { overlay.hidden = false; };
    const closeIntro = () => { overlay.hidden = true; };
    document.getElementById('intro-dismiss').addEventListener('click', closeIntro);
    document.getElementById('intro-methods').addEventListener('click', () => { closeIntro(); ACC.emit('switch-view', 'methods'); });
    document.getElementById('reopen-intro').addEventListener('click', openIntro);
    const helpBtn = document.getElementById('map-help');
    if (helpBtn) helpBtn.addEventListener('click', openIntro);
    overlay.hidden = true;
  }

  /* ------------------------------- build -------------------------------- */
  function build() {
    if (built) return;
    built = true;
    gd = document.getElementById('map-plot');
    wrap = document.getElementById('map-plot-wrap');

    // All venues are jointly clustered, so show them all by default; each is
    // independently toggleable from the Sources menu.
    const sources = ACC.state.data.sources || [];
    visibleSources = new Set(sources.map(s => s.id));

    draw();
    gd.on('plotly_click', ev => {
      if (!ev.points || !ev.points.length) return;
      const pt = ev.points[0];
      const cd = pt.customdata;
      if (!Array.isArray(cd)) return;             // search ring / non-point trace
      const [sid, idx] = cd;
      const layer = sourceLayers().find(l => l.id === sid);
      if (!layer) return;
      const rect = wrap.getBoundingClientRect();
      const px = ev.event.clientX - rect.left, py = ev.event.clientY - rect.top;
      setTimeout(() => pinCard(layer, idx, px, py), 0);
    });
    document.addEventListener('mousedown', e => {
      if (pinEl && !e.target.closest('[data-pin]')) dismissPin();
    });

    buildControls();
    renderLegend();
  }

  function activate() {
    build();
    if (gd && gd.data) Plotly.Plots.resize(gd);
  }

  function isolate(cid) {
    ACC.state.selectedClusters.clear();
    ACC.state.selectedClusters.add(cid);
    if (cid === -1 && !showNoise) {
      showNoise = true;
      const t = document.getElementById('toggle-noise');
      if (t) t.checked = true;
    }
    if (built) { renderLegend(); refresh(); }
  }

  function rebuildTheme() {
    if (!built) return;
    dismissPin();
    draw();
    renderLegend();
  }

  // Claim texts arrived (split payload): drop the memoised per-source layers
  // (they carry copies of points.claim) and redraw so tooltips/search see them.
  ACC.on('claims-ready', () => {
    _layers = null;
    const s = document.getElementById('map-search');
    if (s) s.placeholder = 'Search claims & titles…';
    if (built) draw();
  });

  return { activate, isolate, rebuildTheme };
})();
