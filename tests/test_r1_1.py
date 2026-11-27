"""Golden tests: values checked by hand against the R1-1 PDF (June 2026)."""
from pathlib import Path

import pytest

from vanzoning import Metric, store
from vanzoning.envelope import Site, building_options

PDF = Path(__file__).parent / "fixtures" / "r1-1.pdf"


@pytest.fixture(scope="module", params=["bundled", "fresh_parse"])
def r1(request):
    if request.param == "bundled":
        return store.load("R1-1")
    if not PDF.exists():
        pytest.skip("fixture PDF not present")
    from vanzoning.parse.schedule import parse_district_schedule

    return parse_district_schedule(PDF)


def test_metadata(r1):
    assert r1.district == "R1-1"
    assert r1.name == "Residential Inclusive"
    assert r1.source.version_label == "June 2026"


@pytest.mark.parametrize(
    "metric,use,bound,expected,filters",
    [
        (Metric.FSR, "multiple_dwelling", "max", 1.00, {}),
        (Metric.FSR, "single_detached_house", "max", 0.60, {}),
        (Metric.FSR, "duplex", "max", 0.70, {}),
        (Metric.FSR, "duplex_with_secondary_suite", "max", 0.70, {}),
        (Metric.DWELLING_UNITS, "multiple_dwelling", "max", 8, {"tenure": "rental"}),
        (Metric.DWELLING_UNITS, "multiple_dwelling", "max", 6, {"tenure": "strata_or_mixed"}),
        (Metric.BUILDING_HEIGHT, "multiple_dwelling", "max", 8.5, {"condition": "rear_building"}),
        (Metric.BUILDING_HEIGHT, "multiple_dwelling", "max", 11.5, {"condition": None}),
        (Metric.BUILDING_HEIGHT, "duplex", "max", 11.5, {}),
        (Metric.STOREYS, "duplex", "max", 3, {}),
        (Metric.FRONT_YARD, "duplex", "min", 4.9, {}),
        (Metric.SIDE_YARD, "multiple_dwelling", "min", 1.2, {}),
        (Metric.REAR_YARD, "multiple_dwelling", "min", 0.9, {"condition": "courtyard"}),
        (Metric.REAR_YARD, "single_detached_house", "min", 10.7, {}),
        (Metric.SITE_AREA, "duplex", "min", 306, {}),
        (Metric.SITE_FRONTAGE, "single_detached_house", "min", 7.3, {}),
        (Metric.SITE_COVERAGE, "duplex", "max", 0.50, {}),
        (Metric.IMPERMEABLE_AREA, "duplex", "max", 0.75, {}),
        (Metric.BUILDING_DEPTH, "multiple_dwelling", "max", 19.8, {}),
        (Metric.BUILDING_WIDTH, "multiple_dwelling", "max", 17.4, {}),
    ],
)
def test_values(r1, metric, use, bound, expected, filters):
    assert r1.value(metric, use, bound, **filters) == pytest.approx(expected)


def test_multiplex_site_area_bands(r1):
    bands = {(r.min_units, r.max_units, r.bound): r.value for r in r1.get(Metric.SITE_AREA, "multiple_dwelling")}
    assert bands == {(6, 8, "min"): 557, (5, 5, "min"): 464, (3, 4, "min"): 306, (3, 3, "max"): 463}


def test_relaxations_are_discretionary(r1):
    rows = r1.get(Metric.FSR, "infill", "max", include_discretionary=True, include_conditional=True)
    assert [r.value for r in rows if r.discretionary] == [0.85]
    assert rows[-1].requires == {"retention": True}
    assert r1.value(Metric.FSR, "infill", "max") == 0.60  # outright


def test_uses(r1):
    by = {u.use: u for u in r1.uses}
    assert by["duplex"].approval == "outright"
    assert by["multiple_dwelling"].approval == "conditional"
    assert by["multiple_dwelling"].use_specific_regulations == ["2.2.1", "2.2.2", "2.2.7", "2.2.8", "2.2.9"]
    assert len(r1.uses) == 47


