"""
Drift Inspector data + portable build.

Two independent steps:
  * ``build_data()``  -> inspector/data/acc_data.json (points + cluster stats)
                         from the canonical clustering + cached 2D UMAP.
  * ``bake()``        -> a single self-contained HTML, inlining the inspector/
                         css/js/plotly/data so the demo runs offline.

The website in inspector/ is the source of truth; the baked HTML is always
regenerated, never hand-edited. The acc_data.json schema is documented in
config.SCHEMA_VERSION and consumed by inspector/js/data.js.
"""
import json
import os
import re

import numpy as np
import pandas as pd

from . import config
from .corpus import load_canonical_corpus
from .drift import drift_color_relative

YEARS = config.YEARS


MIN_AUTHOR_PAPERS = 3   # author must have >= this many display papers to be pickable


def _author_lists(papers_df):
    """paper_id -> (author_id list, author_name list) from a papers.csv frame."""
    aid, anm = {}, {}
    for r in papers_df.itertuples():
        pid = str(r.paper_id)
        aid[pid] = [a for a in str(getattr(r, 'author_ids', '') or '').split('; ') if a]
        anm[pid] = [a for a in str(getattr(r, 'authors', '') or '').split('; ') if a]
    return aid, anm


def build_data():
    df = load_canonical_corpus()
    if not config.UMAP2D_CACHE.exists():
        raise FileNotFoundError(
            f'{config.UMAP2D_CACHE} not found — run `acc project` (or `acc embed`'
            f' then `acc project`) once to create it')
    U = np.load(config.UMAP2D_CACHE)
    if len(U) != len(df):
        raise RuntimeError('UMAP cache length mismatch')
    df = df.copy()
    df['x'] = np.round(U[:, 0].astype(float), 3)
    df['y'] = np.round(U[:, 1].astype(float), 3)

    papers_per_year = (df.groupby('year')['paper_id'].nunique()
                       .reindex(YEARS).astype(int))

    # Automatic c-TF-IDF descriptors (short + full), recomputed live so the demo
    # carries both layers; curated manual names override via short/full_label.
    from . import cluster as naming
    desc = naming.compute_descriptors(df)
    names = naming.load_cluster_names()

    # ---- cluster stats (paper-level document frequency, % of papers) -------
    clusters = []
    dfc = df[df['cluster'] != -1]
    for cid, grp in dfc.groupby('cluster'):
        cid = int(cid)
        df_traj, papers_traj, claims_traj = [], [], []
        for y in YEARS:
            sub = grp[grp['year'] == y]
            n_papers = sub['paper_id'].nunique()
            df_traj.append(round(100.0 * n_papers / papers_per_year[y], 4))
            papers_traj.append(int(n_papers))
            claims_traj.append(int(len(sub)))
        slope = float(np.polyfit(np.asarray(YEARS, float),
                                 np.asarray(df_traj, float) / 100.0, 1)[0])
        tfidf_short, tfidf_full = desc[cid]
        clusters.append({
            'id': cid,
            'raw': tfidf_short,                       # short c-TF-IDF descriptor
            'tfidfFull': tfidf_full,                  # full c-TF-IDF descriptor
            'label': naming.short_label(cid, tfidf_short),    # map / list / legend
            'labelFull': naming.full_label(cid, tfidf_full),  # clusters-page title
            'reviewed': cid in names,
            'size': int(len(grp)),
            'papers': int(grp['paper_id'].nunique()),
            'df': df_traj,                      # % of papers per year
            'papersByYear': papers_traj,        # paper counts per year
            'claims': claims_traj,              # claim counts per year
            'deltaPp': round(df_traj[-1] - df_traj[0], 4),
            'rel': (round((df_traj[-1] - df_traj[0]) / df_traj[0], 4)
                    if df_traj[0] > 0 else None),
            'slope': round(slope, 6),
        })

    clusters.sort(key=lambda c: -c['size'])
    for i, c in enumerate(clusters):
        c['color'] = config.CLUSTER_PALETTE[i]   # size-ordered palette, as v3
        c['driftColor'] = drift_color_relative(c['df'][0], c['df'][-1])

    # ---- sources[] (per-venue stats) + venue -> source index ----------------
    # Display sources come in two flavours. *Clustered* sources are jointly
    # clustered into acc_clusters.csv, so their points and per-venue stats come
    # straight from `df`. *Overlay* sources are other venues assigned to the
    # existing clusters by nearest centroid (`acc assign` -> <src>/clusters.csv);
    # they are folded into the same points/papers/sources arrays below so every
    # venue is an equal, toggleable map layer and a selectable Compare cohort,
    # while the canonical cluster stats stay defined by the clustered corpus.
    from . import corpus as _corpus
    manifest = _corpus.load_manifest()
    src_by_id = {s['id']: s for s in manifest['sources']}
    clustering_ids = set(manifest['clustering']['sources'])
    disp_ids = [sid for sid in manifest['display']['sources'] if sid in src_by_id]

    def _resolve(rel):
        return (config.CLAIMS_SOURCES_DIR / rel).resolve()

    # Pre-load each assigned overlay source (claim text + cluster + xy + year and
    # its paper metadata). Sources not yet assigned are simply skipped.
    overlays = {}
    for sid in disp_ids:
        if sid in clustering_ids:
            continue
        paths = src_by_id[sid].get('paths', {})
        cl_path = _resolve(paths.get('clusters', f'{sid}/clusters.csv'))
        if not cl_path.exists():
            continue
        oc = pd.read_csv(_resolve(paths['claims']))
        asg = pd.read_csv(cl_path)                        # claim_id, cluster, x, y
        oc = oc.merge(asg, on='claim_id', how='inner')
        op = pd.read_csv(_resolve(paths['papers']), dtype=str).fillna('')
        overlays[sid] = {'claims': oc, 'papers': op}

    sources, venue_idx = [], {}
    for i, sid in enumerate(disp_ids):
        s = src_by_id[sid]
        venue = s.get('venue', sid)
        venue_idx[venue] = i
        if sid in clustering_ids:
            sub = df[df['venue'] == venue]
            role = 'clustered'
            n_papers, n_claims = int(sub['paper_id'].nunique()), int(len(sub))
            years = sorted(int(y) for y in sub['year'].unique())
            ppy = [int(sub[sub['year'] == y]['paper_id'].nunique()) for y in YEARS]
        else:
            role = 'overlay'
            oc = overlays.get(sid, {}).get('claims')
            if oc is not None and len(oc):
                n_papers, n_claims = int(oc['paper_id'].nunique()), int(len(oc))
                years = sorted(int(y) for y in oc['year'].unique())
                ppy = [int(oc[oc['year'] == y]['paper_id'].nunique()) for y in YEARS]
            else:
                n_papers = n_claims = 0; years = []; ppy = [0] * len(YEARS)
        sources.append({
            'id': sid, 'name': s.get('name', sid), 'venue': venue,
            'color': s.get('color', '#888888'), 'base': i == 0, 'role': role,
            'nPapers': n_papers, 'nClaims': n_claims,
            'years': years, 'papersPerYear': ppy,
        })

    # ---- points (columnar, all venues) + papers / titles / authors ----------
    from collections import Counter
    pids = df['paper_id'].astype(str).tolist()
    titles = df['original_title'].astype(str).tolist()
    venues_col = df['venue'].astype(str).tolist()
    zero = pd.Series([''] * len(df))
    aid_col = (df['author_ids'] if 'author_ids' in df.columns else zero).fillna('').astype(str).tolist()
    anm_col = (df['authors'] if 'authors' in df.columns else zero).fillna('').astype(str).tolist()
    paper_index, paper_list, title_list, authors_by_paper = {}, [], [], []
    pidx, srcidx = [], []
    aid_count, aid_name = Counter(), {}
    for k in range(len(df)):
        pid = pids[k]
        if pid not in paper_index:
            paper_index[pid] = len(paper_list)
            paper_list.append(pid)
            title_list.append(titles[k])
            ids = [a for a in aid_col[k].split('; ') if a]
            nms = [a for a in anm_col[k].split('; ') if a]
            authors_by_paper.append(ids)
            for a, nm in zip(ids, nms):
                aid_count[a] += 1
                aid_name.setdefault(a, nm)
        pidx.append(paper_index[pid])
        srcidx.append(venue_idx.get(venues_col[k], 0))

    # base (clustered) point columns
    px = df['x'].tolist(); py = df['y'].tolist()
    pyear = df['year'].astype(int).tolist()
    pcluster = df['cluster'].astype(int).tolist()
    pclaim = df['atomic_claim'].astype(str).tolist()

    # append overlay points; they share the global papers/titles/authors arrays
    # (paper ids are anthology ids, globally unique) so tooltips, paper links,
    # and the Compare cohorts all work with no frontend change.
    for sid in disp_ids:
        if sid not in overlays:
            continue
        oc, op = overlays[sid]['claims'], overlays[sid]['papers']
        sidx = venue_idx[src_by_id[sid].get('venue', sid)]
        title_by_pid = {str(r.paper_id): str(r.title) for r in op.itertuples()}
        oaid, oanm = _author_lists(op)
        for r in oc.itertuples():
            pid = str(r.paper_id)
            if pid not in paper_index:
                paper_index[pid] = len(paper_list)
                paper_list.append(pid)
                title_list.append(title_by_pid.get(pid, ''))
                ids = oaid.get(pid, [])
                authors_by_paper.append(ids)
                for a, nm in zip(ids, oanm.get(pid, [])):
                    aid_count[a] += 1
                    aid_name.setdefault(a, nm)
            px.append(round(float(r.x), 3)); py.append(round(float(r.y), 3))
            pyear.append(int(r.year)); pcluster.append(int(r.cluster))
            pclaim.append(str(r.atomic_claim)); pidx.append(paper_index[pid])
            srcidx.append(sidx)

    authors_index = {a: [aid_name.get(a, a), int(n)]
                     for a, n in aid_count.items() if n >= MIN_AUTHOR_PAPERS}

    points = {
        'x': px, 'y': py, 'year': pyear, 'cluster': pcluster,
        'paper': pidx, 'claim': pclaim, 'source': srcidx,
    }

    venues = [s['venue'] for s in sources]
    vstr = ' · '.join(venues) if len(venues) <= 3 else f'{len(venues)} venues'
    data = {
        'meta': {
            'title': 'Drift Inspector',
            'subtitle': f'{vstr} · {YEARS[0]}–{YEARS[-1]} · Atomic Contribution Claims',
            'years': YEARS,
            'papersPerYear': [int(papers_per_year[y]) for y in YEARS],
            'totalPapersPerYear': None,
            'claimsPerYear': [int((df['year'] == y).sum()) for y in YEARS],
            'nClaims': int(len(df)),
            'nClusters': len(clusters),
            'noiseShare': round(float((df['cluster'] == -1).mean()), 4),
            'anthologyBase': 'https://aclanthology.org/',
        },
        'clusters': clusters,
        'papers': paper_list,
        'titles': title_list,
        'points': points,
        'sources': sources,
        'authorsByPaper': authors_by_paper,
        'authorsIndex': authors_index,
    }

    config.DATA_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(config.DATA_JSON, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, separators=(',', ':'))
    print(f'Wrote {config.DATA_JSON} ({os.path.getsize(config.DATA_JSON)/1e6:.1f} MB), '
          f'{len(clusters)} clusters, {len(df)} points')

    # Split payload for the deployed site: a small "core" file paints the map
    # immediately; the claim texts + author tables (~75% of the bytes) load in
    # the background. data.js prefers the pair and falls back to the monolithic
    # acc_data.json when acc_core.json is absent — the baked build and the
    # pinned EMNLP instance keep using the monolith. Same schema otherwise.
    core = dict(data, points={k: v for k, v in points.items() if k != 'claim'})
    del core['authorsByPaper'], core['authorsIndex']
    heavy = {'claim': points['claim'],
             'authorsByPaper': authors_by_paper, 'authorsIndex': authors_index}
    for name, obj in (('acc_core.json', core), ('acc_claims.json', heavy)):
        path = config.DATA_JSON.parent / name
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, separators=(',', ':'))
        print(f'Wrote {path} ({os.path.getsize(path)/1e6:.1f} MB)')


