"""Layer 2b: turn blocks + clauses into validated DistrictSchedules.

One PDF can cover several districts (RM-5/5A/5B/5C/5D, R3-1/2/3, ...). Rows are
first produced with the list of districts they apply to (from the table column,
or from "In the RR-2B district ..." wording in the clause or its parents), then
split into one `DistrictSchedule` per district.
"""
from __future__ import annotations

import hashlib
import itertools
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from .. import __version__
from ..extract.tagged_pdf import Block, iter_blocks
from ..models import (
    Clause,
    DistrictSchedule,
    Figure,
    Metric,
    OverviewEntry,
    Regulation,
    SourceDocument,
    Unit,
    UseApproval,
)
from .clauses import SECTION_RE, RawClause, build_clauses
from .quantities import (
    CONDITION_ALIASES,
    NUM,
    detect_bound,
    detect_metric,
    detect_tenure,
    extract_requires,
    num,
    parse_quantities,
    parse_unit_range,
    slugify,
)

MARKER_RE = re.compile(r"^\(([a-z]{1,4}|[A-Z])\)\s*(.*)$")
DISTRICT_RE = re.compile(r"\b(R1-1|RA-1|FM-1|R[345]-\d|RT-\d+[A-Z]?|RM-\d+[A-Z]?|RR-\d[A-Z]?)\b")
AREA_CELL_RE = re.compile(rf"^({NUM})\s*m(?:²|2)$")


def district_codes(text: str) -> list[str]:
    return list(dict.fromkeys(DISTRICT_RE.findall(text or "")))


# ---------------------------------------------------------------- uses
_QUALIFIER_RE = re.compile(
    r" containing | not permitted | in the [A-Z0-9-]+ district| as an? (?:outright|conditional) approval use"
    r"| if section | only in the | other than | that includes ",
    re.IGNORECASE,
)


def use_base(name: str) -> str:
    base = name.split(",")[0]
    base = re.sub(r"^\d-storey ", "", base, flags=re.IGNORECASE)
    base = re.sub(r"\b(?:low|mid|high)-rise ", "", base, flags=re.IGNORECASE)
    base = re.sub(r" buildings\b.*$", "", base)  # 'Townhouse buildings in a courtyard ...' -> Townhouse  # R3/R4/R5 'Low-Rise Apartment' = apartment
    return _QUALIFIER_RE.split(base)[0].strip()


def use_slug(name: str) -> str:
    slug = slugify(use_base(name))
    if "existing as of" in name.lower():
        slug += "_existing"
    return slug


def split_or(base: str) -> list[str]:
    """'Duplex or Duplex with Secondary Suite' -> two uses, but keep
    'Seniors Supportive or Independent Living Housing' / 'Park or Playground' whole:
    only split when both sides start with the same word."""
    parts = [p.strip() for p in re.split(r" or (?:an? )?(?=[A-Z])", base, flags=0) if p.strip()]
    if len(parts) > 1 and len({p.split()[0].lower() for p in parts}) == 1:
        return parts
    return [base.strip()]


def overview_uses(name: str) -> list[str]:
    """'Duplex or Duplex with Secondary Suite, in combination ...' -> [duplex, duplex_with_secondary_suite]."""
    if name.lower().startswith(("other uses", "all uses", "all other uses")):
        return []
    return [slugify(p) for p in split_or(use_base(name))]


class _UseMatcher:
    """Finds use names mentioned in free text, longest names first."""

    FORMS = ["apartment", "townhouse", "triplex", "duplex", "freehold rowhouse", "multiple dwelling",
             "mixed-use residential building", "infill", "laneway house", "single detached house"]

    def __init__(self, names: list[str]):
        pairs = {}
        for n in names + self.FORMS:
            for part in split_or(use_base(n)):
                pairs[part.lower()] = slugify(part)
        self.pairs = sorted(pairs.items(), key=lambda kv: -len(kv[0]))

    def find(self, text: str) -> list[str]:
        low = text.lower()
        found = []
        for name, slug in self.pairs:
            pat = r"\b" + re.escape(name) + r"s?\b"
            if re.search(pat, low):
                if slug not in found:
                    found.append(slug)
                low = re.sub(pat, " ", low)
        return found


# ---------------------------------------------------------------- rows
@dataclass
class _Row:
    """A Regulation before it is split per district."""

    districts: list[str]
    kw: dict = field(default_factory=dict)