def test_family_units(r1):
    v = r1.value(Metric.FAMILY_UNITS, "multiple_dwelling", "min", min_units=5, tenure="strata_or_mixed")
    assert v == 3


def test_every_rule_has_provenance(r1):
    for r in r1.regulations:
        assert r.clause and r.page >= 1 and r.source_text


def test_no_diagram_text_in_clauses(r1):
    assert not any("Diagram:" in c.text for c in r1.clauses)
    assert not any("City of Vancouver June" in c.text for c in r1.clauses)


def test_33ft_lot_allows_fourplex_not_sixplex(r1):
    opts = {(o.use, o.units): o for o in building_options(r1, Site(area_m2=306, frontage_m=10.06, depth_m=37.2))}
    assert opts[("multiple_dwelling", 4)].eligible
    assert not opts[("multiple_dwelling", 6)].eligible
    assert opts[("duplex", 2)].max_floor_area_m2 == pytest.approx(0.7 * 306)


def test_rental_unlocks_8_units(r1):
    site = Site(area_m2=622, frontage_m=16.8, depth_m=37.2)
    strata = {o.units: o.eligible for o in building_options(r1, site) if o.use == "multiple_dwelling"}
    site.tenure = "rental"
    rental = {o.units: o.eligible for o in building_options(r1, site) if o.use == "multiple_dwelling"}
    assert not strata[8] and rental[8]


def test_envelope_vs_fsr_33ft_lot(r1):
    # 10.06 x 30.4 m: width 10.06-2*1.2, depth 30.4-4.9-10.7, 3 storeys -> ~340 m2 > FSR cap 306
    o = next(o for o in building_options(r1, Site(306, 10.06, 30.4)) if o.use == "multiple_dwelling" and o.units == 4)
    assert o.envelope_floor_area_m2 == pytest.approx((10.06 - 2.4) * 14.8 * 3)
    assert o.binding == "fsr" and o.max_floor_area_m2 == pytest.approx(306)
    # SDH: 50% coverage and a 50% partial third storey
    sdh = next(o for o in building_options(r1, Site(306, 10.06, 30.4)) if o.use == "single_detached_house")
    assert sdh.floors == 3 and sdh.envelope_floor_area_m2 == pytest.approx((10.06 - 2.4) * 14.8 * 2.5)


def test_multiple_dwelling_headline_limits(r1):
    """Headline limits read off the R1-1 PDF by hand."""
    want = dict(fsr=1, height=11.5, floors=3, front=4.9, side=1.2, rear=10.7, building_width=17.4, building_depth=19.8)
    u, M = "multiple_dwelling", Metric
    assert r1.value(M.FSR, u, "max") == want["fsr"]
    assert r1.value(M.BUILDING_HEIGHT, u, "max", condition=None) == want["height"]
    assert r1.value(M.STOREYS, u, "max", condition=None) == want["floors"]
    assert r1.value(M.FRONT_YARD, u, "min") == want["front"]
    assert r1.value(M.SIDE_YARD, u, "min") == want["side"]
    assert r1.value(M.REAR_YARD, u, "min", condition=None) == want["rear"]
    assert r1.value(M.BUILDING_WIDTH, u, "max") == want["building_width"]
    assert r1.value(M.BUILDING_DEPTH, u, "max") == want["building_depth"]
    fam = {(r.min_units, r.tenure): r.value for r in r1.get(M.FAMILY_UNITS, u)}
    assert [fam[(n, "strata_or_mixed")] for n in (3, 4, 5, 6)] == [2, 2, 3, 3]
    assert [fam[(n, "rental")] for n in range(3, 9)] == [1, 1, 2, 2, 2, 3]


def test_ga_and_milp_agree():
    import runpy, io, contextlib
    out = {}
    for name in ("milp_max_units", "ga_max_units"):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            runpy.run_path(str(Path(__file__).parents[1] / "examples" / f"{name}.py"))
        out[name] = int(buf.getvalue().strip().splitlines()[-1].split(":")[1])
    assert out["milp_max_units"] == out["ga_max_units"] == 27
