"""
Joint clustering across venues.

Runs the canonical UMAP-5D + HDBSCAN recipe over the union of the venues' claims
(reusing the per-source SPECTER2 embedding caches when present; on a fresh
clone missing caches are recomputed from the shipped per-source claims),
producing a single shared topic space so conferences are compared natively
rather than overlaid. Writes:

  * ``data/clusters/acc_clusters.csv`` — claim_id, paper_id, year, venue, cluster
    (the new multi-venue canonical), and
  * the aligned ``acc_specter2_embeddings.npy`` / ``acc_umap5d.npy`` /
    ``acc_umap2d.npy`` caches (row order == acc_clusters.csv).

Cluster ids are re-labelled by descending size (0 = largest; noise = -1), so the
size-ordered palette and any id-referencing stays stable across re-runs.
The EMNLP source keeps its historical balanced subsample + cache; other venues
are taken in full (already ~748 papers/year from extraction).
"""
import numpy as np
import pandas as pd

from . import config
from . import corpus

_COLS = ["claim_id", "paper_id", "year", "atomic_claim", "venue"]


def _assemble():
    """(corpus_df, E) for all display venues, aligned row-for-row to E."""
    manifest = corpus.load_manifest()
    ids = manifest["display"]["sources"]
    parts, embs = [], []
    for sid in ids:
        if sid == "emnlp":
            df = corpus.load_clustering_corpus()          # balanced 16,576, EMB_CACHE order
            E = np.load(config.EMB_CACHE)
        else:
            s = next(x for x in manifest["sources"] if x["id"] == sid)
            df = corpus.read_source_claims(s)             # all claims, emb_<sid> order
            cache = config.ARTIFACTS / f"emb_{sid}.npy"
            if not cache.exists():
                # Fresh clone: per-source embedding caches are regenerable, not
                # shipped — recompute from the source's claims (row order = df).
                from .embed import embed_claims
                E = embed_claims(df["atomic_claim"].tolist(), cache=cache)
            else:
                E = np.load(cache)
        df = df[[c for c in _COLS if c in df.columns]].reset_index(drop=True)
        if len(df) != len(E):
            raise RuntimeError(f"{sid}: claims={len(df)} vs emb={len(E)} misaligned")
        parts.append(df)
        embs.append(np.asarray(E, dtype=np.float32))
        print(f"  {sid}: {len(df)} claims")
    return pd.concat(parts, ignore_index=True), np.vstack(embs)


def _relabel_by_size(labels: np.ndarray) -> np.ndarray:
    """Re-map cluster ids so 0 = largest cluster (noise stays -1)."""
    ids = [c for c in np.unique(labels) if c != -1]
    order = sorted(ids, key=lambda c: -(labels == c).sum())
    remap = {c: i for i, c in enumerate(order)}
    remap[-1] = -1
    return np.array([remap[c] for c in labels])


def _caches_consistent():
    """True if acc_clusters + emb + 5D UMAP all exist and share a row count."""
    if not (config.ACC_CLUSTERS.exists() and config.EMB_CACHE.exists()
            and config.UMAP5D_CACHE.exists()):
        return False
    n = len(pd.read_csv(config.ACC_CLUSTERS, usecols=["claim_id"]))
    return len(np.load(config.EMB_CACHE, mmap_mode="r")) == n \
        and len(np.load(config.UMAP5D_CACHE, mmap_mode="r")) == n


def run_clustering(reassemble=False):
    import umap
    import hdbscan
    import warnings
    warnings.filterwarnings("ignore")

    if not reassemble and _caches_consistent():
        # Re-cluster from cached UMAP-5D (fast) — e.g. tuning HDBSCAN params.
        print("Re-clustering from cached UMAP-5D (embeddings unchanged)...")
        corpus_df = pd.read_csv(config.ACC_CLUSTERS)[["claim_id", "paper_id", "year", "venue"]]
        E = np.load(config.EMB_CACHE)
        u5 = np.load(config.UMAP5D_CACHE)
        u2 = np.load(config.UMAP2D_CACHE)
    else:
        print("Assembling multi-venue corpus + embeddings...")
        corpus_df, E = _assemble()
        print(f"Total: {len(corpus_df)} claims, {E.shape[1]}-d embeddings")
        print("UMAP -> 5D (clustering projection)...")
        u5 = umap.UMAP(**config.UMAP_5D).fit_transform(E)
        print("UMAP -> 2D (map projection)...")
        u2 = np.round(umap.UMAP(**config.UMAP_2D).fit_transform(E), 3)

    print("HDBSCAN...")
    labels = _relabel_by_size(hdbscan.HDBSCAN(**config.HDBSCAN_PARAMS).fit_predict(u5))

    corpus_df = corpus_df.copy()
    corpus_df["cluster"] = labels.astype(int)
    corpus_df["cluster_name"] = ""

    out = corpus_df[["claim_id", "paper_id", "year", "venue", "cluster", "cluster_name"]]
    config.ACC_CLUSTERS.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(config.ACC_CLUSTERS, index=False)
    np.save(config.EMB_CACHE, E)
    np.save(config.UMAP5D_CACHE, u5)
    np.save(config.UMAP2D_CACHE, u2)

    n = len(set(labels)) - (1 if -1 in labels else 0)
    print(f"\nWrote {config.ACC_CLUSTERS}: {len(out)} claims · {n} clusters + noise "
          f"({(labels == -1).mean():.1%})")
    by_v = out[out.cluster != -1].groupby("venue")["cluster"].nunique()
    print("clusters touched per venue:", by_v.to_dict())
    return out
