"""All residential districts: golden values read off the PDFs by hand,
checked against the parsed schedules.

Runs on the bundled JSON. Set VANZONING_PDF_DIR to a folder of the City's
district schedule PDFs to also re-parse them and check nothing drifted.
"""
import os
from pathlib import Path

import pytest

from vanzoning import Metric as M
from vanzoning import store
from vanzoning.summary import summarize

# district: (use, dwelling units, site facts, expected headline limits from summarize())
HEADLINE = {
    "R1-1": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1, 'height': 11.5, 'floors': 3, 'front': 4.9, 'side': 1.2, 'rear': 10.7, 'building_depth': 19.8, 'building_width': 17.4, 'rental_only': False}),
    "R3-1": ('apartment', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1.6, 'height': 23, 'front': 3.7, 'side': 1.8, 'rear': 3.1, 'min_area': 460, 'rental_only': False}),
    "R3-2": ('apartment', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1.6, 'height': 23, 'front': 3.7, 'side': 1.8, 'rear': 3.1, 'min_area': 460}),
    "R3-3": ('apartment', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1.6, 'height': 23, 'front': 3.7, 'side': 1.8, 'rear': 3.1, 'min_area': 460, 'rental_only': False}),
    "R4-1": ('apartment', 3, {'site_area': 1672.62, 'site_frontage': 45.7, 'site_depth': 36.6},
        {'fsr': 4, 'height': 47, 'front': 3.7, 'side': 3.7, 'rear': 6.1, 'min_area': 1532, 'min_width': 45.7, 'max_width': 60.7, 'rental_only': False}),
    "R5-1": ('apartment', 3, {'site_area': 1672.62, 'site_frontage': 45.7, 'site_depth': 36.6},
        {'height': 84, 'front': 3.7, 'side': 3.7, 'rear': 6.1, 'min_area': 1532, 'min_width': 45.7, 'max_width': 60.7, 'rental_only': False}),
    "R5-2": ('apartment', 3, {'site_area': 1672.62, 'site_frontage': 45.7, 'site_depth': 36.6},
        {'height': 69, 'front': 3.7, 'side': 3.7, 'rear': 6.1, 'min_area': 1532, 'min_width': 45.7, 'max_width': 60.7, 'rental_only': False}),
    "R5-3": ('apartment', 3, {'site_area': 1672.62, 'site_frontage': 45.7, 'site_depth': 36.6},
        {'height': 84, 'front': 3.7, 'side': 3.7, 'rear': 6.1, 'min_area': 1532, 'min_width': 45.7, 'max_width': 60.7, 'rental_only': False}),
    "R5-4": ('apartment', 3, {'site_area': 1672.62, 'site_frontage': 45.7, 'site_depth': 36.6},
        {'height': 84, 'front': 3.7, 'side': 3.7, 'rear': 6.1, 'min_area': 1532, 'min_width': 45.7, 'max_width': 60.7, 'rental_only': False}),
    "RM-1": ('multiple_dwelling', 3, {'site_area': 669.78, 'site_frontage': 18.3, 'site_depth': 36.6},
        {'fsr': 0.4, 'approved_fsr': 1.2, 'height': 10.7, 'floors': 2, 'side': 1.5, 'rear': 0.6, 'min_area': 604, 'min_width': 18.3, 'coverage': 0.55, 'depth_fraction': 0.4, 'rental_only': False}),
    "RM-10": ('apartment', 3, {'site_area': 1098.0, 'site_frontage': 30, 'site_depth': 36.6},
        {'fsr': 0.9, 'height': 20, 'front': 3.7, 'side': 3, 'rear': 6.1, 'min_area': 855, 'min_width': 30, 'max_width': 50, 'coverage': 0.5, 'building_depth': 21.3, 'rental_only': False}),
    "RM-11": ('apartment', 3, {'site_area': 1339.56, 'site_frontage': 36.6, 'site_depth': 36.6},
        {'fsr': 0.75, 'height': 13.7, 'front': 3.7, 'side': 2.1, 'rear': 6.1, 'min_area': 1000, 'min_width': 36.6, 'max_width': 50, 'coverage': 0.55, 'rental_only': False}),
    "RM-12": ('apartment', 3, {'site_area': 1339.56, 'site_frontage': 36.6, 'site_depth': 36.6},
        {'fsr': 1.7, 'height': 13.7, 'floors': 4, 'front': 3.7, 'side': 2.1, 'rear': 6.1, 'min_area': 1000, 'min_width': 36.6, 'coverage': 0.55, 'building_width': 26, 'rental_only': False}),
    "RM-2": ('multiple_dwelling', 3, {'site_area': 550, 'site_frontage': 15.0, 'site_depth': 36.667},
        {'fsr': 0.75, 'height': 10.7, 'front': 6.1, 'side': 2.1, 'rear': 10.7, 'min_area': 550, 'max_area': 3000, 'rental_only': False}),
    "RM-3": ('multiple_dwelling', 3, {'site_area': 550, 'site_frontage': 15.0, 'site_depth': 36.667},
        {'fsr': 1, 'height': 36.6, 'front': 6.1, 'side': 2.1, 'rear': 10.7, 'min_area': 550, 'rental_only': False}),
    "RM-3A": ('multiple_dwelling', 3, {'site_area': 550, 'site_frontage': 15.0, 'site_depth': 36.667},
        {'fsr': 1, 'height': 10.7, 'front': 6.1, 'side': 2.1, 'rear': 10.7, 'min_area': 550, 'rental_only': False}),
    "RM-4": ('multiple_dwelling', 3, {'site_area': 550, 'site_frontage': 15.0, 'site_depth': 36.667},
        {'fsr': 1.45, 'height': 10.7, 'front': 6.1, 'side': 2.1, 'rear': 10.7, 'min_area': 550, 'max_width': 45.8, 'rental_only': False}),
    "RM-5": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1, 'approved_fsr': 1.5, 'height': 18.3, 'front': 3.7, 'side': 2.1, 'rear': 2.1, 'coverage': 0.5, 'rental_only': False}),
    "RM-5A": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1, 'approved_fsr': 2.2, 'height': 18.3, 'front': 3.7, 'side': 2.1, 'rear': 2.1, 'coverage': 0.5, 'rental_only': False}),
    "RM-5B": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1, 'approved_fsr': 2.75, 'height': 18.3, 'front': 3.7, 'side': 2.1, 'rear': 2.1, 'coverage': 0.5, 'rental_only': False}),
    "RM-5C": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1, 'approved_fsr': 2.2, 'height': 18.3, 'front': 3.7, 'side': 2.1, 'rear': 2.1, 'coverage': 0.5, 'rental_only': False}),
    "RM-5D": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1, 'approved_fsr': 2.2, 'height': 18.3, 'front': 3.7, 'side': 2.1, 'rear': 2.1, 'coverage': 0.5, 'rental_only': False}),
    "RM-6": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1, 'approved_fsr': 2.5, 'height': 12.2, 'front': 12.2, 'side': 2.1, 'rear': 3.7, 'rental_only': False}),
    "RM-7": ('townhouse', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 0.6, 'approved_fsr': 1.2, 'height': 10.7, 'floors': 3, 'front': 6.1, 'side': 1.2, 'min_area': 445, 'min_width': 12.8, 'coverage': 0.55, 'depth_fraction': 0.4, 'top_fraction': 0.5, 'rental_only': False}),
    "RM-7A": ('townhouse', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 0.6, 'approved_fsr': 1.2, 'height': 10.7, 'floors': 3, 'front': 6.1, 'side': 1.2, 'rear': 1.8, 'min_area': 445, 'min_width': 12.8, 'coverage': 0.55, 'depth_fraction': 0.4, 'top_fraction': 0.5, 'rental_only': False}),
    "RM-8": ('townhouse', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1.2, 'height': 11.5, 'floors': 3, 'front': 3.7, 'side': 1.2, 'rear': 1.8, 'min_area': 445, 'min_width': 12.8, 'coverage': 0.55, 'depth_fraction': 0.4, 'building_width': 27, 'rental_only': False}),
    "RM-8A": ('townhouse', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1.2, 'height': 11.5, 'floors': 3, 'front': 3.7, 'side': 1.2, 'rear': 1.8, 'min_area': 445, 'min_width': 12.8, 'coverage': 0.55, 'depth_fraction': 0.4, 'building_width': 27, 'rental_only': False}),
    "RM-9": ('apartment', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 0.75, 'height': 12.2, 'floors': 4, 'front': 4.9, 'side': 2.1, 'rear': 3.7, 'min_area': 445, 'min_width': 12.8, 'max_width': 50, 'coverage': 0.55, 'rental_only': False}),
    "RM-9A": ('apartment', 3, {'site_area': 556.32, 'site_frontage': 15.2, 'site_depth': 36.6},
        {'fsr': 0.7, 'height': 13.7, 'floors': 4, 'front': 3.7, 'side': 2.1, 'rear': 3.7, 'min_area': 445, 'min_width': 15.2, 'max_width': 50, 'coverage': 0.55, 'rental_only': False}),
    "RM-9B": ('apartment', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 0.7, 'height': 12.2, 'floors': 4, 'front': 4.9, 'side': 2.1, 'rear': 3.7, 'min_area': 445, 'min_width': 12.8, 'max_width': 50, 'coverage': 0.55, 'rental_only': False}),
    "RR-1": ('townhouse', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1, 'height': 11.5, 'floors': 3, 'front': 3.7, 'side': 1.2, 'rear': 3.1, 'min_area': 303, 'min_width': 10, 'rental_only': True}),
    "RR-2A": ('apartment', 3, {'site_area': 613, 'site_frontage': 15.0, 'site_depth': 40.867},
        {'fsr': 1.75, 'height': 13.7, 'floors': 4, 'front': 3.7, 'side': 1.8, 'rear': 7.6, 'min_area': 613, 'building_depth': 22.8, 'building_width': 45.7, 'rental_only': True}),
    "RR-2B": ('apartment', 3, {'site_area': 613, 'site_frontage': 15.0, 'site_depth': 40.867},
        {'fsr': 2.2, 'height': 19.8, 'floors': 6, 'front': 3.7, 'side': 2.4, 'rear': 7.6, 'min_area': 613, 'building_depth': 22.8, 'building_width': 45.7, 'rental_only': True}),
    "RR-3A": ('apartment', 3, {'site_area': 920, 'site_frontage': 15.0, 'site_depth': 61.333},
        {'height': 15.3, 'floors': 4, 'front': 2.5, 'rear': 6.1, 'min_area': 920, 'rental_only': True}),
    "RR-3B": ('apartment', 3, {'site_area': 920, 'site_frontage': 15.0, 'site_depth': 61.333},
        {'height': 23, 'floors': 6, 'front': 2.5, 'rear': 6.1, 'min_area': 920, 'rental_only': True}),
    "RR-3C": ('apartment', 3, {'site_area': 920, 'site_frontage': 15.0, 'site_depth': 61.333},
        {'height': 23, 'floors': 6, 'front': 2.5, 'rear': 6.1, 'min_area': 920, 'rental_only': True}),
    "RT-1": ('duplex', 2, {'site_area': 780, 'site_frontage': 15.0, 'site_depth': 52.0},
        {'fsr': 0.6, 'height': 6.1, 'floors': 1, 'front': 7.3, 'side': 1.5, 'rear': 10.7, 'min_area': 780, 'coverage': 0.45, 'rental_only': False}),
    "RT-10": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15, 'site_depth': 36.6},
        {'fsr': 0.4, 'approved_fsr': 0.8, 'height': 10.7, 'floors': 2, 'side': 1.2, 'coverage': 0.45, 'depth_fraction': 0.4, 'rental_only': False}),
    "RT-11": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 0.6, 'approved_fsr': 0.85, 'height': 10.7, 'floors': 2, 'side': 1.2, 'min_width': 9.8, 'coverage': 0.45, 'depth_fraction': 0.4, 'rental_only': False}),
    "RT-2": ('multiple_dwelling', 3, {'site_area': 668, 'site_frontage': 15.0, 'site_depth': 44.533},
        {'fsr': 0.75, 'height': 9.2, 'front': 7.3, 'side': 1.5, 'rear': 10.7, 'min_area': 668, 'coverage': 0.4, 'rental_only': False}),
    "RT-3": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 0.6, 'approved_fsr': 0.75, 'height': 10.7, 'floors': 3, 'front': 3.7, 'side': 1.5, 'rear': 20, 'min_area': 510, 'coverage': 0.45, 'top_fraction': 0.5, 'rental_only': False}),
    "RT-4": ('duplex', 2, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 0.6, 'height': 10.7, 'floors': 3, 'front': 7.3, 'side': 1.5, 'rear': 10.7, 'min_area': 306, 'coverage': 0.45, 'top_fraction': 0.5, 'rental_only': False}),
    "RT-4A": ('duplex', 2, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 0.6, 'height': 10.7, 'floors': 3, 'front': 7.3, 'side': 1.5, 'rear': 10.7, 'min_area': 306, 'coverage': 0.45, 'top_fraction': 0.5, 'rental_only': False}),
    "RT-5": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 0.6, 'approved_fsr': 0.75, 'height': 10.7, 'floors': 3, 'front': 7.3, 'side': 1.5, 'rear': 10.7, 'min_area': 338, 'coverage': 0.45, 'depth_fraction': 0.45, 'units_per_ha': 74, 'top_fraction': 0.5, 'rental_only': False}),
    "RT-7": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1, 'height': 11.5, 'floors': 3, 'front': 4.9, 'side': 1.2, 'rear': 10.7, 'building_depth': 19.8, 'building_width': 17.4, 'rental_only': False}),
    "RT-8": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 0.5, 'approved_fsr': 0.75, 'height': 10.7, 'floors': 2, 'side': 1.5, 'coverage': 0.45, 'depth_fraction': 0.35, 'units_per_ha': 62, 'rental_only': False}),
    "RT-9": ('multiple_dwelling', 3, {'site_area': 549.0, 'site_frontage': 15.0, 'site_depth': 36.6},
        {'fsr': 1, 'height': 11.5, 'floors': 3, 'front': 4.9, 'side': 1.2, 'rear': 10.7, 'building_depth': 19.8, 'building_width': 17.4, 'rental_only': False}),
}

