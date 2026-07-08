"""
UMAP projection for the Drift Inspector map.

Owns the 2D projection and its cache. Previously this lived inside
build_inspector.py (the "v3" script), which made the current build depend on a
script we want to retire; it now belongs to the pipeline package proper.

``umap_2d`` accepts a params/cache override so the multi-seed and native-space
experiments (REPORT_DRIFT_SPECTER2 §9, E2/E5/E11) can reuse it without touching
the canonical cache.
"""
import numpy as np

from . import config


def umap_2d(E: np.ndarray, params: dict = None, cache=None) -> np.ndarray:
    """2D UMAP for the map view (cached at config.UMAP2D_CACHE by default)."""
    cache = cache if cache is not None else config.UMAP2D_CACHE
    if cache.exists():
        U = np.load(cache)
        if len(U) == len(E):
            print(f"Using cached 2D projection: {cache}")
            return U

    import umap
    import warnings
    warnings.filterwarnings('ignore')
    print("Running UMAP (2 components for visualization)...")
    U = umap.UMAP(**(params or config.UMAP_2D)).fit_transform(E)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.save(cache, U)
    print(f"Saved 2D projection: {cache}")
    return U
