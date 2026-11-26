"""Fixed-order numeric feature vectors for ML (numpy -> torch.from_numpy)."""
from __future__ import annotations

import numpy as np

from .models import DistrictSchedule, Metric

# (metric, bound) pairs in a stable order; extend only by appending.
FEATURES: list[tuple[Metric, str]] = [
    (Metric.FSR, "max"),
    (Metric.BUILDING_HEIGHT, "max"),
    (Metric.STOREYS, "max"),
    (Metric.SITE_AREA, "min"),
    (Metric.SITE_FRONTAGE, "min"),
    (Metric.SITE_DEPTH, "min"),
    (Metric.FRONT_YARD, "min"),
    (Metric.SIDE_YARD, "min"),
    (Metric.REAR_YARD, "min"),
    (Metric.BUILDING_DEPTH, "max"),
    (Metric.BUILDING_WIDTH, "max"),
    (Metric.SITE_COVERAGE, "max"),
    (Metric.IMPERMEABLE_AREA, "max"),
    (Metric.DWELLING_UNITS, "max"),
]
FEATURE_NAMES = [f"{m.value}_{b}" for m, b in FEATURES]


def feature_vector(sched: DistrictSchedule, use: str, **filters) -> np.ndarray:
    """Base-case (no condition) value per feature; NaN where the district is silent."""
    out = np.full(len(FEATURES), np.nan, dtype=np.float32)
    for i, (metric, bound) in enumerate(FEATURES):
        rows = [r for r in sched.get(metric, use, bound, **filters) if r.condition is None]
        if rows:
            vals = [r.value for r in rows]
            # For unit-banded rules (multiplex site area), take the most permissive band.
            out[i] = min(vals) if bound == "min" else max(vals)
    return out


def feature_matrix(schedules: list[DistrictSchedule], use: str) -> tuple[np.ndarray, list[str]]:
    """Rows = districts. `torch.from_numpy(X)` works directly."""
    X = np.stack([feature_vector(s, use) for s in schedules])
    return X, [s.district for s in schedules]
