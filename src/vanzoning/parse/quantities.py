"""Regex helpers that turn bylaw phrases into numbers and conditions."""
from __future__ import annotations

import re
from collections.abc import Callable

from ..models import Metric, Unit

NUM = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
_QTY = re.compile(
    rf"({NUM})\s*(m²|m2|m\b|storeys?\b|units per hectare|%(?: of the site (?:area|width|depth))?)"
)


def num(s: str) -> float:
    return float(s.replace(",", ""))


# Order matters: more specific phrases first.
METRIC_KEYWORDS: list[tuple[str, Metric]] = [
    ("separation", Metric.BUILDING_SEPARATION),
    ("floor space ratio", Metric.FSR),
    ("front yard", Metric.FRONT_YARD),
    ("side yard", Metric.SIDE_YARD),
    ("rear yard", Metric.REAR_YARD),
    ("rear setback", Metric.REAR_YARD),
    ("building height", Metric.BUILDING_HEIGHT),
    ("building depth", Metric.BUILDING_DEPTH),
    ("building width", Metric.BUILDING_WIDTH),
    ("site coverage", Metric.SITE_COVERAGE),
    ("site frontage", Metric.SITE_FRONTAGE),
    ("site width", Metric.SITE_FRONTAGE),
    ("site depth", Metric.SITE_DEPTH),
    ("site area", Metric.SITE_AREA),
    ("impermeable", Metric.IMPERMEABLE_AREA),
    ("units per hectare", Metric.UNITS_PER_HECTARE),
    ("dwelling unit density", Metric.UNITS_PER_HECTARE),
]

CONDITION_ALIASES = {
    "rear buildings": "rear_building",
    "a rear building": "rear_building",
    "buildings in a courtyard configuration": "courtyard",
    "all other buildings": None,
    "a building other than a rear building": None,
    "all other sites": None,
    "on all other sites": None,
    "other sites": None,
    "all other uses": None,
    "other side yard": None,
    "1 townhouse building on a site": None,
    "1 freehold rowhouse building on a site": None,
    "1 principal building": None,
    "in the front 60% of the site depth": None,
    "all buildings other than infill": None,
    "in the rear 40% of the site depth": "rear_40pct_of_site_depth",
    "more than 1 townhouse building on a site": "more_than_1_building",
    "more than 1 freehold rowhouse building on a site": "more_than_1_building",
    "exterior side yard": "exterior_side_yard",
    "buildings located on a site frontage": "between_frontage_buildings",
    "rear buildings (separation)": "between_rear_buildings",
    "buildings located on a site frontage and rear buildings": "frontage_to_rear",
}


def parse_quantities(text: str) -> list[tuple[float, Unit]]:
    if text.strip().lower() in ("no minimum", "not required"):
        return [(0.0, None)]  # caller picks the metric's unit
    out = []
    for n, unit in _QTY.findall(text):
        v = num(n)
        if unit in ("m²", "m2"):
            out.append((v, Unit.M2))
        elif unit == "m":
            out.append((v, Unit.M))
        elif unit.startswith("storey"):
            out.append((v, Unit.STOREYS))
        elif unit == "units per hectare":
            out.append((v, Unit.UNITS_PER_HA))
        elif unit.startswith("%"):
            kind = {"width": Unit.FRACTION_OF_SITE_WIDTH, "depth": Unit.FRACTION_OF_SITE_DEPTH}.get(
                unit.rsplit(" ", 1)[-1], Unit.FRACTION_OF_SITE)
            out.append((v / 100.0, kind))
    return out


def detect_metric(label: str) -> Metric | None:
    low = label.lower()
    for kw, metric in METRIC_KEYWORDS:
        if kw in low:
            return metric
    return None


def detect_bound(label: str) -> str | None:
    low = label.lower()
    if "minimum" in low:
        return "min"
    if "maximum" in low:
        return "max"
    return None


_UNIT_PATTERNS: list[tuple[str, Callable | None]] = [
    (r"not less than (\d+) and not more than (\d+) dwelling units?", lambda m, c: (int(m[1]), int(m[2]))),
    (r"more than (\d+) dwelling units?", lambda m, c: (int(m[1]) + 1, c if c and c > int(m[1]) else None)),
    (r"(?:not more than|no more than|up to) (\d+) (?:dwelling )?units?", lambda m, c: (1, int(m[1]))),
    (r"(\d+) or more dwelling units?", lambda m, c: (int(m[1]), c)),
    (r"containing ((?:\d+, )*\d+(?: or \d+)?)( or more)? (?:dwelling )?units?\b", None),
    (r"^((?:\d+, )*\d+(?: or \d+)?) dwelling units?\b", None),
]


