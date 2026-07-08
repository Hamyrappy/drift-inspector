"""
Export the public Drift Inspector subset (for the EMNLP submission / a public
`drift-inspector` repo). Copies the deployable site, the reproducible pipeline,
the canonical claim dataset, and the artifacts the paper promises to release
(baseline metrics, human-validation protocol + de-identified sheets, encoder and
extractor ablations, robustness grid). Deliberately omits the large regenerable /
third-party data (SToP taxonomy, cached embeddings) and the full ACL-Anthology
claim dump (346k claims, ~120 MB) which is distributed separately on Hugging Face.
Nothing is deleted from the source repo.
"""
import shutil
import subprocess
from pathlib import Path

from . import config

# The paper-study EMNLP instance (deployed at …/drift-inspector-emnlp/) is a
# hybrid: the *current* frontend + the EMNLP-only acc_data.json pinned at the
# submission build. Verified working (Compare keyword/author cohorts OK; venue
# cohorts need points.source, which the EMNLP data predates — by design).
EMNLP_DATA_COMMIT = "44b166f"

# Per-venue claim sources to ship: the manifest's clustering set (the 6 *ACL main
# tracks that back the canonical joint clustering) PLUS emnlp_full, which backs the
# extractor ablation. The full-anthology dump (data/claims_sources/anthology/, ~120 MB)
# and the superseded legacy folders are intentionally excluded — see EXCLUDED_NOTE.
_CLAIMS_SOURCES = ["acl_all", "emnlp_all", "naacl_all", "eacl_all", "coling_all", "aacl_all", "emnlp_full"]

# (path relative to repo root, path relative to export root)
INCLUDE = [
    ("inspector", "inspector"),                       # the deployable site
    ("drift_inspector_v5.html", "drift_inspector_v5.html"),  # portable build
    ("src/acc", "src/acc"),                           # pipeline package
    ("pyproject.toml", "pyproject.toml"),
    ("uv.lock", "uv.lock"),
    (".python-version", ".python-version"),
    ("notebooks", "notebooks"),                       # analysis + validation + baselines + CLI walkthroughs
    ("landing", "landing"),                           # project landing page source (deployed at /drift-inspector/)
    ("PUBLIC_RELEASE_README.md", "README.md"),        # public README
    ("LICENSE", "LICENSE"),
    ("CITATION.cff", "CITATION.cff"),

    # --- README figures ---
    ("artifacts/drift_inspector_v5.png", "docs/drift_inspector_v5.png"),
    ("artifacts/compare_overtime_bert_llm.png", "docs/compare_overtime_bert_llm.png"),

    # --- canonical claim dataset (the paper's EMNLP corpus) ---
    ("data/claims/openrouter_claims.csv", "data/claims/openrouter_claims.csv"),
    ("data/clusters/acc_clusters.csv", "data/clusters/acc_clusters.csv"),
    ("data/clusters/cluster_names.json", "data/clusters/cluster_names.json"),
    ("data/clusters/sent_clusters.csv", "data/clusters/sent_clusters.csv"),
    ("data/claims_sources/manifest.json", "data/claims_sources/manifest.json"),

    # --- paper-promised released artifacts: baseline comparison (intrinsic + SToP) ---
    ("artifacts/baseline/full_comparison_table.tex", "artifacts/baseline/full_comparison_table.tex"),
    ("artifacts/baseline/stop_alignment_table.csv", "artifacts/baseline/stop_alignment_table.csv"),
    ("artifacts/baseline/acc_clusters_emnlp.csv", "artifacts/baseline/acc_clusters_emnlp.csv"),  # 16,576-claim corpus w/ clusters

    # --- robustness ---
    ("artifacts/robustness_grid.csv", "artifacts/robustness_grid.csv"),
    ("artifacts/robustness_grid_table.tex", "artifacts/robustness_grid_table.tex"),
    ("artifacts/robustness", "artifacts/robustness"),

    # --- ablations: encoder + extractor ---
    ("artifacts/audit/encoder_ablation_results.csv", "artifacts/audit/encoder_ablation_results.csv"),
    ("artifacts/audit/encoder_ablation_signs.csv", "artifacts/audit/encoder_ablation_signs.csv"),
    ("artifacts/audit/extractor_ablation_stop_results.csv", "artifacts/audit/extractor_ablation_stop_results.csv"),
    ("artifacts/audit/extractor_ablation_STOP_FINDINGS.md", "artifacts/audit/extractor_ablation_STOP_FINDINGS.md"),
    ("artifacts/audit/extractor_ablation_JUDGE_FINDINGS.md", "artifacts/audit/extractor_ablation_JUDGE_FINDINGS.md"),

    # --- human validation: protocol + de-identified sheets (no annotator names/emails) ---
    ("artifacts/human_validation/README.md", "artifacts/human_validation/README.md"),
    ("artifacts/human_validation/annotator_sheet-1.csv", "artifacts/human_validation/annotator_sheet-1.csv"),
    ("artifacts/human_validation/annotator_sheet-2.csv", "artifacts/human_validation/annotator_sheet-2.csv"),
    ("artifacts/human_validation/annotator_sheet-3.csv", "artifacts/human_validation/annotator_sheet-3.csv"),
    ("artifacts/human_validation/judge_results.csv", "artifacts/human_validation/judge_results.csv"),
]

# Optional ablation-hardening artifacts (present only after that experiment is run).
_OPTIONAL = [
    ("artifacts/audit/ablation_hardening_results.csv", "artifacts/audit/ablation_hardening_results.csv"),
    ("artifacts/audit/ablation_hardening_signs.csv", "artifacts/audit/ablation_hardening_signs.csv"),
]

