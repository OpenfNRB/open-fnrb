# SPDX-License-Identifier: GPL-3.0-or-later
"""Native-grid polygon intersections with explicit square-metre area measurement."""
from dataclasses import dataclass
import math
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union
from .area import PlanarArea, WGS84Area


def polygon(value):
    if value.is_empty or not value.is_valid or value.geom_type not in ('Polygon', 'MultiPolygon'):
        raise ValueError('Nonempty valid polygon geometry required; no automatic repair.')
    return value


def union_boundaries(boundaries):
    values = [polygon(g) for g in boundaries]
    if not values:
        raise ValueError('At least one boundary required.')
    return unary_union(values)


def travel_radius_metres(*, round_trip_hours, travelling_share, speed_kmh):
    values = (round_trip_hours, travelling_share, speed_kmh)
    if not all(math.isfinite(x) for x in values) or round_trip_hours <= 0 or speed_kmh <= 0 or not 0 < travelling_share <= 1:
        raise ValueError('Positive trip duration/speed and travelling share in (0,1] required.')
    return round_trip_hours * travelling_share * speed_kmh * 1000 / 2


@dataclass(frozen=True)
class Support:
    area_ha: np.ndarray
    source_cell_ids: np.ndarray
    zone_index: np.ndarray
    mapped_stock: np.ndarray
    stock_scale: np.ndarray
    geometries: tuple
    audit: dict


def prepare_native_grid(*, stock, uncertainty, transform, boundary, zones,
                        eligibility, exclusions, area_crs_confirmed,
                        source_shape=None, source_origin=(0,0), area_measure=None,
                        cell_values=None,grid_shape=None):
    """Split source cells exactly at boundary, zone and eligibility polygons.

    ``transform`` is the six-element GDAL affine transform. IDs are full-raster
    row * width + column, never local clipped-window positions. Zones are
    (parameter index, polygon) pairs. Eligibility is an explicit polygon union;
    an explicit empty list means no eligible resource. Exclusions are mandatory
    but may be empty. The explicit area measure returns square metres.
    Missing data is checked throughout the boundary, including excluded land.
    """
    if area_crs_confirmed is not True:
        raise ValueError('The coordinate system and area measurement must be confirmed.')
    measure = PlanarArea() if area_measure is None else area_measure
    if not isinstance(measure,(PlanarArea,WGS84Area)):
        raise ValueError('Supported explicit area measurement required.')
    if cell_values is None:
        stock, uncertainty = np.asarray(stock, float), np.asarray(uncertainty, float)
        if stock.ndim != 2 or stock.shape != uncertainty.shape or 0 in stock.shape:
            raise ValueError('Stock and uncertainty must be matching nonempty native grids.')
        grid_shape=stock.shape
        cell_values=((r,c,stock[r,c],uncertainty[r,c]) for r in range(grid_shape[0]) for c in range(grid_shape[1]))
    elif stock is not None or uncertainty is not None or grid_shape is None or len(grid_shape)!=2 or any(type(v) is not int or v<=0 for v in grid_shape):
        raise ValueError('Streamed cells require positive grid dimensions and no in-memory arrays.')
    t = np.asarray(transform, float)
    if t.shape != (6,) or not np.all(np.isfinite(t)) or abs(t[1]*t[5]-t[2]*t[4]) == 0:
        raise ValueError('Valid nonsingular GDAL affine transform required.')
    boundary = polygon(boundary)
    zones = list(zones)
    for i, (code, geometry) in enumerate(zones):
        if not isinstance(code, (int, np.integer)) or code < 0:
            raise ValueError('Nonnegative integer parameter indices required.')
        polygon(geometry)
        for _, previous in zones[:i]:
            if measure(geometry.intersection(previous)) > 1e-8:
                raise ValueError('Ecological zones overlap; ambiguous parameter assignment.')
    def cell(row, col):
        def xy(r, c):
            return (t[0]+c*t[1]+r*t[2], t[3]+c*t[4]+r*t[5])
        return Polygon([xy(row,col),xy(row,col+1),xy(row+1,col+1),xy(row+1,col)])
    height, width = grid_shape
    source_shape = grid_shape if source_shape is None else tuple(source_shape)
    if len(source_shape) != 2 or len(source_origin) != 2 or any(
            not isinstance(x,(int,np.integer)) for x in (*source_shape,*source_origin)):
        raise ValueError('Integer source dimensions and window origin required.')
    row_origin,col_origin = source_origin
    if min(source_shape) <= 0 or min(source_origin) < 0 or row_origin+height > source_shape[0] or col_origin+width > source_shape[1]:
        raise ValueError('Prepared window lies outside the original source grid.')
    def source_id(row,col):
        return (row+row_origin)*source_shape[1]+col+col_origin
    def xy(r,c):
        return (t[0]+c*t[1]+r*t[2],t[3]+c*t[4]+r*t[5])
    footprint = Polygon([xy(0,0),xy(0,width),xy(height,width),xy(height,0)])
    tolerance = max(1e-6, measure(boundary)*1e-9)
    if measure(boundary.difference(footprint)) > tolerance:
        raise ValueError('Starting-stock grid does not cover the assessment boundary.')
    eligible = unary_union([polygon(g) for g in eligibility]).intersection(boundary)
    excluded = unary_union([polygon(g) for g in exclusions])
    eligible = eligible.difference(excluded)
    zone_union = unary_union([g for _,g in zones])
    if measure(eligible.difference(zone_union)) > tolerance:
        raise ValueError('Ecological-zone coverage is incomplete over eligible resource.')
    records = []
    seen=0
    for row,col,b,s in cell_values:
            if row*width+col!=seen or not 0<=col<width or not 0<=row<height:
                raise ValueError('Streamed cells must cover the native window exactly once in row-major order.')
            seen+=1
            shape = cell(row,col).intersection(boundary)
            if shape.area == 0:
                continue
            if not np.isfinite(b) or not np.isfinite(s) or b < 0 or s < 0:
                raise ValueError(f'Missing or invalid stock/uncertainty at source cell {source_id(row,col)}.')
            resource = shape.intersection(eligible)
            if resource.area == 0:
                continue
            for code, zone in zones:
                part = resource.intersection(zone)
                if part.area > 0:
                    records.append((measure(part)/10000, source_id(row,col), code, b, s, part))
    if seen!=height*width:raise ValueError('Streamed native window is incomplete.')
    arrays = [np.array([r[k] for r in records], dtype=(np.int64 if k in (1,2) else float)) for k in range(5)]
    if not math.isclose(float(arrays[0].sum())*10000, measure(eligible), rel_tol=1e-9, abs_tol=tolerance):
        raise ValueError('Prepared areas do not reconcile with eligible polygon area.')
    for a in arrays:
        a.flags.writeable = False
    return Support(*arrays, tuple(r[5] for r in records), dict(
        boundary_area_ha=measure(boundary)/10000, eligible_area_ha=measure(eligible)/10000,
        noneligible_area_ha=(measure(boundary)-measure(eligible))/10000,
        source_cells=len(set(arrays[1].tolist())), records=len(records),
        area_method=measure.method, transform=t.tolist(), shape=list(grid_shape),
        source_shape=list(source_shape),source_origin=list(source_origin)))


