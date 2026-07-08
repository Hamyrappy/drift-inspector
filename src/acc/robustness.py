"""
UMAP/HDBSCAN hyperparameter robustness for the paper's EMNLP study corpus.

Re-embeds the study corpus with the SAME SPECTER2 model used by the demo
(into its own cache under artifacts/robustness/), sweeps the clustering
hyperparameters, and for each grid cell reports (a) agreement with the study
clustering (ARI/AMI) and (b) whether the 2020->2025 sign of each headline
theme's document frequency is preserved. Reads only shipped files
(config.STUDY_CLUSTERS + config.STUDY_CLAIMS_TEXT), so it reproduces the
published grid from a fresh clone of the public release.

Outputs:
    artifacts/robustness_grid.csv          (one row per grid cell)
    artifacts/robustness_grid_table.tex    (LaTeX table for the appendix)
"""
from itertools import product

import numpy as np
import pandas as pd

from . import config
from .embed import embed_claims


def load_aligned() -> pd.DataFrame:
    """The study clustering with claim text aligned by paper_id + claim order.

    Both files preserve the extraction's within-paper claim order and their
    per-paper claim counts match for all 4,488 papers, so the positional
    alignment is exact (the study file's claim_id is a row index, not the
    extraction's clm_* id — hence no direct join).
    """
    acc = pd.read_csv(config.STUDY_CLUSTERS)
    full = pd.read_csv(config.STUDY_CLAIMS_TEXT)
    fmap = {p: g["atomic_claim"].tolist() for p, g in full.groupby("paper_id")}
    acc = acc.copy()
    acc["order"] = acc.groupby("paper_id").cumcount()
    acc["text"] = acc.apply(
        lambda r: fmap.get(r.paper_id, [None] * 99)[r.order]
        if r.order < len(fmap.get(r.paper_id, [])) else None, axis=1)
    assert acc["text"].notna().all(), "text alignment failed"
    return acc


def run():
    import umap
    import hdbscan
    from sklearn.metrics import adjusted_rand_score, adjusted_mutual_info_score

    acc = load_aligned()
    papers = {y: acc[acc.year == y].paper_id.nunique()
              for y in sorted(acc.year.unique())}
    # Own cache: never touch the canonical (extended-corpus) embedding cache.
    config.ROBUSTNESS_DIR.mkdir(parents=True, exist_ok=True)
    E = embed_claims(acc["text"].tolist(),
                     cache=config.ROBUSTNESS_DIR / "study_specter2_embeddings.npy")

    def df_sign(labels, theme_members):
        # for a perturbed clustering, find the best-overlap cluster to the
        # canonical theme and return the 2020->2025 sign.
        best, bj = None, 0.0
        for c in set(labels):
            if c == -1:
                continue
            m = set(np.where(labels == c)[0])
            j = len(theme_members & m) / len(theme_members | m) if (theme_members | m) else 0
            if j > bj:
                bj, best = j, c
        if best is None:
            return 0
        idx = np.where(labels == best)[0]
        sub = acc.iloc[idx]
        d20 = sub[sub.year == 2020].paper_id.nunique() / papers[2020]
        d25 = sub[sub.year == 2025].paper_id.nunique() / papers[2025]
        return np.sign(d25 - d20)

    canon = acc["cluster"].values
    canon_sign = {}
    for cid in config.HEADLINE:
        sub = acc[acc.cluster == cid]
        d20 = sub[sub.year == 2020].paper_id.nunique() / papers[2020]
        d25 = sub[sub.year == 2025].paper_id.nunique() / papers[2025]
        canon_sign[cid] = np.sign(d25 - d20)
    theme_members = {cid: set(np.where(canon == cid)[0]) for cid in config.HEADLINE}

    grid = dict(n_neighbors=[30, 40, 50], n_components=[5, 10],
                min_cluster_size=[20, 25, 30], min_samples=[5, 10])
    rows = []
    for nn, nc, mcs, ms in product(grid["n_neighbors"], grid["n_components"],
                                   grid["min_cluster_size"], grid["min_samples"]):
        U = umap.UMAP(n_neighbors=nn, n_components=nc, metric="cosine",
                      random_state=42).fit_transform(E)
        lab = hdbscan.HDBSCAN(min_cluster_size=mcs, min_samples=ms,
                              cluster_selection_method="eom").fit_predict(U)
        mask = (canon != -1) & (lab != -1)
        ari = adjusted_rand_score(canon[mask], lab[mask])
        ami = adjusted_mutual_info_score(canon[mask], lab[mask])
        agree = sum(df_sign(lab, theme_members[cid]) == canon_sign[cid]
                    for cid in config.HEADLINE)
        rows.append(dict(n_neighbors=nn, n_components=nc, min_cluster_size=mcs,
                         min_samples=ms, k=len(set(lab)) - (1 if -1 in lab else 0),
                         noise=float(np.mean(lab == -1)), ARI=ari, AMI=ami,
                         sign_agree=f"{agree}/{len(config.HEADLINE)}"))
        print(rows[-1])

    out = pd.DataFrame(rows)
    config.ARTIFACTS.mkdir(parents=True, exist_ok=True)
    out.to_csv(config.ARTIFACTS / "robustness_grid.csv", index=False)
    with open(config.ARTIFACTS / "robustness_grid_table.tex", "w") as f:
        f.write(out.to_latex(index=False, float_format="%.3f"))
    n = len(config.HEADLINE)
    print("\nSummary: ARI %.3f-%.3f, headline sign agreement preserved in all %d "
          "cells where it equals %d/%d"
          % (out.ARI.min(), out.ARI.max(),
             (out.sign_agree == f"{n}/{n}").sum(), n, n))