# Limits that are easy to misread: conditional, prose-only, or not a rule at all.
# (field, value per the PDF, clause / why). None = no unconditional value.
TRICKY_LIMITS = {
    "R3-2": [("rental_only", True, "3.1.1.4(a): must be 100% rental")],
    "R5-1": [("fsr", None, "3.1.1.2: every FSR path needs 20% below-market rental or social housing")],
    "R5-2": [("fsr", None, "3.1.1.4(b): 5.50 only with 20% below-market rental or 100% social")],
    "R5-3": [("fsr", None, "3.1.1.7: conditional on below-market rental / social housing")],
    "R5-4": [("fsr", None, "3.1.1.9: conditional on below-market rental / social housing")],
    "RM-1": [("front", 3.1, "table 3.1.2.4 is 3.1 m; 4.9 m applies only within 4.9 m of side lines (3.1.2.11)")],
    "RM-8": [("units_per_ha", None, "3.1.1.4: 145/ha only where FSR exceeds 0.90 (needs an fsr fact)")],
    "RM-8A": [("units_per_ha", None, "3.1.1.4: 145/ha only where FSR exceeds 0.90")],
    "RR-3A": [("fsr", None, "3.1.1.3: needs non-dwelling FSR of at least 0.35"),
              ("side", None, "3.1.2.4: 3.7 m only beside an R-district side yard, else not required")],
    "RR-3B": [("fsr", None, "3.1.1.3: needs non-dwelling FSR of at least 0.35"),
              ("side", None, "3.1.2.4: conditional")],
    "RR-3C": [("fsr", None, "3.1.1.3: needs non-dwelling FSR of at least 0.35"),
              ("side", None, "3.1.2.4: conditional")],
    "RT-1": [("max_units", None, "duplex unit count is a domain constant (envelope.UNITS_PER_USE), not a rule")],
    "RT-4": [("max_units", None, "same as RT-1")],
    "RT-4A": [("max_units", None, "same as RT-1")],
    "RT-2": [("floors", None, "3.1.2.2 limits height to 9.2 m with no storey count")],
    "RT-10": [("rear", 0.6, "table 3.1.2.5 is 0.6 m"),
              ("min_area", 306.0, "511 m2 is for more than 1 principal building (3.1.2.9, prose)"),
              ("min_width", None, "15.0 m is for more than 1 principal building (3.1.2.9, prose)")],
    "RT-11": [("rear", 0.6, "table 3.1.2.6 is 0.6 m"),
              ("min_area", None, "511 m2 is for more than 1 principal building (prose)")],
}