def estimate_annual_harvest(*, households, woody_biomass_use_tonnes_per_household_year):
    if not all(math.isfinite(x) and x >= 0 for x in (households, woody_biomass_use_tonnes_per_household_year)):
        raise ValueError('Nonnegative finite household count and dry-tonne household woody biomass use required.')
    return households * woody_biomass_use_tonnes_per_household_year


def allocate_households(*, administrative_areas, built_up_support, boundary, area_measure=None):
    """Allocate (ID, count, polygon) totals using full-unit built-up denominators.

    Built-up support is a complete, validated polygon representation, supplied
    independently from resource eligibility. Administrative units cannot overlap.
    """
    boundary = polygon(boundary)
    measure = PlanarArea() if area_measure is None else area_measure
    if not isinstance(measure,(PlanarArea,WGS84Area)):
        raise ValueError("Supported explicit area measurement required.")
    support = unary_union([polygon(g) for g in built_up_support])
    units = list(administrative_areas)
    ids, results = set(), []
    for i, (identity, count, geometry) in enumerate(units):
        polygon(geometry)
        if not identity or identity in ids or not math.isfinite(count) or count < 0:
            raise ValueError('Unique administrative IDs and valid household totals required.')
        ids.add(identity)
        for _, _, previous in units[:i]:
            if measure(geometry.intersection(previous)) > 1e-8:
                raise ValueError('Administrative overlaps would duplicate household allocation.')
        full = support.intersection(geometry)
        if measure(full) <= 0:
            raise ValueError(f'Zero built-up denominator for {identity}; explicit resolution required.')
        inside = measure(full.intersection(boundary))
        results.append(dict(administrative_id=identity, households_total=count,
                            full_support_m2=measure(full), inside_support_m2=inside,
                            households_allocated=count*inside/measure(full)))
    return results
