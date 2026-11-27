"""Layer 3: turn rules into per-site building options.

This is the bridge to optimisation: for each site you get every building
option the district allows, whether it is eligible, and its unit count and
maximum floor area. That table is what a MILP (one binary per site x option)
or an ML feature pipeline consumes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import floor
from typing import Literal

from .models import DistrictSchedule, Metric

# Dwelling units each non-multiplex form yields. Domain knowledge, not parsed:
# e.g. a duplex with secondary suite allows 1 suite per unit (R1-1 s.2.2.3).
UNITS_PER_USE = {
    "single_detached_house": 1,
    "single_detached_house_with_secondary_suite": 2,
    "duplex": 2,
    "duplex_with_secondary_suite": 4,
}


@dataclass
class Site:
    area_m2: float
    frontage_m: float
    depth_m: float | None = None
    tenure: Literal["strata_or_mixed", "rental"] = "strata_or_mixed"
    has_lane: bool = True  # multiplex needs rear vehicular access (R1-1 2.2.7(b))
    in_floodplain: bool = False  # multiplex not permitted (R1-1 2.2.7(c))
    corner_site: bool = False
    extra_facts: dict = field(default_factory=dict)  # e.g. {"social_housing_share": 1.0, "transit_oriented_area": True}

    def facts(self) -> dict:
        """Facts used to evaluate `Regulation.requires` (site_area_gte, corner_site, ...)."""
        return {"site_area": self.area_m2, "site_frontage": self.frontage_m, "site_depth": self.depth_m,
                "corner_site": self.corner_site, **self.extra_facts}


@dataclass
class Option:
    district: str
    use: str
    units: int
    eligible: bool
    max_fsr: float | None
    max_floor_area_m2: float | None  # min(FSR x site area, geometric envelope)
    fsr_floor_area_m2: float | None = None
    envelope_floor_area_m2: float | None = None
    footprint_m2: float | None = None
    floors: int | None = None
    binding: str | None = None  # "fsr" | "envelope"
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["reasons"] = "; ".join(self.reasons)
        return d


def _check(sched: DistrictSchedule, site: Site, use: str, units: int | None, reasons: list[str]) -> None:
    def rows(metric, bound):
        out = []
        for r in sched.get(metric, use, bound, facts=site.facts()):
            if r.condition is not None:
                continue  # courtyard / rear-building variants are design choices
            if units is not None and r.min_units is not None and not (r.min_units <= units <= (r.max_units or units)):
                continue
            out.append(r)
        return out

    for metric, attr in ((Metric.SITE_AREA, "area_m2"), (Metric.SITE_FRONTAGE, "frontage_m"), (Metric.SITE_DEPTH, "depth_m")):
        val = getattr(site, attr)
        if val is None:
            continue
        for r in rows(metric, "min"):
            if val < r.value:
                reasons.append(f"{metric.value} {val:g} < min {r.value:g} ({r.clause})")
        for r in rows(metric, "max"):
            if val > r.value:
                reasons.append(f"{metric.value} {val:g} > max {r.value:g} ({r.clause})")


def geometric_envelope(
    sched: DistrictSchedule, site: Site, use: str, floor_height_m: float = 3.0
) -> dict | None:
    """Simplified single rectangular building envelope: footprint from yards and max building
    width/depth, capped by site coverage; floors from height / floor height and
    the storey cap; partial top storey where the schedule requires one.
    Returns None if site depth is unknown."""
    if site.depth_m is None:
        return None

    facts = site.facts()

    def v(metric, bound):
        rows = sched.get(metric, use, bound, facts=facts, condition=None)
        if not rows:
            return None
        vals = []
        for r in rows:  # "10% of the site width" -> metres
            scale = {"fraction_of_site_width": site.frontage_m, "fraction_of_site_depth": site.depth_m}.get(r.unit.value)
            vals.append(r.value * scale if scale is not None and metric != Metric.SITE_COVERAGE else r.value)
        cond = [x for x, r in zip(vals, rows) if r.requires]
        pool = cond or vals
        return (min(pool) if cond else max(pool)) if bound == "min" else (max(pool) if cond else min(pool))

    side = v(Metric.SIDE_YARD, "min") or 0.0
    width = max(0.0, site.frontage_m - 2 * side)
    depth = max(0.0, site.depth_m - (v(Metric.FRONT_YARD, "min") or 0) - (v(Metric.REAR_YARD, "min") or 0))
    if (bw := v(Metric.BUILDING_WIDTH, "max")) is not None:
        width = min(width, bw)
    if (bd := v(Metric.BUILDING_DEPTH, "max")) is not None:
        depth = min(depth, bd)
    footprint = width * depth
    if (cov := v(Metric.SITE_COVERAGE, "max")) is not None:
        footprint = min(footprint, cov * site.area_m2)
    height = v(Metric.BUILDING_HEIGHT, "max")
    storeys = v(Metric.STOREYS, "max")
    floors = floor((height or 1e9) / floor_height_m)
    if storeys is not None:
        floors = min(floors, int(storeys))
    top = v(Metric.TOP_STOREY_FRACTION, "max")
    top = top if (top is not None and storeys is not None and floors == int(storeys)) else 1.0
    gross = max(0, floors - 1 + top) * footprint if floors else 0.0
    return dict(footprint_m2=footprint, floors=floors, envelope_floor_area_m2=gross)


def _make_option(sched, site, use, units, fsr, reasons, floor_height_m) -> Option:
    fsr_area = fsr * site.area_m2 if fsr else None
    env = geometric_envelope(sched, site, use, floor_height_m) or {}
    env_area = env.get("envelope_floor_area_m2")
    cands = {k: x for k, x in (("fsr", fsr_area), ("envelope", env_area)) if x is not None}
    binding = min(cands, key=cands.get) if cands else None
    return Option(sched.district, use, units, not reasons, fsr,
                  cands[binding] if binding else None, fsr_area, env_area,
                  env.get("footprint_m2"), env.get("floors"), binding, reasons)


def building_options(sched: DistrictSchedule, site: Site, floor_height_m: float = 3.0) -> list[Option]:
    opts: list[Option] = []

    # Multiplex: one option per allowed unit count -----------------------
    if "multiple_dwelling" in sched.use_groups.values() and sched.get(Metric.DWELLING_UNITS, "multiple_dwelling", "max"):
        cap = sched.value(Metric.DWELLING_UNITS, "multiple_dwelling", "max", tenure=site.tenure)
        cap_any = max(r.value for r in sched.get(Metric.DWELLING_UNITS, "multiple_dwelling", "max"))
        fsr = sched.value(Metric.FSR, "multiple_dwelling", "max", facts=site.facts())
        unit_floor = min((r.min_units for r in sched.get(Metric.SITE_AREA, "multiple_dwelling", "min") if r.min_units), default=3)
        for n in range(unit_floor, int(cap_any) + 1):
            reasons: list[str] = []
            if cap is not None and n > cap:
                reasons.append(f"{n} units > max {cap:g} for {site.tenure} tenure")
            if not site.has_lane:
                reasons.append("no rear vehicular access (2.2.7(b))")
            if site.in_floodplain:
                reasons.append("in flood plain (2.2.7(c))")
            _check(sched, site, "multiple_dwelling", n, reasons)
            opts.append(_make_option(sched, site, "multiple_dwelling", n, fsr, reasons, floor_height_m))

    # Other residential forms --------------------------------------------
    for use, units in UNITS_PER_USE.items():
        if not any(u.use == use for u in sched.uses):
            continue
        reasons = []
        _check(sched, site, use, None, reasons)
        fsr = sched.value(Metric.FSR, use, "max", facts=site.facts())
        opts.append(_make_option(sched, site, use, units, fsr, reasons, floor_height_m))
    return opts


def options_frame(sched: DistrictSchedule, sites):
    """sites: DataFrame with area_m2, frontage_m[, depth_m, tenure, has_lane, in_floodplain].
    Returns a long DataFrame (site_id x option) ready for a MILP or ML model."""
    import pandas as pd

    fields = Site.__dataclass_fields__
    rows = []
    for site_id, rec in sites.iterrows():
        site = Site(**{k: rec[k] for k in fields if k in rec and pd.notna(rec[k])})
        for o in building_options(sched, site):
            rows.append({"site_id": site_id, **o.as_dict()})
    return pd.DataFrame(rows)