def _summary(district):
    use, units, facts, _ = HEADLINE[district]
    return summarize(store.load(district), use, facts=facts, units=units)


def test_all_residential_districts_bundled():
    expected = set(HEADLINE) | {"FM-1"}
    assert expected <= set(store.available())
    assert len(expected) == 48


@pytest.mark.parametrize("district", sorted(HEADLINE))
def test_headline_limits(district):
    got = _summary(district)
    want = HEADLINE[district][3]
    assert {k: got[k] for k in want} == pytest.approx(want)


@pytest.mark.parametrize("district,field,pdf,why", [
    (d, *x) for d, xs in sorted(TRICKY_LIMITS.items()) for x in xs])
def test_tricky_limits_follow_the_pdf(district, field, pdf, why):
    got = _summary(district)[field]
    assert got == (pytest.approx(pdf) if isinstance(pdf, float) else pdf)


# ---------------------------------------------------------------- density rules
def L(d):
    return store.load(d)


def test_r3_fsr_tables():
    r3 = L("R3-1")
    f = lambda **k: r3.value(M.FSR, "apartment", "max", facts={"site_frontage": 20, **k}, tenure=k.pop("t", None) or "rental")
    assert f(site_area=920, site_depth=30) == 2.7          # 3.1.1.2(a)(i)
    assert f(site_area=613, site_depth=40) == 2.2          # (a)(iii) all other sites
    assert f(site_area=460, site_depth=40) == 1.6
    assert f(site_area=400, site_depth=40) is None          # below the 460 m2 minimum
    assert f(site_area=1000, site_depth=30, social_housing_share=1.0) == 3.0  # 3.1.1.2(b)
    strata = r3.value(M.FSR, "apartment", "max", tenure="strata_or_mixed",
                      facts=dict(site_area=613, site_depth=40, site_frontage=41, corner_site=True))
    assert strata == 1.75                                   # 3.1.1.3(b)
    assert L("R3-2").rental_only and not L("R3-1").rental_only
    assert r3.regulated_by("duplex") == "R1-1"              # overview: small forms follow R1-1