def _group_for_clause(cid: str, group_titles: dict[str, str]) -> str:
    """Section 3.x regulations apply to a group of uses named by the 3.x heading."""
    for prefix, group in sorted(group_titles.items(), key=lambda kv: -len(kv[0])):
        if cid == prefix or cid.startswith(prefix + ".") or cid.startswith(prefix + "("):
            return group
    return "other_uses"


def _parse_use_table(tables: list[Block]) -> list[UseApproval]:
    uses: list[UseApproval] = []
    category = "uncategorized"
    for t in tables:
        for row in t.rows:
            cells = [c for c in row if c is not None]
            if len(cells) == 1 or (len(cells) > 1 and not any(cells[1:])):
                category = cells[0]
                continue
            name, approval = cells[0], cells[1].lower()
            refs = [r.strip() for r in cells[2].split(",")] if len(cells) > 2 and cells[2] else []
            lo, hi = parse_unit_range(name)
            uses.append(
                UseApproval(
                    use=use_slug(name), name=name, category=category,
                    approval="outright" if approval.startswith("outright") else "conditional",
                    use_specific_regulations=[r for r in refs if r],
                    min_units=lo, max_units=hi,
                )
            )
    return uses


def _parse_overview(tables: list[Block]) -> list[OverviewEntry]:
    """Section 1.2 table. Merged cells (row spans) are carried down."""

    def is_area(c):
        return c == "--" or bool(AREA_CELL_RE.match(c)) or c.lower().startswith("regulated by")

    def is_section(c):
        return bool(re.match(r"^\d+\.\d+$", c)) or c.lower().startswith("regulated by")

    out, area, section = [], None, None
    for t in tables:
        for row in t.rows:
            cells = [c for c in row if c]
            if not cells:
                continue
            if len(cells) >= 3:
                area, name, section = cells[0], cells[1], cells[2]
            elif len(cells) == 2 and is_area(cells[0]) and not is_section(cells[1]):
                area, name = cells
            elif len(cells) == 2:
                name, section = cells
            else:
                name = cells[0]
            m = AREA_CELL_RE.match(area or "")
            reg = re.search(DISTRICT_RE, section or "") if (section or "").lower().startswith("regulated") else None
            out.append(OverviewEntry(
                name=name, uses=overview_uses(name), min_site_area_m2=num(m.group(1)) if m else None,
                section=section if section and is_section(section) and not reg else None,
                regulated_by=reg.group(1) if reg else None,
            ))
    return out


def _regulation_table_rows(tables: list[Block], districts: list[str]):
    """Flatten 'Regulations | <district> [| <district>]' tables into
    (clause_id, label, [(districts, value)], page).

    Parent rows ("3.1.2.5 Maximum building height for:") have no value and
    prefix their (a)/(b) children. Tables split across pages share state."""
    out = []
    parent_id, parent_label = None, ""
    for t in tables:
        cols = [district_codes(h) or districts for h in t.header[1:]] or [districts]
        for row in t.rows:
            label = row[0] or ""
            vals = list(row[1:]) + [""] * (len(cols) - len(row[1:]))
            cells = [(cols[i], v) for i, v in enumerate(vals[: len(cols)]) if v]
            sec = SECTION_RE.match(label)
            mk = MARKER_RE.match(label)
            if sec:
                parent_id, parent_label = sec.group(1), sec.group(2).rstrip(":")
                if cells:
                    out.append((parent_id, parent_label, cells, t.page))
            elif mk and parent_id:
                out.append((f"{parent_id}({mk.group(1)})", f"{parent_label} | {mk.group(2)}", cells, t.page))
    return out


_RANGE_PHRASES = [
    (rf"^(?:where the [a-z ]+ )?does not exceed ({NUM}) ?m(?:²|2)?$", "lte"),
    (rf"^(?:is )?(?:of )?({NUM}) ?m(?:²|2)? or less$", "lte"),
    (rf"^exceeds ({NUM}) ?m(?:²|2)?$", "gt"),
    (rf"^(?:is )?greater than ({NUM}) ?m(?:²|2)?$", "gt"),
    (rf"^(?:is )?less than ({NUM}) ?m(?:²|2)?$", "lt"),
    (rf"^(?:is )?({NUM}) ?m(?:²|2)? or more$", "gte"),
]


