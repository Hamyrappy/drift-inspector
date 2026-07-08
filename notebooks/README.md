# Notebooks

Analysis and validation notebooks that run **on top of** the pipeline outputs.
The pipeline itself — download → extract → cluster → name → build-inspector — is
the `acc` CLI (`uv run acc …`), not a notebook; see the repo [README](../README.md).
Every notebook opens with a repo-root bootstrap cell, so it runs from any kernel
cwd and all paths are relative to the repo root.

| Notebook | Role | Related `acc` command |
|---|---|---|
| [`analysis.ipynb`](analysis.ipynb) | The paper's EMNLP 2020–2025 drift analysis: SPECTER2 → UMAP → HDBSCAN on the balanced EMNLP claim sample, cluster inspection, drift figures (butterfly, growth table, stacked area) and SToP external validation. | figures overlap `acc figures`; site data is `acc all` |
| [`human_validation.ipynb`](human_validation.ipynb) | Human + LLM-as-judge validation of ACC extraction: builds the annotator / master sheets, runs the judge, reports agreement (Fleiss' κ = 0.844 across three annotators, drop-Unsure convention). Reads/writes `artifacts/human_validation/*.csv`. | `acc judge --validation` (needs the internal master sheet, which is not shipped — the agreement numbers reproduce from the shipped annotator sheets via this notebook) |
| [`baseline_comparison.ipynb`](baseline_comparison.ipynb) | ACC vs classical topic models (LDA / NMF / BERTopic / SentSPECTER) on coherence, diversity and SToP alignment. Writes `artifacts/baseline/`. | — (research) |

## ⚠ Notebook corpus ≠ canonical clusters

`analysis.ipynb` and `baseline_comparison.ipynb` were written for the
**EMNLP-only** corpus (≈16.5k claims, 80 clusters, HDBSCAN `min_cluster_size=25`)
and still **re-derive their own** embedding + clustering inline — this is the
corpus every number in the paper is computed on. The canonical
`data/clusters/acc_clusters.csv` is the **joint 6-venue** corpus
(ACL + EMNLP + NAACL + EACL + COLING + AACL, ≈70k claims, 88 clusters,
`min_cluster_size=115`). These are
two different analyses — do **not** assume the notebook figures match the
canonical / Inspector clustering. Pointing the notebooks at `acc.corpus`
(`load_clustering_corpus`) / the shared caches is deliberate follow-up, not yet
done: naively reusing `acc.embed` here would overwrite the canonical embedding
cache (different row count), so the dedup needs the corpus question resolved first.

## Retired

`extraction_validation.ipynb` (older standalone Yandex LLM-judge →
`claims_validation_results.csv`) was superseded by `acc judge` / `acc filter` and
the judge section of `human_validation.ipynb`; it was retired to the project's
internal archive.
