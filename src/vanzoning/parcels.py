"""Parcel geometry helpers: measure frontage/depth from parcel polygons.

Ported from the earlier vancouver_r_zoning `preprocess_properties.py`
(minimum rotated rectangle oriented by street axis). Needs the `geo` extra:
`pip install "vanzoning[geo]"` (shapely, pyproj).

Use with City of Vancouver Open Data `property-parcel-polygons.geojson`.
Outputs feed `vanzoning.envelope.Site(area_m2, frontage_m, depth_m)`.
"""
import re
from collections import defaultdict

import numpy as np
from pyproj import Transformer
from shapely.affinity import translate

PROJECT = Transformer.from_crs("EPSG:4326", "EPSG:32610", always_xy=True).transform


def key(value):
    return '' if value is None else str(value).strip()


def dimensions(geom, street, street_axis=None):
    """Orient measured rectangle by numbered avenues or observed street axes.

    This identifies the front/back axis, not the front side or legal frontage.
    Never rescale a rectangle to force area agreement.
    """
    flags = []
    if geom.is_empty or not geom.is_valid or geom.geom_type != 'Polygon':
        return None, None, ['invalid_or_multipart_geometry']
    origin = geom.centroid
    with np.errstate(invalid="ignore", divide="ignore"):
        rect = translate(geom, xoff=-origin.x, yoff=-origin.y).minimum_rotated_rectangle
    if rect.is_empty or rect.geom_type != "Polygon" or not np.isfinite(rect.area):
        return None, None, ["invalid_or_multipart_geometry"]
    error = (rect.area - geom.area) / geom.area
    coords = list(rect.exterior.coords)
    edges = [(coords[i+1][0]-coords[i][0], coords[i+1][1]-coords[i][1]) for i in range(2)]
    lengths = [(x*x+y*y)**.5 for x,y in edges]
    # Numbered avenues provide a grid fallback; other names need observed axes.
    s = key(street).upper()
    east_west = bool(re.fullmatch(r'[EW] \d+(?:ST|ND|RD|TH) AV', s))
    if street_axis is None and east_west:
        street_axis = (1, 0)
    if street_axis is None:
        return None, None, ['unresolved_street_orientation']
    scores = [abs(x*street_axis[0]+y*street_axis[1])/length for (x,y),length in zip(edges,lengths)]
    i = max(range(2), key=lambda j: scores[j])
    if scores[i] < .98:
        return None, None, ['street_axis_not_grid_aligned']
    if error > .02:
        flags.append('irregular_geometry')
    flags.extend(['address_axis_estimate', 'front_side_unknown', 'corner_status_unknown'])
    return lengths[i], lengths[1-i], flags


def infer_street_axes(parcels):
    """Infer street axes from many distinct addressed parcel centres.

    Require >=20 unique centres, >=200 m span, and strong linearity.
    This estimates an axis only; no corner or front-side inference.
    """
    centres = defaultdict(set)
    for f in parcels:
        p = f['properties']
        point = p.get('geo_point_2d') or {}
        if point.get('lon') is not None and point.get('lat') is not None and p.get('streetname'):
            centres[key(p['streetname'])].add(PROJECT(point['lon'], point['lat']))
    axes = {}
    for street, points in centres.items():
        if len(points) < 20:
            continue
        coords = np.array(list(points))
        values, vectors = np.linalg.eigh(np.cov(coords.T))
        direction = vectors[:, -1]
        span = float(np.ptp(coords @ direction))
        ratio = float(values[-1] / max(values[0], .001))
        if ratio >= 25 and span >= 200:
            axes[street] = dict(axis=direction.tolist(), centre_count=len(points), span_m=span, variance_ratio=ratio)
    return axes
