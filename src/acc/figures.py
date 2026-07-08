"""
Paper figures regenerated from the paper's EMNLP study corpus.

  * ``build_butterfly()``     -> artifacts/drift_chart_butterfly.pdf
  * ``build_trajectories()``  -> artifacts/drift_trajectories.pdf

Both recompute directly from config.STUDY_CLUSTERS (the 16,576-claim study
corpus behind every number in the paper — NOT the extended joint clustering,
whose years/cluster ids differ) so the figures can never drift from the paper
tables; build_trajectories cross-checks the result against the shipped
robustness artifact. matplotlib is imported lazily inside the functions to
keep ``import acc`` cheap.
"""
import re

import pandas as pd

from . import config

CMAP_NAME = 'RdBu_r'
TOP_N = 10
TRAJ_N = 8        # trajectories per panel (fewer than TOP_N: legibility over coverage)
Y_AXIS_PAD = 40


def _study_label(cid, fallback):
    """Curated study-corpus label for a cluster id.

    cluster_names.json (acc.cluster.short_label) names the EXTENDED joint
    clustering — its ids don't apply to the study corpus, so the curated
    READABLE_LABELS (reviewed against these 80 clusters) are used instead.
    """
    n = config.READABLE_LABELS.get(int(cid))
    return n[0] if n else fallback


def build_butterfly():
    """Diverging horizontal bar chart of the top declining/growing clusters."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.colors as mcolors
    import matplotlib.pyplot as plt

    df = pd.read_csv(config.STUDY_CLUSTERS)
    years = sorted(df['year'].unique())
    start, end = years[0], years[-1]
    total_start = df[df['year'] == start]['paper_id'].nunique()
    total_end = df[df['year'] == end]['paper_id'].nunique()
    print(f"papers {start}: {total_start}, {end}: {total_end}")

    df_clean = df[df['cluster'] != -1]
    counts = (
        df_clean[df_clean['year'].isin([start, end])]
        .groupby(['cluster', 'year'])['paper_id'].nunique()
        .unstack(fill_value=0)
        .reindex(columns=[start, end], fill_value=0)
    )
    counts['pct_start'] = counts[start] / total_start * 100
    counts['pct_end'] = counts[end] / total_end * 100
    counts['delta'] = counts['pct_end'] - counts['pct_start']
    counts['shift_label'] = counts.apply(
        lambda x: f"{x['pct_start']:.1f}% → {x['pct_end']:.1f}%", axis=1)

    drift_sorted = counts.sort_values('delta', ascending=True)
    plot_data = pd.concat([drift_sorted.head(TOP_N), drift_sorted.tail(TOP_N)])
    raw_name = df_clean.groupby('cluster')['cluster_name'].first()
    plot_data.index = [_study_label(int(cid), str(raw_name.get(int(cid), cid))).upper()
                       for cid in plot_data.index]
    print(plot_data[['pct_start', 'pct_end', 'delta']].round(1).to_string())

    fig, ax = plt.subplots(figsize=(13, 9))
    norm = mcolors.TwoSlopeNorm(vmin=plot_data['delta'].min(), vcenter=0,
                                vmax=plot_data['delta'].max())
    cmap = plt.get_cmap(CMAP_NAME)
    colors = [cmap(norm(val)) for val in plot_data['delta']]
    bars = ax.barh(plot_data.index, plot_data['delta'], color=colors,
                   height=1.0, edgecolor='white', linewidth=1)

    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xticks([])
    ax.tick_params(axis='y', length=0, labelsize=11, pad=Y_AXIS_PAD)

    for bar, value, shift_text in zip(bars, plot_data['delta'], plot_data['shift_label']):
        width = bar.get_width()
        delta_text = f"{value:+.1f}%"
        text_color = cmap(0.1) if value < 0 else cmap(0.9)
        grey_text = '#666666'
        if value < 0:
            ax.text(width - 0.3, bar.get_y() + bar.get_height() / 2, delta_text,
                    va='center', ha='right', fontsize=11, fontweight='bold', color=text_color)
            ax.text(0.4, bar.get_y() + bar.get_height() / 2, shift_text,
                    va='center', ha='left', fontsize=10, color=grey_text, family='monospace')
        else:
            ax.text(width + 0.3, bar.get_y() + bar.get_height() / 2, delta_text,
                    va='center', ha='left', fontsize=11, fontweight='bold', color=text_color)
            ax.text(-0.4, bar.get_y() + bar.get_height() / 2, shift_text,
                    va='center', ha='right', fontsize=10, color=grey_text, family='monospace')

    plt.subplots_adjust(top=0.7, bottom=0.02, left=0.1, right=0.98)
    out = config.ARTIFACTS / 'drift_chart_butterfly.pdf'
    plt.savefig(out, format='pdf', dpi=300, bbox_inches='tight', pad_inches=0.01)
    print(f'Saved {out}')


def _spread(values, min_gap):
    """Nudge label y-positions apart (input order arbitrary)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = list(values)
    prev = None
    for i in order:
        if prev is not None and out[i] - prev < min_gap:
            out[i] = prev + min_gap
        prev = out[i]
    return out