def _site_fact(parent_label: str) -> str | None:
    """Which site dimension a ':'-ended table label ranges over."""
    low = parent_label.lower()
    pats = [(r"where the site width|where the site frontage|where the frontage|with a (?:site )?(?:width|frontage) of", "site_frontage"),
            (r"where the (?:average )?site depth|with a (?:site )?depth of|where the depth", "site_depth"),
            (r"where the site area|with a site area of", "site_area")]
    for pat, fact in pats:
        if re.search(pat, low):
            return fact
    return None


def _form_regulations(rows, group_titles, matcher: _UseMatcher, unit_cap: int | None, districts):
    regs, clauses = [], []
    for cid, label, cells, page in rows:
        clauses.append(Clause(id=cid, text=f"{label}: " + " | ".join(
            f"{'/'.join(d)}: {v}" if len(cells) > 1 else v for d, v in cells), page=page))
        parent_label, _, sub = label.partition(" | ")
        sub_is_label = bool(sub) and detect_bound(sub) is not None
        metric = detect_metric(sub) if sub_is_label else detect_metric(parent_label)
        if metric is None:
            continue
        bound = detect_bound(sub) or detect_bound(parent_label)
        group = _group_for_clause(cid, group_titles)
        lo, hi = parse_unit_range(sub, unit_cap)
        if lo is None:
            lo, hi = parse_unit_range(parent_label, unit_cap)
        requires: dict = {k: v for k, v in extract_requires(label).items() if k != "tenure"}
        condition = None
        portions = re.search(r" for (portions of a building .+)$", parent_label)
        if portions and not sub:
            condition = _leftover_condition(portions.group(1), matcher)
        if sub and not sub_is_label:
            key = sub.strip().rstrip(":")
            fact = _site_fact(parent_label)
            rng = next(((re.match(p, key.lower()), op) for p, op in _RANGE_PHRASES if re.match(p, key.lower())), None)
            if fact and rng:
                requires[f"{fact}_{rng[1]}"] = num(rng[0].group(1))
            elif key.lower() in ("corner site", "a corner site"):
                requires["corner_site"] = True
            else:
                if metric == Metric.BUILDING_SEPARATION and key == "rear buildings":
                    key = "rear buildings (separation)"
                if key.lower() in CONDITION_ALIASES or key in CONDITION_ALIASES:
                    condition = CONDITION_ALIASES.get(key, CONDITION_ALIASES.get(key.lower()))
                else:
                    condition = _leftover_condition(key, matcher)
        storey = re.search(r"\b(\d)-storey\b", sub or "")
        if storey and condition is None:
            condition = f"{storey.group(1)}_storey"
        named = [u for u in matcher.find(" | ".join(_strip_conditions(x) for x in label.split(" | "))) if u != group]
        targets = named or ["*"]
        label_districts = [d for d in district_codes(label) if d in districts]
        for col_districts, value in cells:
            ds = [d for d in col_districts if not label_districts or d in label_districts]
            for qty, unit in parse_quantities(value):
                if unit is None:  # "not required" / "no minimum"
                    unit = {Metric.SITE_AREA: Unit.M2, Metric.SITE_COVERAGE: Unit.FRACTION_OF_SITE}.get(metric, Unit.M)
                m = Metric.STOREYS if unit == Unit.STOREYS else metric
                for use in targets:
                    regs.append(_Row(ds, dict(
                        use=use, group=group, metric=m, bound=bound or "max", value=qty, unit=unit,
                        min_units=lo, max_units=hi, condition=condition, requires=dict(requires),
                        clause=cid, page=page, source_text=f"{label}: {value}")))
    return regs, clauses


_FILLER = re.compile(
    r"\b(a|an|the|for|of|and|or|in|with|containing|dwelling|units?|uses?|not|less|more|than|\d+|"
    r"other than a rear building|all other|other)\b")


def _leftover_condition(key: str, matcher: _UseMatcher) -> str | None:
    low = key.lower()
    for name, _ in matcher.pairs:
        low = re.sub(r"\b" + re.escape(name) + r"s?\b", " ", low)
    low = re.sub(r"\b\d-storey\b", " ", low)
    low = re.sub(r"other than a rear building", " ", low)
    rest = _FILLER.sub(" ", low)
    if not re.search(r"[a-z]{3,}", rest):
        return None
    return CONDITION_ALIASES.get(key, slugify(key))