def test_rr2_and_rr3_multi_column_tables():
    a, b = L("RR-2A"), L("RR-2B")
    assert a.value(M.BUILDING_HEIGHT, "apartment", "max", condition=None) == 13.7
    assert b.value(M.BUILDING_HEIGHT, "apartment", "max", condition=None) == 19.8
    assert b.value(M.STOREYS, "apartment", "max") == 6
    assert a.value(M.SIDE_YARD, "apartment", "min") == 1.8 and b.value(M.SIDE_YARD, "apartment", "min") == 2.4
    assert b.value(M.FSR, "apartment", "max", facts=dict(site_area=1470, site_depth=40, site_frontage=30)) == 2.4
    assert a.rental_only and b.rental_only
    for d, fsr, relaxed in (("RR-3A", 2.4, 2.5), ("RR-3B", 3.4, 3.5), ("RR-3C", 3.4, 3.5)):
        s = L(d)
        assert s.value(M.FSR, "apartment", "max", facts={"non_dwelling_fsr": 0.35}) == fsr
        disc = [r for r in s.get(M.FSR, "apartment", "max", include_discretionary=True, include_conditional=True)
                if r.discretionary]
        assert [r.value for r in disc] == [relaxed] and disc[0].requires["corner_site"] is True


def test_r5_tenure_and_affordability_paths():
    r5 = L("R5-1")
    assert r5.value(M.FSR, "apartment", "max") is None
    assert r5.value(M.FSR, "apartment", "max", tenure="rental", facts={"below_market_rental_share": 0.2}) == 6.5
    assert r5.value(M.FSR, "apartment", "max", tenure="strata_or_mixed", facts={"social_housing_share": 0.2}) == 5.0
    assert r5.value(M.FSR, "mixed_use_residential_building", "max", tenure="rental",
                    facts={"social_housing_share": 1.0}) == 6.8
    assert L("R5-2").value(M.FSR, "apartment", "max", facts={"social_housing_share": 1.0}) == 5.5
    assert r5.value(M.SITE_FRONTAGE, "apartment", "max") == 60.7     # prose 3.1.2.7