def build_trajectories():
    """Two-panel per-year DF trajectories for top declining/growing clusters."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    df = pd.read_csv(config.STUDY_CLUSTERS)
    years = sorted(df['year'].unique())
    papers_per_year = df.groupby('year')['paper_id'].nunique().reindex(years)
    print('papers per year:\n', papers_per_year.to_string())

    dfc = df[df['cluster'] != -1]
    traj = (
        dfc.groupby(['cluster', 'year'])['paper_id'].nunique()
        .unstack(fill_value=0)
        .reindex(columns=years, fill_value=0)
        .div(papers_per_year, axis=1) * 100
    )
    traj['delta'] = traj[years[-1]] - traj[years[0]]

    declining = traj.nsmallest(TRAJ_N, 'delta')
    growing = traj.nlargest(TRAJ_N, 'delta')

    # -- Cross-check against the robustness artifact --------------------------
    if config.HEADLINE_TRAJ.exists():
        rob = pd.read_csv(config.HEADLINE_TRAJ)
        rob['traj_vals'] = rob['traj'].apply(
            lambda s: [float(x) for x in re.findall(r'([\d.]+)\)', s)])
        mismatches = 0
        for _, row in rob.iterrows():
            ours = [round(v, 1) for v in traj.loc[row['cid'], years]]
            theirs = [round(v, 1) for v in row['traj_vals']]
            if ours != theirs:
                mismatches += 1
                print(f"MISMATCH cid={row['cid']} ({row['cluster']}): {ours} vs {theirs}")
        print(f"cross-check vs robustness artifact: "
              f"{len(rob) - mismatches}/{len(rob)} headline clusters match exactly")
        assert mismatches == 0, "primary-data trajectories disagree with robustness artifact"

    # -- Plot ------------------------------------------------------------------
    name_map = pd.Series(
        {cid: _study_label(int(cid), n)
         for cid, n in dfc.groupby('cluster')['cluster_name'].first().items()})

    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2))
    # Label each line at the side where the clusters fan OUT, not where they
    # converge: declining clusters are well separated at their high 2020 values
    # (left), growing clusters at their high 2025 values (right). Labels live in
    # in-axes whitespace on that side, and the y-axis ticks move to the OPPOSITE
    # side of each panel so names never collide with the tick numbers.
    panels = [
        (axes[0], declining, plt.cm.Reds, 'Declining clusters', 'left'),
        (axes[1], growing, plt.cm.Greens, 'Growing clusters', 'right'),
    ]
    for ax, sub, cmap_name, title, side in panels:
        n = len(sub)
        anchor_year = years[0] if side == 'left' else years[-1]
        anchor_vals = [row[anchor_year] for _, row in sub.iterrows()]
        span = max(sub[years].to_numpy().max(), 1)
        label_y = _spread(anchor_vals, min_gap=span * 0.075)
        if side == 'left':
            ax.set_xlim(2016.2, 2025.4)        # left whitespace for labels
            ax.yaxis.tick_right()              # ticks out of the label zone
            label_x, ha, hide = 2019.55, 'right', 'left'
            note_x, note_ha = 1.0, 'right'
        else:
            ax.set_xlim(2019.6, 2028.8)        # right whitespace for labels
            label_x, ha, hide = 2025.45, 'left', 'right'
            note_x, note_ha = 0.0, 'left'
        # darkest -> lightest by descending fan-out value, so adjacent lines
        # differ in shade as well as position
        order = sorted(range(n), key=lambda i: -anchor_vals[i])
        shade = {idx: 0.92 - 0.60 * rank / max(n - 1, 1)
                 for rank, idx in enumerate(order)}
        for i, (cid, row) in enumerate(sub.iterrows()):
            color = cmap_name(shade[i])
            ax.plot(years, row[years], color=color, lw=1.8,
                    marker='o', ms=2.8, zorder=3)
            ax.annotate(name_map[cid],
                        xy=(anchor_year, anchor_vals[i]),
                        xytext=(label_x, label_y[i]),
                        fontsize=7.4, color=color, va='center', ha=ha,
                        arrowprops=dict(arrowstyle='-', color=color,
                                        lw=0.5, alpha=0.55))
        ax.set_title(title, fontsize=10.5, pad=14)
        ax.set_xticks(years)
        ax.tick_params(labelsize=8)
        ax.set_ylim(bottom=-0.3)
        for spine in ['top', hide]:
            ax.spines[spine].set_visible(False)
        ax.grid(axis='y', lw=0.3, alpha=0.4)
        ax.text(note_x, 1.04, '% of papers (document frequency)',
                transform=ax.transAxes, fontsize=7.5, color='#555555', ha=note_ha)

    plt.tight_layout(w_pad=3.0)
    out = config.ARTIFACTS / 'drift_trajectories.pdf'
    plt.savefig(out, bbox_inches='tight', pad_inches=0.03)
    out_png = config.ARTIFACTS / 'drift_trajectories.png'
    plt.savefig(out_png, dpi=200, bbox_inches='tight', pad_inches=0.03)
    print(f'Saved {out}')
    print(f'Saved {out_png}')
    print('\nDeclining:')
    print(pd.DataFrame({'label': name_map[declining.index],
                        'delta_pp': declining['delta'].round(1)}).to_string(index=False))
    print('\nGrowing:')
    print(pd.DataFrame({'label': name_map[growing.index],
                        'delta_pp': growing['delta'].round(1)}).to_string(index=False))