# --------------------------------------------------------- text rules
_SEG_SPLIT = re.compile(r",? except that[,:]? ?| \[\.\.\.\] |; (?:and |or )?|, or (?=\d)")
_FSR_VAL = re.compile(
    rf"floor space ratio (?:for (?:the )?(?:overall site|additions to existing buildings) )?"
    rf"(?:is|is increased to|to a maximum of|may be increased to)\s+({NUM})(?!\s*(?:m|%))"
)
_LIST_VAL = re.compile(rf"^({NUM})\b(?!\s*(?:m\b|m2|m²|%|units|dwelling))")
_UNITS_MAX = [
    (re.compile(r"maximum number of (?:dwelling )?units(?: for the site| on a site)? is (\d+)"), False),
    (re.compile(r"number of dwelling units[^.:;]*?must not exceed (\d+)(?: dwelling)? units?\b(?! per)"), False),
    (re.compile(r"may (?:increase|vary) the permitted number of dwelling units to (\d+)"), True),
]
_UPH = re.compile(rf"({NUM}) units per hectare")
_SITE_PROSE = re.compile(rf"\b(maximum|minimum) (site frontage|site area|site depth) (?:is|must be) (({NUM}) ?(?:m2|m²|m\b))")
_OR_CONDITIONS = re.compile(
    r",? or (?=(?:with |on |where |if |is |has )?(?:an? |the )?(?:site|frontage|lot|minimum|\d+%|corner))")
_TOP_STOREY = re.compile(r"storey\b([^.;]{0,60}?) must be a partial storey not exceeding (\d+)% of the storey immediately below")
_HEIGHT = re.compile(rf"maximum building height (?:is|may be increased to|to) ({NUM}) ?m\b")
_DISCRETION = re.compile(r"\bmay (?:increase|relax|permit|vary|allow)\b")
_DOP_CONSIDERS = re.compile(
    r",? ?if the director of planning(?: or development permit board)?(?: first)? (?:considers|is satisfied)[^;]*")
_UNPARSED_IF = re.compile(r"\b(?:if|where|provided(?: that)?)\b(?! ?:)")
_COND_TAIL = re.compile(
    r"(?:\bif|\bwhere|(?<!except )\bthat|(?<!except )provided that|for (?:buildings|developments|sites) (?:where|that)|the site)\s*(?:either)?:$")


def _segments(text: str) -> list[str]:
    return [s for s in _SEG_SPLIT.split(text) if s.strip()]


def _trailing_connector(n: RawClause) -> str | None:
    last = n.descendants()[-1] if n.children else n
    t = last.text.rstrip(" ,;.").lower()
    return "or" if t.endswith(" or") else "and" if t.endswith(" and") else None


def _alternatives(node: RawClause, include_own: bool = True, limit: int = 16) -> list[dict]:
    """Conditions in a clause subtree as a list of alternatives (OR of ANDs)."""
    own = extract_requires(node.text) if include_own else {}
    if not node.children:
        return [own or {"unparsed_condition": True}]  # a condition we could not structure
    kids = node.children
    either = _head(node.text).lower().endswith("either:")
    ors = either or any(_trailing_connector(k) == "or" for k in kids[:-1])
    child_alts = [_alternatives(k) for k in kids]
    if ors:
        combined = [a for ca in child_alts for a in ca]
    else:
        combined = [{k: v for d in combo for k, v in d.items()} for combo in itertools.product(*child_alts)]
    return [{**own, **a} for a in combined][:limit]


def _per_district_values(text: str, districts: list[str]) -> list[tuple[float, list[str]]]:
    out = []
    for m in re.finditer(rf"({NUM}) in the ((?:[A-Z0-9-]+(?:, | and | or )?)+) districts?", text):
        ds = [d for d in district_codes(m.group(2)) if d in districts]
        if ds:
            out.append((num(m.group(1)), ds))
    return out if len(out) > 1 else []


def _alternatives_text(text: str) -> list[dict]:
    """Alternatives in one run-on sentence: split on ' or ' between conditions."""
    parts = [p for p in re.split(r",? or (?=\d+% |a minimum|the site|100%)", text) if p.strip()]
    alts = [extract_requires(p) for p in parts]
    return [a for a in alts if a] or [{}]


def _nearest(c: RawClause, fn):
    node = c
    while node is not None:
        v = fn(node.text)
        if v:
            return v
        node = node.parent
    return None


