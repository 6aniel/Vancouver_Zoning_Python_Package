"""One flat dict of headline limits per district and building form.

Handy for tables, for comparing districts, and as a quick feature row. Every
value comes from `DistrictSchedule.value()`, so conditional rows only count
when `facts` satisfy them (see `Regulation.requires`).
"""
from __future__ import annotations

from .models import DistrictSchedule, Metric

FIELDS = [
    "fsr", "approved_fsr", "height", "floors", "front", "side", "rear", "min_area", "min_width", "max_area",
    "max_width", "coverage", "building_depth", "depth_fraction", "building_width", "units_per_ha", "max_units",
    "top_fraction", "rental_only",
]


def summarize(
    sched: DistrictSchedule,
    use: str,
    facts: dict | None = None,
    units: int | None = None,
    tenure: str | None = None,
) -> dict:
    """Headline limits for `use` on a site described by `facts`
    (site_area, site_frontage, site_depth, corner_site, fsr, ...).

    fsr is the outright limit; approved_fsr the highest Director of Planning
    relaxation whose conditions hold. Side yards given as a share of site width
    are converted to metres with facts['site_frontage']."""
    facts = facts or {}
    kw = {"units": units}
    tkw = {"tenure": tenure} if tenure else {}

    def v(metric, bound, **extra):
        return sched.value(metric, use, bound, facts=facts, **kw, **extra)

    def side():
        rows = sched.get(Metric.SIDE_YARD, use, "min", facts=facts, condition=None, **kw)
        vals = [r.value * facts.get("site_frontage", float("nan")) if r.unit.value == "fraction_of_site_width"
                else r.value for r in rows]
        cond = [x for x, r in zip(vals, rows) if r.requires]
        return (min(cond) if cond else max(vals)) if vals else None

    def depth(fraction: bool):
        rows = [r for r in sched.get(Metric.BUILDING_DEPTH, use, "max", facts=facts, condition=None, **kw)
                if (r.unit.value == "fraction_of_site_depth") == fraction]
        return min(r.value for r in rows) if rows else None

    disc = [r.value for r in sched.get(Metric.FSR, use, "max", include_discretionary=True, facts=facts, **kw, **tkw)
            if r.discretionary]
    return dict(
        fsr=sched.value(Metric.FSR, use, "max", **kw, **tkw) or v(Metric.FSR, "max", **tkw),
        approved_fsr=max(disc) if disc else None,
        height=v(Metric.BUILDING_HEIGHT, "max", condition=None),
        floors=v(Metric.STOREYS, "max", condition=None),
        front=v(Metric.FRONT_YARD, "min") or v(Metric.FRONT_YARD, "max"),
        side=side(),
        rear=v(Metric.REAR_YARD, "min", condition=None),
        min_area=v(Metric.SITE_AREA, "min", condition=None),
        min_width=v(Metric.SITE_FRONTAGE, "min", condition=None),
        max_area=v(Metric.SITE_AREA, "max"),
        max_width=v(Metric.SITE_FRONTAGE, "max"),
        coverage=v(Metric.SITE_COVERAGE, "max"),
        building_depth=depth(False),
        depth_fraction=depth(True),
        building_width=v(Metric.BUILDING_WIDTH, "max"),
        units_per_ha=v(Metric.UNITS_PER_HECTARE, "max"),
        max_units=v(Metric.DWELLING_UNITS, "max", **tkw),
        top_fraction=v(Metric.TOP_STOREY_FRACTION, "max"),
        rental_only=sched.rental_only,
    )
