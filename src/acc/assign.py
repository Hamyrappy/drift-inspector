"""
Assign an overlaid source's claims to the existing clusters.

For venues that are NOT jointly clustered (e.g. ACL, COLING overlaid on the
EMNLP topic space), each claim is embedded with the same SPECTER2 encoder and
assigned to the nearest cluster centroid (cosine). A 2D position near the
assigned cluster's centroid (seeded jitter) lets the points sit on the map.
Writes ``data/claims_sources/<id>/clusters.csv`` (claim_id, cluster, x, y) — the
file the manifest's display/compare machinery reads.

This generalises ``acc.testconf`` to any source folder with a ``claims.csv``.
"""
import numpy as np
import pandas as pd

from . import config
from . import corpus
from . import embed as _embed


def _unit(M):
    n = np.linalg.norm(M, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return M / n


def assign_source(source_id, jitter_seed=42):
    src = config.CLAIMS_SOURCES_DIR / source_id
    claims = pd.read_csv(src / "claims.csv")
    if claims.empty:
        raise RuntimeError(f"{source_id}: claims.csv is empty — run `acc extract` first")

    # canonical (clustered) basis — embeddings, clusters, 2D, all aligned
    canon = corpus.load_clustering_corpus()
    emb = np.load(config.EMB_CACHE)
    u2d = np.load(config.UMAP2D_CACHE)
    if not (len(canon) == len(emb) == len(u2d)):
        raise RuntimeError(f"alignment: corpus={len(canon)} emb={len(emb)} umap={len(u2d)}")
    canon_cluster = canon["cluster"].to_numpy()

    # embed this source's claims (own cache)
    cache = config.ARTIFACTS / f"emb_{source_id}.npy"
    cemb = np.asarray(_embed.embed_claims(claims["atomic_claim"].astype(str).tolist(), cache=cache),
                      dtype=np.float64)

    cluster_ids = sorted(c for c in np.unique(canon_cluster) if c != -1)
    centroids = np.vstack([emb[canon_cluster == c].mean(axis=0) for c in cluster_ids])
    sims = _unit(cemb) @ _unit(centroids).T
    nearest = sims.argmax(axis=1)
    assigned = np.array([cluster_ids[i] for i in nearest])
    best = sims.max(axis=1)

    rng = np.random.default_rng(jitter_seed)
    cen2d = {c: u2d[canon_cluster == c].mean(axis=0) for c in cluster_ids}
    std2d = {c: u2d[canon_cluster == c].std(axis=0) for c in cluster_ids}
    xy = np.zeros((len(assigned), 2))
    for i, c in enumerate(assigned):
        xy[i] = cen2d[c] + rng.normal(0, 1, 2) * 0.5 * std2d[c]
    xy = np.round(xy, 3)

    pd.DataFrame({"claim_id": claims["claim_id"], "cluster": assigned,
                  "x": xy[:, 0], "y": xy[:, 1]}).to_csv(src / "clusters.csv", index=False)
    print(f"[{source_id}] assigned {len(assigned)} claims to {len(cluster_ids)} clusters; "
          f"mean cosine {best.mean():.3f} -> {src/'clusters.csv'}")
    return float(best.mean())