class _TextRules:
    def __init__(self, districts, group_titles, matcher):
        self.districts, self.group_titles, self.matcher = districts, group_titles, matcher

    section_districts: dict[str, list[str]] = {}

    def scope(self, c: RawClause) -> list[str]:
        for txt in [n.text for n in _chain(c)] + [c.section_title or ""]:
            ds = [d for d in district_codes(txt) if d in self.districts]
            if ds:
                return ds
        # A section whose regulation table is headed by only some districts
        # (RM-7/7A: courtyard townhouse is RM-7A only) applies to those only.
        sec = re.match(r"3\.\d+", c.id)
        return list(self.section_districts.get(sec.group(0), self.districts) if sec else self.districts)

    def group(self, c: RawClause) -> str:
        despite = re.search(r"Despite (?:the [a-z ]+ in )?sections? (\d+(?:\.\d+)+)", c.root.text)
        if c.id.startswith("5.") and despite:
            return _group_for_clause(despite.group(1), self.group_titles)
        return _group_for_clause(c.id, self.group_titles)

    def uses(self, c: RawClause, segment: str) -> list[str]:
        found = self.matcher.find(_strip_conditions(segment))
        node = c.parent
        while not found and node is not None:
            found = self.matcher.find(_strip_conditions(_head(node.text).split("except that")[0]))
            node = node.parent
        g = self.group(c)
        return [u for u in found if u != g] or ["*"]

    def emit(self, c, metric, value, unit, segment, discretionary, out, alts=None, bound="max", districts=None,
             **extra):
        has_alts = bool(alts)
        tenure_ctx = detect_tenure(segment) or _nearest(c.parent, detect_tenure) if c.parent else detect_tenure(segment)
        base_req = {k: v for k, v in extract_requires(segment).items()}
        if not alts:
            parts = _OR_CONDITIONS.split(segment.lower())
            part_reqs = [extract_requires(p) for p in parts]
            if len(parts) > 1 and all(part_reqs[1:]):  # "sites less than 445 m2 or with a frontage less than 12.8 m"
                head = {k: v for k, v in part_reqs[0].items()}
                alts = [{**head}] + [r for r in part_reqs[1:]]
                base_req = {k: v for k, v in base_req.items() if k == "tenure"}
        alts = alts or [{}]
        conditional = has_alts or _UNPARSED_IF.search(_DOP_CONSIDERS.sub("", segment.lower()))
        if metric == Metric.FSR and "containing" in segment and "min_units" not in extra:
            lo, hi = parse_unit_range(_strip_conditions(segment))  # "1.45 for 4-storey townhouse containing more than 8"
            storey = re.search(r"\b(\d)-storey\b", segment)
            extra = {**extra, "min_units": lo, "max_units": hi}
            if storey and not extra.get("condition"):
                extra["condition"] = f"{storey.group(1)}_storey"
        for alt in alts:
            req = {**base_req, **alt}
            if conditional and not {k for k in req if k != "tenure"}:
                req["unparsed_condition"] = True  # an 'if ...' we could not structure: see source_text
            tenure = req.pop("tenure", None) or tenure_ctx
            for use in self.uses(c, segment):
                out.append(_Row(districts or self.scope(c), dict(
                    use=use, group=self.group(c), metric=metric, bound=bound, value=value, unit=unit,
                    tenure=tenure, discretionary=discretionary, requires=req, clause=c.id, page=c.page,
                    source_text=c.subtree_text() if c.children else c.text, **extra)))

    def run(self, raw: list[RawClause]) -> list[_Row]:
        out: list[_Row] = []
        for c in raw:
            ctx_discretion = any(_DISCRETION.search(_head(n.text)) for n in _chain(c)[1:])
            cond_children = bool(c.children) and bool(_COND_TAIL.search(_head(c.text)))
            alts = _alternatives(c, include_own=False) if cond_children else None
            for seg in _segments(c.text):
                low = seg.lower()
                pre_disc = lambda pos: bool(_DISCRETION.search(low[:pos])) or ctx_discretion
                # FSR ---------------------------------------------------
                for m in _FSR_VAL.finditer(low):
                    if "relax" in low[: m.start()] and "relax the permitted" not in low:
                        continue
                    per_district = _per_district_values(seg[m.start(1):], self.districts)
                    if per_district:  # "2.50 in the RR-3A district and 3.50 in the RR-3B and RR-3C districts"
                        for val, ds in per_district:
                            self.emit(c, Metric.FSR, val, Unit.RATIO, seg, pre_disc(m.start()), out, alts, districts=ds)
                    else:
                        self.emit(c, Metric.FSR, num(m.group(1)), Unit.RATIO, seg, pre_disc(m.start()), out, alts)
                # Max dwelling units -----------------------------------
                for pat, disc in _UNITS_MAX:
                    for m in pat.finditer(low):
                        self.emit(c, Metric.DWELLING_UNITS, int(m.group(1)), Unit.COUNT, seg,
                                  disc or pre_disc(m.start()), out, alts)
                # Dwelling unit density --------------------------------
                ctx = " ".join(_head(n.text).lower() for n in _chain(c))
                if "dwelling unit" in ctx or "number of dwelling units" in ctx:
                    for m in _UPH.finditer(low):
                        self.emit(c, Metric.UNITS_PER_HECTARE, num(m.group(1)), Unit.UNITS_PER_HA, seg,
                                  pre_disc(m.start()) or "permit an increase" in ctx, out, alts)
                # Partial top storey -----------------------------------
                for m in _TOP_STOREY.finditer(low):
                    rear = "of a rear building" in m.group(1) or "of a rear building" in low[: m.start()]
                    self.emit(c, Metric.TOP_STOREY_FRACTION, int(m.group(2)) / 100, Unit.RATIO, seg, False, out,
                              condition="rear_building" if rear else None)
                # Prose site limits ("The maximum site frontage is 60.7 m") ----
                for m in _SITE_PROSE.finditer(low):
                    metric = {"site frontage": Metric.SITE_FRONTAGE, "site area": Metric.SITE_AREA,
                              "site depth": Metric.SITE_DEPTH}[m.group(2)]
                    qty = parse_quantities(m.group(3))
                    if qty:
                        self.emit(c, metric, qty[0][0], qty[0][1], seg, pre_disc(m.start()), out, alts,
                                  bound="max" if m.group(1) == "maximum" else "min")
                # Conditional building height (prose "despite" rules) ---
                for m in _HEIGHT.finditer(low):
                    disc = pre_disc(m.start())
                    rows_before = len(out)
                    self.emit(c, Metric.BUILDING_HEIGHT, num(m.group(1)), Unit.M, seg, disc, out, alts)
                    if not disc and not any(r.kw["requires"] for r in out[rows_before:]):
                        del out[rows_before:]  # unconditional heights come from the tables
            # Value lists under "... floor space ratio is:" / "to a maximum of:" ----
            parent = c.parent
            phead = _head(parent.text) if parent is not None else ""
            if parent is not None and phead.endswith(":") and not _COND_TAIL.search(phead):
                plow = phead.lower()
                m = _LIST_VAL.match(c.text.strip())
                um = re.match(r"^(\d+) (?:dwelling )?units?\b(?! per)", c.text.strip())
                if um and "number of dwelling units" in plow and re.search(r"(?:must not|does not|not) exceed:$", plow):
                    disc = bool(_DISCRETION.search(plow))
                    inherited = {k: v for k, v in extract_requires(plow).items() if k != "tenure"}
                    self.emit(c, Metric.DWELLING_UNITS, int(um.group(1)), Unit.COUNT, c.text, disc, out,
                              [inherited] if inherited else None)
                if m and "floor space ratio" in plow[-160:]:
                    disc = bool(_DISCRETION.search(plow)) or any(_DISCRETION.search(n.text) for n in _chain(parent)[1:])
                    c_alts = _alternatives(c, include_own=False) if c.children and _COND_TAIL.search(_head(c.text)) else None
                    tail = parent.text.split(" [...] ", 1)[1] if " [...] " in parent.text else ""
                    tail = _DOP_CONSIDERS.sub("", tail.lower()).strip()
                    tail_alts = _alternatives_text(tail) if re.search(r"\b(?:if|where|provided)\b", tail) else None
                    self.emit(c, Metric.FSR, num(m.group(1)), Unit.RATIO, c.text, disc, out,
                              c_alts or tail_alts, condition=_purpose(c.text))
        return out