def parse_unit_range(text: str, cap: int | None = None) -> tuple[int | None, int | None]:
    """'containing 3 or 4 dwelling units' -> (3, 4); '6 or more' -> (6, cap);
    'more than 8 dwelling units' -> (9, cap); 'not less than 5 and not more than 8' -> (5, 8)."""
    low = text.lower().strip()
    for pat, fn in _UNIT_PATTERNS:
        m = re.search(pat, low)
        if not m:
            continue
        if fn:
            lo, hi = fn(m, cap)
        else:
            nums = [int(x) for x in re.findall(r"\d+", m.group(1))]
            lo, hi = min(nums), (cap if (m.lastindex or 0) >= 2 and m.group(2) else max(nums))
        if re.search(r"\bor (?:a )?triplex\b", low):  # "townhouse containing 4 dwelling units or triplex"
            lo = min(lo, 3)
        return lo, hi
    return None, None


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


# ------------------------------------------------------------ conditions
_M2 = r"\s?m(?:²|2)"
_REQ_PATTERNS: list[tuple[str, Callable]] = [
    (rf"minimum site area (?:of )?({NUM}){_M2}", lambda m: {"site_area_gte": num(m[1])}),
    (rf"site area of ({NUM}){_M2} or more", lambda m: {"site_area_gte": num(m[1])}),
    (rf"(?:sites?|lots?) (?:that are )?less than ({NUM}){_M2}", lambda m: {"site_area_lt": num(m[1])}),
    (rf"site area (?:of )?less than ({NUM}){_M2}", lambda m: {"site_area_lt": num(m[1])}),
    (rf"minimum (?:site )?frontage (?:of )?({NUM}) ?m\b", lambda m: {"site_frontage_gte": num(m[1])}),
    (rf"(?:site )?frontage (?:of )?({NUM}) ?m or (?:more|greater)", lambda m: {"site_frontage_gte": num(m[1])}),
    (rf"(?:site )?frontage (?:greater than|exceeding|of more than) ({NUM}) ?m", lambda m: {"site_frontage_gt": num(m[1])}),
    (rf"(?:site )?frontage (?:of )?less than ({NUM}) ?m", lambda m: {"site_frontage_lt": num(m[1])}),
    (rf"does not exceed ({NUM}) ?m in depth", lambda m: {"site_depth_lte": num(m[1])}),
    (rf"site depth (?:of )?({NUM}) ?m or more", lambda m: {"site_depth_gte": num(m[1])}),
    (rf"frontage that is equal to or greater than ({NUM}) ?m but is less than ({NUM}) ?m",
     lambda m: {"site_frontage_gte": num(m[1]), "site_frontage_lt": num(m[2])}),
    (rf"(?:width|frontage) of at least ({NUM}) ?m\b", lambda m: {"site_frontage_gte": num(m[1])}),
    (rf"depth of at least ({NUM}) ?m\b", lambda m: {"site_depth_gte": num(m[1])}),
    (rf"floor space ratio for non-dwelling uses (?:is|must be) at least ({NUM})", lambda m: {"non_dwelling_fsr_gte": num(m[1])}),
    (r"\bcorner site", lambda m: {"corner_site": True}),
    (rf"({NUM})% of the (?:residential floor area|total dwelling units|dwelling units)[^,;%]*? (?:is|are) developed as social housing",
     lambda m: {"social_housing_share_gte": num(m[1]) / 100}),
    (rf"({NUM})% of the residential floor area is (?:secured|developed) as below-market rental",
     lambda m: {"below_market_rental_share_gte": num(m[1]) / 100}),
    (r"character house is demolished", lambda m: {"character_house_demolished": True}),
    (r"transit-oriented area", lambda m: {"transit_oriented_area": True}),
    (r"locked in lots?", lambda m: {"locked_in_lots": True}),
    (r"retention of (?:an? |the )?(?:existing|character house|residential building|building)",
     lambda m: {"retention": True}),
    (r"(?:where|if) (?:a|an) (?:character house|existing building|residential building existing|building existing)[^,]*? is retained",
     lambda m: {"retention": True}),
    (rf"floor space ratio (?:does not exceed|is less than or equal to) ({NUM})", lambda m: {"fsr_lte": num(m[1])}),
    (rf"floor space ratio exceeds ({NUM})(?: and does not exceed ({NUM}))?",
     lambda m: {"fsr_gt": num(m[1]), **({"fsr_lte": num(m[2])} if m[2] else {})}),
]


def extract_requires(text: str) -> dict:
    """Facts a phrase conditions on. Includes key 'tenure' if the phrase fixes it."""
    low = text.lower()
    out: dict = {}
    for pat, fn in _REQ_PATTERNS:
        for m in re.finditer(pat, low):
            for k, v in fn(m).items():
                out.setdefault(k, v)
    t = detect_tenure(low)
    if t:
        out["tenure"] = t
    return out


def detect_tenure(text: str) -> str | None:
    low = text.lower()
    if re.search(r"tenure other than (?:residential )?rental", low):
        return "strata_or_mixed"
    if re.search(r"100% residential rental|secured as residential rental tenure", low):
        return "rental"
    return None
