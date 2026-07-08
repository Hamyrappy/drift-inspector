/* ==========================================================================
   data.js — data loading, theme + color science, shared helpers.
   Exposes a global `ACC` namespace used by all views.

   Colors are computed CLIENT-SIDE (theme-aware oklch), so the v5 palette
   reflows for light/dark and stays consistent between the static DOM (dots),
   the Plotly traces, and the HTML tooltips. The baked c.color / c.driftColor
   fields in acc_data.json are ignored — kept only for backward compatibility.

   Data sources (priority): <script id="acc-data"> (baked), else the split
   pair acc_core.json (small, first paint) + acc_claims.json (claim texts +
   author tables, fetched in the background — `claims-ready` fires when they
   land), else the monolithic acc_data.json. Replace data/acc_data.json
   (same schema) to point at another corpus — the split files are an optional
   optimisation and are simply absent for swapped corpora.
   ========================================================================== */
'use strict';

window.ACC = (function () {

  /* size-ordered hue wheel: cluster i (by size rank) gets HUES[i] */
  const HUES = [255, 25, 150, 75, 315, 200, 0, 110, 230, 345,
                55, 170, 285, 130, 35, 215, 95, 270, 10, 185];

  const state = {
    data: null,
    claimsPending: false,         // true while claim texts stream in the background
    clusterById: new Map(),
    sorted: [],                   // clusters by size desc
    hueById: new Map(),
    tooltipCache: {},             // theme -> per-point hover html
    selectedClusters: new Set(),  // empty = all
    year: 'ALL',
    colorMode: 'cluster',
    theme: 'light',
    listeners: {},
  };

  /* ----------------------------- events -------------------------------- */
  function on(event, fn) { (state.listeners[event] = state.listeners[event] || []).push(fn); }
  function emit(event, payload) { (state.listeners[event] || []).forEach(fn => fn(payload)); }

  /* --------------------------- data loading ----------------------------- */
  async function load() {
    const embedded = document.getElementById('acc-data');
    if (embedded) {
      state.data = JSON.parse(embedded.textContent);
    } else {
      // Prefer the split payload: acc_core.json is ~1/4 of the bytes and is
      // everything the map/trends need; claim texts stream in behind it.
      let core = null;
      try {
        const r = await fetch('data/acc_core.json', { cache: 'no-store' });
        if (r.ok) core = await r.json();
      } catch (e) { /* no split build — fall through to the monolith */ }
      if (core) {
        core.points.claim = new Array(core.points.x.length).fill('');
        core.authorsByPaper = [];
        core.authorsIndex = {};
        state.data = core;
        state.claimsPending = true;
        fetch('data/acc_claims.json', { cache: 'no-store' })
          .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
          .then(heavy => {
            state.data.points.claim = heavy.claim;
            state.data.authorsByPaper = heavy.authorsByPaper || [];
            state.data.authorsIndex = heavy.authorsIndex || {};
            state.claimsPending = false;
            state.tooltipCache = {};
            emit('claims-ready');
          })
          .catch(err => {
            console.error('failed to load data/acc_claims.json:', err);
            state.claimsPending = false;
            emit('claims-ready');           // unblock the UI (texts stay empty)
          });
      } else {
        const resp = await fetch('data/acc_data.json', { cache: 'no-store' });
        if (!resp.ok) throw new Error('failed to load data/acc_data.json');
        state.data = await resp.json();
      }
    }
    normalize(state.data);
    state.clusterById = new Map();
    for (const c of state.data.clusters) state.clusterById.set(c.id, c);
    state.sorted = [...state.data.clusters].sort((a, b) => b.size - a.size);
    state.hueById = new Map();
    state.sorted.forEach((c, i) => state.hueById.set(c.id, HUES[i % HUES.length]));
    state.noiseCluster = buildNoiseCluster();
    if (state.noiseCluster) state.clusterById.set(-1, state.noiseCluster);
    return state.data;
  }

  /** Normalise older acc_data.json builds (e.g. the pinned EMNLP instance) to
      the current all-in-points contract: points.source tags and per-source
      stats. Builds from the current exporter ship all of this, so every step
      is a no-op for them. */
  function normalize(d) {
    const P = d.points;
    if (!d.sources || !d.sources.length) {
      d.sources = [{ id: 'corpus', name: d.meta.title || 'Corpus',
                     venue: 'Corpus', color: '#1f77b4', base: true }];
    }
    if (!P.source) {
      // Pre-overlay schema: every point belongs to the base corpus; any other
      // listed source has no points in this build — drop its dead menu row.
      d.sources = [d.sources.find(s => s.base) || d.sources[0]];
      P.source = new Array(P.x.length).fill(0);
    }
    if (d.sources.some(s => s.nClaims == null)) {
      const stats = d.sources.map(() => ({ n: 0, papers: new Set(), years: new Set() }));
      for (let i = 0; i < P.x.length; i++) {
        const st = stats[P.source[i]] || stats[0];
        st.n++; st.papers.add(P.paper[i]); st.years.add(P.year[i]);
      }
      d.sources.forEach((s, k) => {
        if (s.nClaims == null) s.nClaims = stats[k].n;
        if (s.nPapers == null) s.nPapers = stats[k].papers.size;
        if (!s.years) s.years = [...stats[k].years].sort((a, b) => a - b);
        if (!s.role) s.role = s.base ? 'clustered' : 'assigned';
      });
    }
  }

  /** Synthesize a pseudo-cluster for the noise points (id -1), computed from
      the points themselves so it works for any swapped data file. Same shape
      as a real cluster entry — the Clusters view renders it like any other. */
  function buildNoiseCluster() {
    const pts = state.data.points;
    const m = state.data.meta;
    const years = m.years;
    const yi = new Map(years.map((y, k) => [y, k]));
    const claims = years.map(() => 0);
    const paperSets = years.map(() => new Set());
    const allPapers = new Set();
    let size = 0;
    for (let i = 0; i < pts.x.length; i++) {
      if (pts.cluster[i] !== -1) continue;
      size++;
      allPapers.add(pts.paper[i]);
      const k = yi.get(pts.year[i]);
      if (k === undefined) continue;
      claims[k]++;
      paperSets[k].add(pts.paper[i]);
    }
    if (!size) return null;
    const df = years.map((y, k) =>
      m.papersPerYear[k] ? +(100 * paperSets[k].size / m.papersPerYear[k]).toFixed(4) : 0);
    const d0 = df[0], d1 = df[df.length - 1];
    return {
      id: -1, label: 'Unclustered', raw: '', reviewed: false,
      size, papers: allPapers.size,
      df, papersByYear: paperSets.map(s => s.size), claims,
      deltaPp: +(d1 - d0).toFixed(4),
      rel: d0 > 0 ? +((d1 - d0) / d0).toFixed(4) : null,
    };
  }

  /* ============================ color science =========================== */
  /** oklch (L 0..1, C, H deg) -> sRGB hex. */
  function oklchHex(L, C, H) {
    const r = H * Math.PI / 180;
    const a = C * Math.cos(r), b = C * Math.sin(r);
    const l_ = L + 0.3963377774 * a + 0.2158037573 * b;
    const m_ = L - 0.1055613458 * a - 0.0638541728 * b;
    const s_ = L - 0.0894841775 * a - 1.2914855480 * b;
    const l = l_ ** 3, m = m_ ** 3, s = s_ ** 3;
    const R = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
    const G = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
    const B = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s;
    const g = c => { c = Math.max(0, Math.min(1, c)); return c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055; };
    const h = c => Math.round(g(c) * 255).toString(16).padStart(2, '0');
    return '#' + h(R) + h(G) + h(B);
  }

  let palCache = null;
  /** Theme palette (hex mirrors the CSS variables, for Plotly + tooltips). */
  function pal() {
    const dark = state.theme === 'dark';
    if (palCache && palCache.dark === dark) return palCache;
    palCache = dark ? {
      dark, bg: '#131519', plot: '#0f1115', card: '#1b1e25',
      ink: '#e9e7df', ink2: '#d7d4c8', mut: '#9a978c', fnt: '#8c8a80', fnt2: '#777568',
      line: '#272b33', line2: '#3a404b',
      acc: oklchHex(0.80, 0.11, 80), up: oklchHex(0.75, 0.11, 160), down: oklchHex(0.68, 0.15, 32),
      labelBg: 'rgba(15,17,21,0.85)', noise: 'rgba(200,205,215,0.30)',
    } : {
      dark, bg: '#faf9f6', plot: '#fcfbf8', card: '#fffefb',
      ink: '#211f1a', ink2: '#33312b', mut: '#6f6a5d', fnt: '#8a8576', fnt2: '#9b968a',
      line: '#e7e3d8', line2: '#cfc9ba',
      acc: oklchHex(0.46, 0.09, 250), up: oklchHex(0.50, 0.10, 160), down: oklchHex(0.55, 0.13, 35),
      labelBg: 'rgba(252,251,248,0.90)', noise: 'rgba(130,124,108,0.35)',
    };
    return palCache;
  }

  function clusterColor(c) {
    if (c.id === -1) return pal().dark ? '#9a978c' : '#8d887b';   // noise: neutral
    const h = state.hueById.get(c.id);
    return pal().dark ? oklchHex(0.74, 0.12, h) : oklchHex(0.55, 0.10, h);
  }

  /** Relative drift color: log2 of the 2025/2020 share ratio, ×8 saturates. */
  function driftColor(c) {
    const df0 = c.df[0], df1 = c.df[c.df.length - 1];
    let t = Math.log2((df1 + 0.05) / (df0 + 0.05)) / 3;
    t = Math.max(-1, Math.min(1, t));
    const at = Math.abs(t);
    const hue = t >= 0 ? 160 : (pal().dark ? 32 : 35);
    return pal().dark
      ? oklchHex(0.66 + 0.08 * at, 0.04 + 0.11 * at, hue)
      : oklchHex(0.62 - 0.10 * at, 0.03 + 0.11 * at, hue);
  }

  /* --------------------------- small helpers ---------------------------- */
  const fmtPp = v => (v >= 0 ? '+' : '') + v.toFixed(1) + ' pp';
  const fmtPct = v => v.toFixed(1) + '%';
  const fmtRel = c => {
    if (c.rel === null || c.rel === undefined) return 'new';
    if (c.rel >= 1) return '×' + (1 + c.rel).toFixed(1);
    return (c.rel >= 0 ? '+' : '') + Math.round(c.rel * 100) + '%';
  };
  const trendArrow = c => (c.deltaPp >= 0 ? '▲' : '▼');
  const escapeHtml = s => String(s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const wrapHtml = (s, w) => {
    const words = escapeHtml(s).split(' ');
    const lines = [];
    let cur = '';
    for (const word of words) {
      if (cur && cur.length + word.length + 1 > w) { lines.push(cur); cur = word; }
      else cur = cur ? cur + ' ' + word : word;
    }
    if (cur) lines.push(cur);
    return lines.join('<br>');
  };
  const paperUrl = i => state.data.meta.anthologyBase + state.data.papers[i];

  /** Split a year series into the connectors that bridge missing years, so a
      line can be drawn SOLID between consecutive present years and DASHED only
      across gaps — instead of dashing a whole line just because one year is
      absent. `y` is null at years the series has no point; optional `covered[i]`
      marks whether year i is covered by the source at all (a real gap) vs merely
      lacking a point (bridge solid then). Draw the base line with
      connectgaps:false, then overlay the returned solid/dashed segment lists. */
  function gapBridge(x, y, covered) {
    const dashX = [], dashY = [], solidX = [], solidY = [];
    let prev = -1;
    for (let i = 0; i < y.length; i++) {
      if (y[i] == null) continue;
      if (prev >= 0 && i > prev + 1) {
        let uncovered = false;
        for (let k = prev + 1; k < i && !uncovered; k++) if (!covered || !covered[k]) uncovered = true;
        const tx = uncovered ? dashX : solidX, ty = uncovered ? dashY : solidY;
        tx.push(x[prev], x[i], null); ty.push(y[prev], y[i], null);
      }
      prev = i;
    }
    return { dashX, dashY, solidX, solidY };
  }

  /* ------------------------- per-point tooltips ------------------------- */
  function tooltips() {
    const key = state.theme;
    if (state.tooltipCache[key]) return state.tooltipCache[key];
    const p = pal();
    const pts = state.data.points;
    const years = state.data.meta.years;
    const y0 = years[0];
    const out = new Array(pts.x.length);
    for (let i = 0; i < pts.x.length; i++) {
      const cid = pts.cluster[i];
      const claim = wrapHtml(pts.claim[i], 64);
      const title = wrapHtml(state.data.titles[pts.paper[i]], 64);
      if (cid === -1) {
        out[i] =
          `<b style='color:${p.fnt}'>UNCLUSTERED CLAIM</b><br>` +
          `<span style='color:${p.fnt};font-size:10px'>Year ${pts.year[i]}</span><br>` +
          `<span>${claim}</span><br>` +
          `<span style='color:${p.fnt2};font-size:10px'><i>${title}</i></span>`;
      } else {
        const c = state.clusterById.get(cid);
        const tc = c.deltaPp >= 0 ? p.up : p.down;
        out[i] =
          `<b style='font-size:12.5px'>${escapeHtml(c.label).toUpperCase()}</b> ` +
          `<span style='color:${tc}'><b>${fmtPp(c.deltaPp)}</b> since ${y0}</span><br>` +
          `<span style='color:${p.fnt};font-size:10px'>From a ${pts.year[i]} paper</span><br>` +
          `<span>${claim}</span><br>` +
          `<span style='color:${p.fnt2};font-size:10px'><i>${title}</i></span>`;
      }
    }
    state.tooltipCache[key] = out;
    return out;
  }

  /* ------------------------------- theme -------------------------------- */
  function initTheme() {
    let theme = 'light';
    try { theme = localStorage.getItem('di5.theme') || 'light'; } catch (e) {}
    state.theme = theme;
    document.body.dataset.theme = theme;
    palCache = null;
  }
  function toggleTheme() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    document.body.dataset.theme = state.theme;
    try { localStorage.setItem('di5.theme', state.theme); } catch (e) {}
    palCache = null;
    emit('theme', state.theme);
  }

  /* ---------------- shared Plotly base layout / config ------------------ */
  function plBase(extra) {
    const p = pal();
    return Object.assign({
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { family: "'IBM Plex Sans', sans-serif", color: p.mut, size: 11 },
      hoverlabel: { bgcolor: p.card, bordercolor: p.line2,
                    font: { size: 11.5, color: p.ink2, family: "'IBM Plex Sans', sans-serif" } },
      modebar: { bgcolor: 'rgba(0,0,0,0)', color: p.fnt, activecolor: p.ink },
    }, extra);
  }
  function plConfig(extra) {
    return Object.assign({
      responsive: true, displaylogo: false, displayModeBar: 'hover',
      modeBarButtonsToRemove: ['zoom2d', 'pan2d', 'zoomIn2d', 'zoomOut2d',
                               'autoScale2d', 'resetScale2d', 'select2d', 'lasso2d'],
    }, extra);
  }

  return {
    state, load, on, emit, tooltips,
    oklchHex, pal, clusterColor, driftColor,
    fmtPp, fmtPct, fmtRel, trendArrow, escapeHtml, wrapHtml, paperUrl, gapBridge,
    initTheme, toggleTheme, plBase, plConfig,
  };
})();