def _head(text: str) -> str:
    """Clause text without the '[...] except that ...' tail build_clauses appends."""
    return text.split(" [...] ")[0].rstrip()


def _strip_conditions(seg: str) -> str:
    """Drop 'to facilitate the retention of ...' / 'if ...' tails before looking for use names."""
    return re.split(r"\bto facilitate\b|\bif the\b|\bif a\b|\bprovided\b|\bon a site with\b|\bother than\b|\bexcept\b"
                    r"|\bfor sites where\b|\bwhere there is\b", seg)[0]


def _purpose(text: str) -> str | None:
    m = re.search(r"to facilitate (?:the )?(.+?)(?: if |,|;|$)", text)
    return re.sub(r"^an?_", "", slugify(m.group(1)))[:60] if m else None


def _chain(c: RawClause) -> list[RawClause]:
    out, node = [], c
    while node is not None:
        out.append(node)
        node = node.parent
    return out


def _fsr_tables(raw: list[RawClause], rules: _TextRules) -> list[_Row]:
    """'Maximum Floor Space Ratio by Minimum Site Area' tables (R3, RR-2)."""
    out = []
    for c in raw:
        tabs = [t for t in c.tables if t.header and "Floor Space Ratio by" in t.header[0]]
        if not tabs:
            continue
        rows = [r for t in tabs for r in t.rows]
        areas = next(([num(AREA_CELL_RE.match(x).group(1)) for x in r if x]
                      for r in rows if r and all(AREA_CELL_RE.match(x) for x in r if x)), None)
        if not areas:
            continue
        tenure = _nearest(c, detect_tenure)
        for r in rows:
            label, vals = r[0], [v for v in r[1:] if v]
            if not re.match(r"^\(", label or "") or len(vals) != len(areas):
                continue
            req = extract_requires(label)
            req.pop("tenure", None)
            mk = MARKER_RE.match(label)
            cid = f"{c.id}({mk.group(1)})" if mk else c.id
            for area, v in zip(areas, vals):
                out.append(_Row(rules.scope(c), dict(
                    use="*", group=rules.group(c), metric=Metric.FSR, bound="max", value=num(v), unit=Unit.RATIO,
                    tenure=tenure, requires={**req, "site_area_gte": area}, clause=cid, page=c.page,
                    source_text=f"{c.text} | {label} | min site area {area:g} m2: {v}")))
    return out