def bake():
    insp = str(config.INSPECTOR)
    html = open(os.path.join(insp, 'index.html'), encoding='utf-8').read()

    def inline_css(m):
        path = m.group(1).split('?')[0]          # tolerate ?v= cache-busting
        css = open(os.path.join(insp, path), encoding='utf-8').read()
        return f'<style>\n{css}\n</style>'

    def inline_js(m):
        path = m.group(1).split('?')[0]          # tolerate ?v= cache-busting
        js = open(os.path.join(insp, path), encoding='utf-8').read()
        return f'<script>\n{js}\n</script>'

    html = re.sub(r'<link rel="stylesheet" href="([^"]+)"\s*/?>', inline_css, html)

    # Embed the data json BEFORE the app scripts (data.js picks it up).
    data_raw = open(config.DATA_JSON, encoding='utf-8').read().replace('</', '<\\/')
    embed = f'<script type="application/json" id="acc-data">{data_raw}</script>'
    html = html.replace('<!-- BAKE:DATA -->', embed)

    html = re.sub(r'<script src="([^"]+)"></script>', inline_js, html)

    with open(config.PORTABLE_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f'Baked portable build -> {config.PORTABLE_HTML} '
          f'({os.path.getsize(config.PORTABLE_HTML)/1e6:.1f} MB)')
