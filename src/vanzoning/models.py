"""Data schema for Vancouver district schedules.

Design goals
------------
* One `DistrictSchedule` per district per bylaw version, serialisable to JSON.
* Numeric limits live in a flat list of `Regulation` rows ("long format"), so
  they drop straight into pandas, a MILP builder, or a tensor.
* Every number keeps provenance (clause id, page, original text) so a
  collaborator can always check it against the PDF.
* Anything we don't yet model numerically is still kept verbatim in `clauses`.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Metric(str, Enum):
    FSR = "fsr"
    DWELLING_UNITS = "dwelling_units"
    SITE_AREA = "site_area"
    SITE_FRONTAGE = "site_frontage"
    SITE_DEPTH = "site_depth"
    BUILDING_HEIGHT = "building_height"
    STOREYS = "storeys"
    FRONT_YARD = "front_yard"
    SIDE_YARD = "side_yard"
    REAR_YARD = "rear_yard"
    BUILDING_DEPTH = "building_depth"
    BUILDING_WIDTH = "building_width"
    BUILDING_SEPARATION = "building_separation"
    SITE_COVERAGE = "site_coverage"
    IMPERMEABLE_AREA = "impermeable_area"
    FAMILY_UNITS = "family_units"  # min units with 2+ bedrooms
    TOP_STOREY_FRACTION = "top_storey_fraction"  # partial top storey as share of storey below
    UNITS_PER_HECTARE = "units_per_hectare"  # dwelling unit density cap


class Unit(str, Enum):
    M = "m"
    M2 = "m2"
    STOREYS = "storeys"
    RATIO = "ratio"  # e.g. FSR
    FRACTION_OF_SITE = "fraction_of_site"  # 50% of site area -> 0.5
    FRACTION_OF_SITE_WIDTH = "fraction_of_site_width"  # 10% of the site width -> 0.1
    FRACTION_OF_SITE_DEPTH = "fraction_of_site_depth"  # 30% of the site depth -> 0.3
    UNITS_PER_HA = "units_per_ha"
    COUNT = "count"


class Regulation(BaseModel):
    """One numeric limit, e.g. 'max building height 11.5 m for multiplex'."""

    district: str
    group: str = Field(description="Use group whose section the rule sits in, e.g. 'multiple_dwelling' (s.3.1) or 'other_uses' (s.3.2)")
    use: str = Field("*", description="Specific use slug if the clause names one (e.g. 'duplex'), else '*' for the whole group")
    metric: Metric
    bound: Literal["min", "max"]
    value: float
    unit: Unit
    min_units: int | None = Field(None, description="Lower end of dwelling-unit range this applies to")
    max_units: int | None = Field(None, description="Upper end of dwelling-unit range this applies to")
    condition: str | None = Field(None, description="Qualifier, e.g. 'rear_building', 'courtyard'")
    tenure: Literal["rental", "any", "strata_or_mixed"] | None = None
    discretionary: bool = Field(False, description="True if only via Director of Planning relaxation")
    requires: dict[str, float | bool] = Field(
        default_factory=dict,
        description=(
            "Site/project facts this row needs, all of which must hold (one row per alternative). "
            "Keys are '<fact>_<op>' with op in gte/gt/lte/lt (e.g. site_area_gte: 920, "
            "site_depth_lte: 33.5, social_housing_share_gte: 1.0, fsr_gt: 0.9) or a bare boolean fact "
            "(corner_site, transit_oriented_area, retention, locked_in_lots). Empty = unconditional."
        ),
    )
    clause: str
    page: int
    source_text: str

    def applies(self, facts: dict | None) -> bool:
        """True if every requirement holds for `facts`; unknown facts fail."""
        if not self.requires:
            return True
        if not facts:
            return False
        for key, want in self.requires.items():
            if isinstance(want, bool):
                if bool(facts.get(key, False)) != want:
                    return False
                continue
            fact, _, op = key.rpartition("_")
            have = facts.get(fact)
            if have is None:
                return False
            ok = {"gte": have >= want, "gt": have > want, "lte": have <= want, "lt": have < want}.get(op)
            if not ok:
                return False
        return True


class UseApproval(BaseModel):
    use: str  # slug
    name: str  # as written in the bylaw
    category: str
    approval: Literal["outright", "conditional"]
    use_specific_regulations: list[str] = []
    min_units: int | None = None  # from the use name, e.g. "containing more than 8 dwelling units"
    max_units: int | None = None


class Clause(BaseModel):
    """Verbatim clause text, for search, review, and LLM/RAG use."""

    id: str  # e.g. "3.1.1.3(b)(ii)(A)"
    text: str
    page: int
    section_title: str | None = None


class Figure(BaseModel):
    caption: str
    page: int


class OverviewEntry(BaseModel):
    """One row of the section 1.2 overview table (use -> min site area -> section)."""

    name: str
    uses: list[str]
    min_site_area_m2: float | None = None
    section: str | None = None  # e.g. "3.1"
    regulated_by: str | None = Field(None, description="Other district whose schedule governs this use, e.g. 'R1-1'")


class SourceDocument(BaseModel):
    filename: str
    sha256: str
    title: str | None = None
    version_label: str | None = None  # e.g. "June 2026" from the footer
    pages: int


class DistrictSchedule(BaseModel):
    district: str
    name: str | None = None  # e.g. "Residential Inclusive"
    intent: str | None = None
    source: SourceDocument
    uses: list[UseApproval] = []
    regulations: list[Regulation] = []
    clauses: list[Clause] = []
    figures: list[Figure] = []
    use_groups: dict[str, str] = Field(default_factory=dict, description="section id -> use group slug")
    group_members: dict[str, list[str]] = Field(
        default_factory=dict, description="use group slug -> use slugs it governs ('*' = every use)")
    overview: list[OverviewEntry] = []
    rental_only: bool = Field(False, description="All dwelling units must be secured as residential rental tenure")
    schedule_districts: list[str] = Field(default_factory=list, description="All districts sharing this schedule PDF")
    parser_version: str

    # convenience -------------------------------------------------------
    def regulations_df(self):
        import pandas as pd

        return pd.DataFrame([r.model_dump(mode="json") for r in self.regulations])

    def uses_df(self):
        import pandas as pd

        return pd.DataFrame([u.model_dump(mode="json") for u in self.uses])

    def regulated_by(self, use: str) -> str | None:
        """District whose schedule governs `use` here (e.g. duplex in R3-1 -> 'R1-1'), else None."""
        return next((e.regulated_by for e in self.overview if use in e.uses and e.regulated_by), None)

    def group_for(self, use: str) -> str:
        """Which section-3 group governs a use (falls back to 'all_uses' / 'other_uses')."""
        groups = list(dict.fromkeys(self.use_groups.values()))
        if use in groups:
            return use
        for g in groups:
            if use in self.group_members.get(g, []):
                return g
        own = next((r.group for r in self.regulations if r.use == use), None)
        if own:  # e.g. "For townhouse, ..." inside the RM-1 multiple dwelling section
            return own
        for g in groups:
            if "*" in self.group_members.get(g, []) or g == "all_uses":
                return g
        return next((g for g in groups if g.startswith("other")), "other_uses")

    def get(
        self,
        metric: Metric | str,
        use: str,
        bound: str | None = None,
        include_discretionary: bool = False,
        facts: dict | None = None,
        include_conditional: bool = False,
        units: int | None = None,
        **filters,
    ) -> list[Regulation]:
        """Rules for `use`, with use-specific rows overriding group-wide ('*') rows.

        Rows with `requires` are returned only if `facts` satisfy them, or if
        include_conditional=True (then all are returned unevaluated).
        `units` keeps only rows whose dwelling-unit band contains that count."""
        metric = Metric(metric)
        group = self.group_for(use)
        rows = [
            r for r in self.regulations
            if r.metric == metric and r.group == group and r.use in (use, "*")
            and (include_discretionary or not r.discretionary)
            and (bound is None or r.bound == bound)
            and (include_conditional or r.applies(facts))
            and (units is None or r.min_units is None or r.min_units <= units <= (r.max_units or units))
            and all(getattr(r, k) == v for k, v in filters.items())
        ]
        specific = {(r.bound, r.condition, r.tenure, r.discretionary) for r in rows if r.use == use}
        return [r for r in rows if r.use == use or (r.bound, r.condition, r.tenure, r.discretionary) not in specific]

    def value(
        self, metric: Metric | str, use: str, bound: str, facts: dict | None = None, units: int | None = None, **filters
    ) -> float | None:
        """Single binding value, or None.

        Unconditional rows: the tightest one binds. Rows whose `requires` hold
        for `facts` are alternative pathways ("despite ..., the maximum is"),
        so if any apply the most permissive of them is returned."""
        rows = self.get(metric, use, bound, facts=facts, units=units, **filters)
        if not rows:
            return None
        cond = [r.value for r in rows if r.requires]
        if cond:
            return min(cond) if bound == "min" else max(cond)
        vals = [r.value for r in rows]
        return max(vals) if bound == "min" else min(vals)