def _family_unit_rows(table: Block, clause_id: str, group: str, districts) -> list[_Row]:
    """2.2.8-style table: min 2+ bedroom units by building size and tenure."""
    rows = []
    for row in table.rows:
        lo, hi = parse_unit_range(row[0])
        if lo is None:
            continue
        for tenure, cell in zip(("rental", "strata_or_mixed"), row[1:3]):
            q = re.match(r"(\d+)", cell or "")
            if q:
                rows.append(_Row(list(districts), dict(
                    use="*", group=group, metric=Metric.FAMILY_UNITS, bound="min",
                    value=int(q.group(1)), unit=Unit.COUNT, min_units=lo, max_units=hi, tenure=tenure,
                    clause=clause_id, page=table.page, source_text=" | ".join(row))))
    return rows


def _rental_only(raw: list[RawClause], rules: _TextRules) -> set[str]:
    """Districts where all dwelling units must be rental, unconditionally."""
    out = set()
    pat = re.compile(r"(?:all dwelling units|the form of tenure for the residential floor area) must be secured as "
                     r"(?:100% )?residential rental tenure(?:,? except that 1 dwelling unit[^.]*)?[;.]?$", re.IGNORECASE)
    for c in raw:
        if pat.search(c.text.strip()):
            out.update(rules.scope(c))
    return out


