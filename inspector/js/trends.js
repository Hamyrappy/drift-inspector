/* ==========================================================================
   trends.js — Trends view: butterfly chart, linked per-year trajectories
   (capped line count for readability), and a sparkline grid (v5 design).
   ========================================================================== */
'use strict';

window.TrendsView = (function () {
  const MAX_TRAJ = 12;
  let built = false;
  let bfClickBound = false;
  let trajSelection = [];

  const visibleClusters = () =>
    ACC.state.data.clusters.filter(c => Math.max(...c.df) >= 0.3);

  /* ----------------------------- butterfly ------------------------------ */
  function butterflyRows() {
    const topN = +document.getElementById('butterfly-topn').value;
    const sorted = [...visibleClusters()].sort((a, b) => a.deltaPp - b.deltaPp);
    const declining = sorted.slice(0, topN);
    const growing = sorted.slice(-topN);
    // dedupe: with fewer than 2×topN clusters the two halves overlap
    const seen = new Set();
    return [...declining, ...growing.reverse()].reverse()
      .filter(c => !seen.has(c.id) && seen.add(c.id));
  }

  function drawButterfly() {
    const gd = document.getElementById('butterfly-plot');
    const p = ACC.pal();
    const rows = butterflyRows();
    const years = ACC.state.data.meta.years;
    const trace = {
      type: 'bar', orientation: 'h',
      y: rows.map(c => c.label),
      x: rows.map(c => c.deltaPp),
      marker: {
        color: rows.map(c => c.deltaPp >= 0 ? p.up : p.down),
        opacity: rows.map(c => trajSelection.includes(c.id) ? 1.0 : 0.55),
        line: { width: rows.map(c => trajSelection.includes(c.id) ? 1.5 : 0),
                color: rows.map(() => p.ink) },
      },
      customdata: rows.map(c => c.id),
      hovertemplate: `<b>%{y}</b><br>Δ %{x:+.1f} pp (${years[0]} → ${years[years.length - 1]})<extra></extra>`,
    };
    const annotations = rows.map(c => ({
      x: 0, y: c.label,
      xanchor: c.deltaPp >= 0 ? 'right' : 'left',
      xshift: c.deltaPp >= 0 ? -6 : 6,
      text: `${ACC.fmtPct(c.df[0])} → ${ACC.fmtPct(c.df[c.df.length - 1])} (${ACC.fmtRel(c)})`,
      showarrow: false, font: { size: 9.5, color: p.fnt },
    }));
    Plotly.react(gd, [trace], ACC.plBase({
      height: Math.max(300, rows.length * 26 + 90),
      margin: { l: 230, r: 20, t: 8, b: 36 },
      xaxis: { title: { text: 'Δ share of papers, pp', font: { size: 11, color: p.mut } },
               zeroline: true, zerolinecolor: p.line2, gridcolor: p.line, tickfont: { size: 10, color: p.fnt } },
      yaxis: { tickfont: { size: 11, color: p.ink2 }, gridcolor: 'rgba(0,0,0,0)' },
      bargap: 0.25, annotations,
    }), ACC.plConfig());
    if (!bfClickBound) {
      bfClickBound = true;
      gd.on('plotly_click', ev => {
        if (ev.points && ev.points.length) toggleTraj(ev.points[0].customdata);
      });
    }
  }

  function refreshButterflyHighlight() {
    const gd = document.getElementById('butterfly-plot');
    if (!gd || !gd.data) return;
    const ids = gd.data[0].customdata;
    Plotly.restyle(gd, {
      'marker.opacity': [ids.map(id => trajSelection.includes(id) ? 1.0 : 0.55)],
      'marker.line.width': [ids.map(id => trajSelection.includes(id) ? 1.5 : 0)],
    }, [0]);
  }

  /* ---------------------------- trajectories ---------------------------- */
  function toggleTraj(cid) {
    const i = trajSelection.indexOf(cid);
    if (i >= 0) trajSelection.splice(i, 1);
    else { if (trajSelection.length >= MAX_TRAJ) trajSelection.shift(); trajSelection.push(cid); }
    drawTrajectories();
    refreshButterflyHighlight();
    renderSparkSelection();
  }

  function drawTrajectories() {
    const gd = document.getElementById('traj-plot');
    const p = ACC.pal();
    const years = ACC.state.data.meta.years;
    const hint = document.getElementById('traj-hint');
    hint.textContent = trajSelection.length
      ? `${trajSelection.length} cluster(s) shown — click butterfly bars or sparklines to add or remove (max ${MAX_TRAJ})`
      : 'click butterfly bars or sparklines to plot trajectories';
    const normalize = document.getElementById('traj-normalize').checked;
    const traces = trajSelection.map(cid => {
      const c = ACC.state.clusterById.get(cid);
      const peak = Math.max(...c.df, 1e-9);
      const ys = normalize ? c.df.map(v => v / peak * 100) : c.df;
      return {
        type: 'scatter', mode: 'lines+markers', x: years, y: ys, name: c.label,
        line: { color: ACC.clusterColor(c), width: 2 }, marker: { size: 5 },
        customdata: c.df,
        hovertemplate: `<b>${c.label}</b><br>%{x}: %{customdata:.1f}% of papers` +
          (normalize ? ' (%{y:.0f}% of peak)' : '') + '<extra></extra>',
      };
    });
    Plotly.react(gd, traces, ACC.plBase({
      height: 380,
      margin: { l: 50, r: 10, t: 8, b: 36 },
      xaxis: { tickvals: years, tickfont: { size: 11, color: p.fnt }, gridcolor: p.line },
      yaxis: { title: { text: normalize ? '% of cluster peak' : '% of papers', font: { size: 11, color: p.mut } },
               rangemode: 'tozero', tickfont: { size: 10, color: p.fnt }, gridcolor: p.line, zerolinecolor: p.line2 },
      legend: { orientation: 'h', y: -0.12, font: { size: 10.5, color: p.ink2 } },
      hovermode: 'closest',
    }), ACC.plConfig());
  }

  /* ----------------------------- sparklines ----------------------------- */
  function sparkSvg(c, colHex) {
    const w = 150, h = 34, pad = 3;
    const max = Math.max(...c.df, 0.1);
    const px = i => pad + i * (w - 2 * pad) / Math.max(1, c.df.length - 1);
    const py = v => h - pad - v / max * (h - 2 * pad);
    const pts = c.df.map((v, i) => px(i).toFixed(1) + ',' + py(v).toFixed(1)).join(' ');
    return `<svg class="spark-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">` +
      `<polyline points="${pts}" fill="none" stroke="${colHex}" stroke-width="1.6"/>` +
      `<circle cx="${px(c.df.length - 1).toFixed(1)}" cy="${py(c.df[c.df.length - 1]).toFixed(1)}" r="2.2" fill="${colHex}"/>` +
      '</svg>';
  }

  function drawSparks() {
    const grid = document.getElementById('spark-grid');
    const p = ACC.pal();
    const mode = document.getElementById('spark-sort').value;
    const sorted = [...visibleClusters()].sort((a, b) =>
      mode === 'delta-desc' ? b.deltaPp - a.deltaPp :
      mode === 'delta-asc' ? a.deltaPp - b.deltaPp : b.size - a.size);
    grid.innerHTML = '';
    for (const c of sorted) {
      const up = c.deltaPp >= 0;
      const colHex = up ? p.up : p.down;
      const cell = document.createElement('div');
      cell.className = 'spark-cell' + (trajSelection.includes(c.id) ? ' selected' : '');
      cell.dataset.cid = c.id;
      cell.title = `${c.label} · share of papers by year: ${c.df.map(v => v.toFixed(1)).join(' → ')}%`;
      cell.innerHTML =
        `<div class="spark-name">${ACC.escapeHtml(c.label)}</div>` +
        `<div class="spark-delta ${up ? 'up-c' : 'down-c'}">${ACC.fmtPp(c.deltaPp)} · ${ACC.fmtRel(c)}</div>` +
        sparkSvg(c, colHex);
      cell.addEventListener('click', () => toggleTraj(c.id));
      cell.addEventListener('dblclick', () => ACC.emit('open-cluster', c.id));
      grid.appendChild(cell);
    }
  }

  function renderSparkSelection() {
    document.querySelectorAll('.spark-cell').forEach(cell =>
      cell.classList.toggle('selected', trajSelection.includes(+cell.dataset.cid)));
  }

  /* ------------------------------- build -------------------------------- */
  function build() {
    if (built) return;
    built = true;
    const cs = [...visibleClusters()].sort((a, b) => a.deltaPp - b.deltaPp);
    trajSelection = [...new Set([...cs.slice(0, 1), ...cs.slice(-1)].map(c => c.id))];

    drawButterfly(); drawTrajectories(); drawSparks();

    document.getElementById('butterfly-topn').addEventListener('change', drawButterfly);
    document.getElementById('spark-sort').addEventListener('change', drawSparks);
    document.getElementById('traj-normalize').addEventListener('change', drawTrajectories);
    document.getElementById('traj-clear').addEventListener('click', () => {
      trajSelection = [];
      drawTrajectories(); refreshButterflyHighlight(); renderSparkSelection();
    });
  }

  function activate() {
    build();
    ['butterfly-plot', 'traj-plot'].forEach(id => {
      const el = document.getElementById(id);
      if (el && el.data) Plotly.Plots.resize(el);
    });
  }

  function rebuildTheme() {
    if (!built) return;
    drawButterfly(); drawTrajectories(); drawSparks();
  }

  return { activate, rebuildTheme };
})();