def test_rm9_frontage_bonus_and_density_tiers():
    rm9 = L("RM-9")
    assert rm9.value(M.FSR, "apartment", "max") == 0.75
    assert L("RM-9B").value(M.FSR, "apartment", "max") == 0.70
    assert rm9.value(M.FSR, "apartment", "max", facts={"site_frontage": 15.2}) == 1.5
    assert rm9.value(M.FSR, "apartment", "max", facts={"site_frontage": 30}) == 2.0
    uph = lambda fsr: rm9.value(M.UNITS_PER_HECTARE, "apartment", "max", facts={"fsr": fsr})
    assert (uph(0.8), uph(1.0), uph(1.5)) == (100, 132, 140)


def test_unit_caps_by_frontage_and_tenure():
    rt10 = L("RT-10")
    caps = [rt10.value(M.DWELLING_UNITS, "multiple_dwelling", "max", facts={"site_frontage": w}) for w in (14, 16)]
    assert caps == [2, 3]
    assert rt10.value(M.UNITS_PER_HECTARE, "multiple_dwelling", "max", facts={"site_frontage": 20}) == 74
    for d in ("RT-7", "RT-9", "R1-1"):
        s = L(d)
        assert s.value(M.DWELLING_UNITS, "multiple_dwelling", "max", tenure="rental") == 8
        assert s.value(M.DWELLING_UNITS, "multiple_dwelling", "max", tenure="strata_or_mixed") == 6
    rm1 = L("RM-1")
    assert rm1.value(M.UNITS_PER_HECTARE, "townhouse", "max", facts={"fsr": 0.9}) == 86
    assert L("RM-8A").value(M.UNITS_PER_HECTARE, "townhouse", "max", facts={"fsr": 1.2}) == 145