# ---------------------------------------------------------------- entry
def parse_schedule_pdf(pdf_path: str | Path) -> list[DistrictSchedule]:
    """Parse one district schedule PDF into one DistrictSchedule per district it covers."""
    pdf_path = Path(pdf_path)
    blocks = list(iter_blocks(pdf_path))
    with pdfplumber.open(pdf_path) as pdf:
        meta, npages = pdf.metadata or {}, len(pdf.pages)
        footer = pdf.pages[0].extract_text() or ""
    version = re.search(r"City of Vancouver\s+(\w+ \d{4})", footer)

    title = next(b.text for b in blocks if b.kind == "heading")
    raw = build_clauses(blocks)

    use_tables, reg_tables, overview_tables, family_table = [], [], [], None
    for b in blocks:
        if b.kind != "table":
            continue
        if b.header[:2] == ["Use", "Approval"]:
            use_tables.append(b)
        elif b.header[:1] == ["Minimum Site Area"]:
            overview_tables.append(b)
        elif b.header and b.header[0] == "Regulations":
            reg_tables.append(b)
        elif b.rows and "number of dwelling units" in (b.rows[0][0] or "").lower():
            family_table = b
        elif family_table is not None and b.rows and "dwelling" in (b.rows[0][0] or "").lower() and not b.header:
            family_table.rows.extend(b.rows)  # continuation across page break

    districts = list(dict.fromkeys(d for t in reg_tables for h in t.header[1:] for d in district_codes(h)))
    for d in district_codes(title):
        if d not in districts:
            districts.append(d)
    if not districts:
        districts = [title]

    group_titles = {}
    for c in raw:
        if re.fullmatch(r"3\.\d+", c.id) and c.section_title:
            group_titles[c.id] = use_slug(SECTION_RE.match(c.section_title).group(2))

    uses = _parse_use_table(use_tables)
    overview = _parse_overview(overview_tables)
    matcher = _UseMatcher([u.name for u in uses] + [e.name for e in overview])
    group_members: dict[str, list[str]] = {}
    for sec, g in group_titles.items():
        title_txt = next(c.section_title for c in raw if c.id == sec)
        members = [u for e in overview if e.section == sec for u in e.uses]
        if "all uses" in title_txt.lower():
            members = ["*"] + members
        members += matcher.find(SECTION_RE.match(title_txt).group(2))
        group_members[g] = list(dict.fromkeys(group_members.get(g, []) + members))

    unit_cap = max([int(m) for c in raw for m in re.findall(r"maximum number of (?:dwelling )?units[^.]*? is (\d+)", c.text)]
                   + [u.max_units for u in uses if u.max_units] or [0]) or None

    rules = _TextRules(districts, group_titles, matcher)
    rows = _regulation_table_rows(reg_tables, districts)
    sec_ds: dict[str, set] = {}
    for cid, _, cells, _ in rows:
        sec = re.match(r"3\.\d+", cid)
        if sec:
            sec_ds.setdefault(sec.group(0), set()).update(d for ds, _ in cells for d in ds)
    rules.section_districts = {k: [d for d in districts if d in v] for k, v in sec_ds.items() if v}
    regs, table_clauses = _form_regulations(rows, group_titles, matcher, unit_cap, districts)
    regs += rules.run(raw)
    regs += _fsr_tables(raw, rules)
    if family_table:
        cid = next((c.id for c in raw if "minimum number of dwelling units with 2 or more bedrooms" in c.text), "2.2.8")
        regs += _family_unit_rows(family_table, cid, _group_for_clause("3.1", group_titles), districts)
    rental = _rental_only(raw, rules)

    clauses = [Clause(id=c.id, text=c.text, page=c.page, section_title=c.section_title) for c in raw] + table_clauses
    clauses.sort(key=lambda c: _clause_sort_key(c.id))

    intent = next((c.text for c in raw if c.id == "1.1"), None)
    name = re.search(r"intent of this (.+?) district schedule", intent or "")
    source = SourceDocument(
        filename=pdf_path.name,
        sha256=hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
        title=meta.get("Title"),
        version_label=version.group(1) if version else None,
        pages=npages,
    )
    figures = [Figure(caption=b.text, page=b.page) for b in blocks if b.kind == "figure"]

    out = []
    for d in districts:
        def mine(text):
            ds = [x for x in district_codes(text) if x in districts]
            return not ds or d in ds

        out.append(DistrictSchedule(
            district=d,
            name=name.group(1) if name else None,
            intent=intent,
            source=source,
            uses=[u for u in uses if mine(u.name)],
            regulations=[Regulation(district=d, **r.kw) for r in regs if d in r.districts],
            clauses=clauses,
            figures=figures,
            use_groups=group_titles,
            group_members=group_members,
            overview=[e for e in overview if mine(e.name)],
            rental_only=d in rental,
            schedule_districts=districts,
            parser_version=__version__,
        ))
    return out


def parse_district_schedule(pdf_path: str | Path, district: str | None = None) -> DistrictSchedule:
    """Parse a PDF and return one district (required if the PDF covers several)."""
    scheds = parse_schedule_pdf(pdf_path)
    if district is None:
        if len(scheds) > 1:
            raise ValueError(f"{Path(pdf_path).name} covers {[s.district for s in scheds]}; pass district=")
        return scheds[0]
    return next(s for s in scheds if s.district == district)


def _clause_sort_key(cid: str):
    nums = re.match(r"[\d.]+", cid).group(0).split(".")
    return ([int(n) for n in nums if n] + [0] * 6)[:6], cid
