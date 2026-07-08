"""
Drift color science.

Drift color is RELATIVE: log2 of the 2025/2020 share ratio (smoothed by EPS so
brand-new clusters don't divide by zero). A cluster that grew 8x (or appeared
from nothing) saturates full green; an 8x shrink saturates full red; a large
cluster that gained "only" +30% stays pale.
"""
import math

from . import config


def drift_ramp(t: float) -> str:
    """Red (declining) -> neutral -> green (growing), t in [0, 1]."""
    t = min(1.0, max(0.0, t))
    if t < 0.5:
        u = 2 * t
        r, g, b = 214, int(39 + 110 * u), int(40 + 110 * u)
    else:
        u = 2 * (t - 0.5)
        r, g, b = int(214 - 85 * u), int(149 + 45 * u), int(39 + 86 * u)
    return f'#{r:02x}{g:02x}{b:02x}'


def drift_color_relative(df_start: float, df_end: float) -> str:
    r = math.log2((df_end + config.DRIFT_EPS) / (df_start + config.DRIFT_EPS))
    return drift_ramp(r / config.DRIFT_LOG_MAX * 0.5 + 0.5)