# Per-venue claim sources, appended programmatically (see _CLAIMS_SOURCES).
INCLUDE += [(f"data/claims_sources/{s}", f"data/claims_sources/{s}") for s in _CLAIMS_SOURCES]
INCLUDE += _OPTIONAL

EXCLUDED_NOTE = [
    "data/claims_sources/anthology/ — full ACL-Anthology dump (346k claims, ~120 MB); ships on Hugging Face, not in this repo",
    "data/claims_sources/{acl,coling,emnlp,iwslt,lrec,ranlp,acl_full} — superseded / non-registered legacy extractions",
    "data/claims_sources/*/{meta.json,processed_papers.csv} — internal extraction bookkeeping",
    "data/external/ — SToP taxonomy (third-party, large)",
    "artifacts/*.npy — cached embeddings / UMAP (regenerable via `uv run acc embed`)",
    "artifacts/human_validation/{master_sheet*,bad_claims_pool*} — internal ground-truth construction",
    "paper/, paper_build/, archive/ — internal writing, changelogs, history",
]

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".ipynb_checkpoints", ".verify")

# Per-venue source folders ship only the dataset files (claims.csv / papers.csv);
# internal extraction bookkeeping (run provenance, per-paper processing logs)
# stays out of the public bundle.
_SOURCE_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".ipynb_checkpoints", ".verify",
    "meta.json", "processed_papers.csv")

# The public repo tracks its data and site files deliberately, so it gets its
# own minimal .gitignore instead of a copy of the internal one (which ignores
# *.csv/*.json/*.html and would hide the shipped datasets from `git add`).
PUBLIC_GITIGNORE = """\
# Drift Inspector — public repository.
# Datasets, JSON and the baked HTML build are tracked on purpose; only
# environment / cache junk is ignored here.
__pycache__/
*.py[cod]
.ipynb_checkpoints/
.venv*/
.env
.envrc
.DS_Store
Thumbs.db
# regenerable embedding / UMAP caches written into artifacts/ by `acc all`
*.npy
"""


def _scrub_notebooks(dest: Path):
    """Replace the author's absolute local paths in shipped notebook outputs."""
    prefix = str(config.ROOT).replace("\\", "/")
    variants = {prefix, prefix.replace("/", "\\"), prefix.replace("/", "\\\\")}
    variants |= {v[0].lower() + v[1:] for v in variants} | {v[0].upper() + v[1:] for v in variants}
    for nb in (dest / "notebooks").glob("*.ipynb"):
        text = nb.read_text(encoding="utf-8")
        scrubbed = text
        for v in variants:
            scrubbed = scrubbed.replace(v, "<repo>")
        if scrubbed != text:
            nb.write_text(scrubbed, encoding="utf-8")
            print(f"  (scrubbed local paths in notebooks/{nb.name})")


def _export_emnlp_instance(root: Path, dest: Path):
    """Assemble inspector-emnlp/: current frontend + pinned EMNLP acc_data.json."""
    dst = dest / "inspector-emnlp"
    shutil.copytree(root / "inspector", dst, dirs_exist_ok=True, ignore=_IGNORE)
    try:
        blob = subprocess.run(
            ["git", "show", f"{EMNLP_DATA_COMMIT}:inspector/data/acc_data.json"],
            cwd=root, capture_output=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        shutil.rmtree(dst, ignore_errors=True)
        print(f"  (WARNING: could not extract EMNLP data from git ({e}); inspector-emnlp/ skipped)")
        return None
    (dst / "data" / "acc_data.json").write_bytes(blob)
    # The pinned instance must use the monolith fallback — the split files
    # copied from inspector/ describe the *extended* corpus, not this one.
    for extra in ("acc_core.json", "acc_claims.json"):
        (dst / "data" / extra).unlink(missing_ok=True)
    return "inspector-emnlp"


def export_public(dest=None):
    root = config.ROOT
    dest = Path(dest).resolve() if dest else (root.parent / "drift-inspector-public")
    dest.mkdir(parents=True, exist_ok=True)

    copied, skipped = [], []
    optional_rels = {o[0] for o in _OPTIONAL}
    for src_rel, dst_rel in INCLUDE:
        src = root / src_rel
        dst = dest / dst_rel
        if not src.exists():
            if src_rel not in optional_rels:
                skipped.append(src_rel)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            ignore = _SOURCE_IGNORE if src_rel.startswith("data/claims_sources/") else _IGNORE
            shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)
        else:
            shutil.copy2(src, dst)
        copied.append(dst_rel)

    emnlp = _export_emnlp_instance(root, dest)
    if emnlp:
        copied.append(emnlp)
    (dest / ".gitignore").write_text(PUBLIC_GITIGNORE, encoding="utf-8")
    copied.append(".gitignore")
    _scrub_notebooks(dest)

    print(f"Exported public bundle -> {dest}\n")
    for c in copied:
        print(f"  + {c}")
    if skipped:
        print("\n  (WARNING: expected but missing in source: " + ", ".join(skipped) + ")")
    print("\nExcluded by design:")
    for e in EXCLUDED_NOTE:
        print(f"  - {e}")
    print("\nNext: cd into the bundle, `git init` + push to the public `drift-inspector`\n"
          "repo. Deploy scheme (see landing/README.md): landing/ -> /drift-inspector/,\n"
          "inspector-emnlp/ -> /drift-inspector-emnlp/, inspector/ -> /drift-inspector-acl/.\n")
    return dest
