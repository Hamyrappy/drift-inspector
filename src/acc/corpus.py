"""
Manifest-driven corpus loader.

Claim data lives under ``data/claims_sources/`` as a set of sources, each a
``{claims.csv, papers.csv, meta.json}`` folder, registered in ``manifest.json``
with roles (``clustering`` / ``display`` / ``compare``). This module assembles:

  * ``load_clustering_corpus()`` — the union of ``clustering`` sources, balanced
    (seed 42) and bound positionally to the canonical ``acc_clusters.csv``. This
    is what was embedded + clustered; the row order is load-bearing (the cached
    embeddings align to it), so the balancing + alignment checks live here.
  * ``load_display_corpus()`` — adds ``display``-only sources (e.g. other venues)
    whose claims are assigned to existing clusters post-hoc (see acc.testconf).
  * ``load_canonical_corpus()`` — backwards-compatible alias kept for the embed /
    project / build-inspector steps, identical to ``load_clustering_corpus()``.
"""
import json

import pandas as pd

from . import config


# --------------------------- manifest helpers --------------------------------
def load_manifest() -> dict:
    with open(config.MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def _resolve(rel: str):
    """Resolve a manifest-relative path against the claims_sources dir."""
    return (config.CLAIMS_SOURCES_DIR / rel).resolve()


def save_manifest(manifest: dict):
    with open(config.MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def register_source(entry: dict, *, display: bool = True):
    """Add or replace a source in manifest.json (and its display membership)."""
    config.MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    if config.MANIFEST.exists():
        manifest = load_manifest()
    else:
        manifest = {"schema_version": "2.0", "sources": [],
                    "clustering": {"sources": [], "clusters_file": "../clusters/acc_clusters.csv",
                                   "balance": {"papers_per_year": config.TARGET_PAPERS_PER_YEAR,
                                               "seed": config.BALANCE_RANDOM_SEED,
                                               "years": list(config.YEARS)}},
                    "display": {"sources": []}}
    manifest["sources"] = [s for s in manifest["sources"] if s["id"] != entry["id"]] + [entry]
    if display:
        disp = manifest.setdefault("display", {}).setdefault("sources", [])
        if entry["id"] not in disp:
            disp.append(entry["id"])
    save_manifest(manifest)
    return manifest


def sources_with_role(role: str, manifest: dict | None = None) -> list[dict]:
    m = manifest or load_manifest()
    return [s for s in m["sources"] if role in s.get("roles", [])]


def read_source_claims(source: dict) -> pd.DataFrame:
    """A source's claims tagged with its id + venue (row order preserved)."""
    claims = pd.read_csv(_resolve(source["paths"]["claims"]))
    claims["source"] = source["id"]
    claims["venue"] = source.get("venue", source["id"])
    return claims


def read_source_papers(source: dict) -> pd.DataFrame:
    return pd.read_csv(_resolve(source["paths"]["papers"]))


# ----------------------------- clustering corpus -----------------------------
def load_clustering_corpus() -> pd.DataFrame:
    """The jointly-clustered multi-venue corpus.

    Reads the canonical ``acc_clusters.csv`` (``claim_id, paper_id, year, venue,
    cluster``) produced by ``acc cluster`` and joins claim text + paper metadata
    by ``claim_id`` / ``paper_id``. Row order == acc_clusters.csv == the cached
    embedding / UMAP arrays, so downstream stays positionally aligned.
    """
    acc = pd.read_csv(config.ACC_CLUSTERS)
    acc["year"] = acc["year"].astype(int)
    manifest = load_manifest()
    # acc_clusters.csv's claim_ids / paper_ids come *only* from the clustering
    # sources, so the text + paper-meta joins read exactly those. (Overlay
    # display sources — other venues assigned post-hoc — are loaded separately
    # by the inspector and may not even be extracted yet.)
    clust = [s for s in manifest["sources"] if s["id"] in manifest["clustering"]["sources"]]

    txt = pd.concat([read_source_claims(s)[["claim_id", "atomic_claim"]] for s in clust],
                    ignore_index=True).drop_duplicates("claim_id")
    df = acc.merge(txt, on="claim_id", how="left")
    missing = int(df["atomic_claim"].isna().sum())
    if missing:
        raise RuntimeError(f"{missing} clustered claim_ids have no text — "
                           f"manifest clustering sources out of sync with acc_clusters.csv")

    df = _attach_paper_meta(df, clust)
    df = _attach_display_label(df)
    print(f"Clustering corpus: {len(df)} claims across {df['venue'].nunique()} venue(s), "
          f"{df['cluster'].nunique() - 1} clusters + noise "
          f"({(df['cluster'] == -1).mean():.1%} noise)")
    return df


# --------------------------- shared attach helpers ---------------------------
def _attach_paper_meta(df: pd.DataFrame, sources: list[dict]) -> pd.DataFrame:
    """Left-join paper-level metadata (title/authors/…); preserves order.

    Columns already present on ``df`` (e.g. ``venue`` from acc_clusters.csv) are
    not clobbered by the papers table.
    """
    papers = pd.concat([read_source_papers(s) for s in sources], ignore_index=True)
    papers = papers.drop_duplicates(subset="paper_id")
    keep = [c for c in ["paper_id", "title", "venue", "track", "url",
                        "authors", "author_ids"] if c in papers.columns]
    papers = papers[keep]
    dup = [c for c in papers.columns if c != "paper_id" and c in df.columns]
    if dup:
        papers = papers.drop(columns=dup)
    out = df.merge(papers, on="paper_id", how="left", validate="many_to_one")
    # Back-compat: downstream (inspector.build_data) reads `original_title`.
    out["original_title"] = out["title"].astype(str)
    return out


def _attach_display_label(df: pd.DataFrame) -> pd.DataFrame:
    from . import cluster as _cluster
    names = _cluster.load_cluster_names()           # LLM names (id -> {short,full})
    df["cluster_display"] = [
        (names[int(c)]["short"] if int(c) in names else "noise" if int(c) == -1 else f"cluster {int(c)}")
        for c in df["cluster"]]
    return df


# ------------------------------ display corpus -------------------------------
def load_display_corpus() -> pd.DataFrame:
    """Clustering corpus + assigned display-only sources (e.g. other venues).

    Display-only sources carry no canonical cluster; their assignments are
    produced post-hoc by ``acc.testconf`` and written to
    ``<source>/clusters.csv``. Until that exists, this returns the clustering
    corpus unchanged (so the current single-venue demo is unaffected).
    """
    manifest = load_manifest()
    base = load_clustering_corpus()
    base["assigned"] = False

    clustering_ids = set(manifest["clustering"]["sources"])
    extra = [s for s in sources_with_role("display", manifest)
             if s["id"] not in clustering_ids]
    frames = [base]
    for s in extra:
        assigned_path = _resolve(s["paths"].get("clusters", f'{s["id"]}/clusters.csv'))
        if not assigned_path.exists():
            continue  # not assigned yet (P3)
        claims = read_source_claims(s)
        asg = pd.read_csv(assigned_path)  # claim_id, cluster
        claims = claims.merge(asg[["claim_id", "cluster"]], on="claim_id", how="inner")
        claims["cluster_name"] = ""
        claims = _attach_paper_meta(claims, [s])
        claims = _attach_display_label(claims)
        claims["assigned"] = True
        frames.append(claims)
    return pd.concat(frames, ignore_index=True)


# ------------------------------ back-compat ----------------------------------
def load_canonical_corpus() -> pd.DataFrame:
    """Deprecated alias: identical to ``load_clustering_corpus()``."""
    return load_clustering_corpus()
