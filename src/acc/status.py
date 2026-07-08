"""
Pipeline status: which artifacts exist and whether they are fresh.

Shared by the CLI (`acc status`) and the TUI (`acc ui`). "Fresh" means every
output exists and is newer than every input that exists; "stale" means an input
was modified after an output; "missing" means an output isn't there yet.
"""
import json

from . import config


def _clustering_source_files(name):
    """<source>/<name>.csv for every manifest-registered clustering source."""
    try:
        manifest = json.loads(config.MANIFEST.read_text(encoding="utf-8"))
        sources = manifest["clustering"]["sources"]
    except (OSError, KeyError, json.JSONDecodeError):
        return []
    return [config.CLAIMS_SOURCES_DIR / s / f"{name}.csv" for s in sources]


def stages():
    """(key, label, [outputs], [inputs], how-to-produce) rows."""
    papers = _clustering_source_files("papers")
    claims = _clustering_source_files("claims")
    return [
        ("corpus",   "Corpus download",        papers,                 [],                                          "acc download"),
        ("claims",   "ACC extraction",         claims,                 papers,                                      "acc extract"),
        ("clusters", "Clustering (canonical)", [config.ACC_CLUSTERS],  claims,                                      "acc cluster"),
        ("embed",    "SPECTER2 cache",         [config.EMB_CACHE],     [config.ACC_CLUSTERS],                       "acc embed"),
        ("project",  "UMAP 2D cache",          [config.UMAP2D_CACHE],  [config.EMB_CACHE],                          "acc project"),
        ("data",     "Inspector data",         [config.DATA_JSON],     [config.ACC_CLUSTERS, config.UMAP2D_CACHE],  "acc build-inspector"),
        ("portable", "Portable HTML",          [config.PORTABLE_HTML], [config.DATA_JSON],                          "acc bake"),
    ]


def _mtime(p):
    return p.stat().st_mtime if p.exists() else None


def stage_state(outputs, inputs):
    if not outputs or not all(o.exists() for o in outputs):
        return "missing"
    out_m = min(_mtime(o) for o in outputs)
    if any((m := _mtime(i)) is not None and m > out_m for i in inputs):
        return "stale"
    return "fresh"


def pipeline_status():
    """List of stage dicts: key, label, outputs, inputs, how, state, size."""
    rows = []
    for key, label, outputs, inputs, how in stages():
        rows.append(dict(
            key=key, label=label, outputs=outputs, inputs=inputs, how=how,
            state=stage_state(outputs, inputs),
            size=sum(o.stat().st_size for o in outputs if o.exists()),
        ))
    return rows
