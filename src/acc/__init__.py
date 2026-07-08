"""
acc — the Atomic Contribution Claims / Drift Inspector pipeline.

The reproducible spine of the project. Interactive steps (corpus download, LLM
extraction) stay in notebooks; the deterministic, locally-reproducible steps
live here and are driven by the ``acc`` CLI (see acc.cli) and the ``acc ui``
dashboard (see acc.tui).

Pipeline:
    corpus  -> embed -> project (UMAP 2D) -> inspector.build_data -> inspector.bake
    (cluster / figures / robustness are analysis branches off the same corpus)
"""
from .config import SCHEMA_VERSION
from .corpus import load_canonical_corpus
from .embed import embed_claims
from .project import umap_2d
from .inspector import build_data, bake

__version__ = SCHEMA_VERSION

__all__ = [
    "load_canonical_corpus",
    "embed_claims",
    "umap_2d",
    "build_data",
    "bake",
    "SCHEMA_VERSION",
    "__version__",
]