def test_rr1_townhouse_bands():
    rr1 = L("RR-1")
    assert rr1.value(M.SITE_AREA, "townhouse", "min", units=4) == 303
    assert rr1.value(M.SITE_AREA, "townhouse", "min", units=3) == 303      # "4 dwelling units or triplex"
    assert rr1.value(M.SITE_AREA, "townhouse", "min", units=6) == 465
    assert rr1.value(M.SITE_AREA, "townhouse", "min", units=12, condition="4_storey") == 920
    assert rr1.value(M.FSR, "townhouse", "max", units=12, condition="4_storey") == 1.45
    assert rr1.value(M.SITE_FRONTAGE, "townhouse", "min", units=12, condition="3_storey") == 20.1


def test_site_width_and_depth_conditions():
    rt1 = L("RT-1")
    rows = rt1.get(M.SIDE_YARD, "duplex", "min", include_conditional=True)
    assert {(r.value, r.unit.value, tuple(r.requires.items())) for r in rows} == {
        (0.1, "fraction_of_site_width", (("site_frontage_lte", 15.0),)),
        (1.5, "m", (("site_frontage_gt", 15.0),))}
    rt5 = L("RT-5")
    assert rt5.value(M.REAR_YARD, "multiple_dwelling", "min", facts={"site_depth": 35}, condition=None) == 10.7
    deep = rt5.get(M.REAR_YARD, "multiple_dwelling", "min", facts={"site_depth": 40}, condition=None)
    assert [(r.value, r.unit.value) for r in deep] == [(0.3, "fraction_of_site_depth")]


def test_rm7_courtyard_only_in_rm7a():
    assert L("RM-7A").get(M.SITE_AREA, "townhouse", "min", condition=None)
    rows7 = [r for r in L("RM-7").regulations if r.clause.startswith("3.1.2")]
    assert rows7 == []  # the 3.1 courtyard table is headed RM-7A only


def test_unparsed_conditions_never_look_unconditional():
    """A rule with an 'if ...' we could not structure must not apply by default."""
    rt3 = L("RT-3")
    assert rt3.value(M.FSR, "multiple_dwelling", "max") == 0.60
    rows = rt3.get(M.FSR, "multiple_dwelling", "max", include_conditional=True)
    assert any(r.value == 1.0 and r.requires.get("unparsed_condition") for r in rows)


@pytest.mark.parametrize("district", sorted(store.available()))
def test_every_district_has_density_and_provenance(district):
    s = store.load(district)
    assert any(r.metric == M.FSR for r in s.regulations)
    for r in s.regulations:
        assert r.clause and r.page >= 1 and r.source_text and r.district == district


def test_overview_min_site_area_matches_section_3():
    """Section 1.2 overview vs the section 3 tables (independent parts of each PDF)."""
    prose_only = {("RT-10", "development_with_more_than_1_principal_building"),
                   ("RT-11", "duplex"), ("RT-11", "single_detached_house")}
    checked = 0
    for s in store.load_all():
        for e in s.overview:
            if not (e.min_site_area_m2 and e.uses and not e.regulated_by):
                continue
            if (s.district, e.uses[0]) in prose_only:
                continue
            vals = {r.value for u in e.uses for r in s.get(M.SITE_AREA, u, "min", include_conditional=True)}
            assert e.min_site_area_m2 in vals, (s.district, e.name)
            checked += 1
    assert checked > 150


PDF_DIR = os.environ.get("VANZONING_PDF_DIR")


@pytest.mark.skipif(not PDF_DIR, reason="set VANZONING_PDF_DIR to re-parse the PDFs")
def test_fresh_parse_matches_bundled():
    from vanzoning.parse.schedule import parse_schedule_pdf

    for pdf in sorted(Path(PDF_DIR).glob("*.pdf")):
        for s in parse_schedule_pdf(pdf):
            bundled = store.load(s.district)
            assert [r.model_dump() for r in s.regulations] == [r.model_dump() for r in bundled.regulations], s.district
