# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit polygon transformations and complete categorical-raster support."""
from dataclasses import dataclass
import math
import numpy as np
import pyproj
from pyproj import CRS, Transformer
from shapely import segmentize
from shapely.geometry import Polygon
from shapely.ops import transform, unary_union

from .preparation import polygon, allocate_households
from .gis_inputs import RasterSource,categorical_values
from .area import PlanarArea, WGS84Area


@dataclass(frozen=True)
class TransformSettings:
    max_source_segment: float
    target_tolerance: float
    maximum_accuracy_metres: float
    maximum_refinements: int = 8


def transform_polygon(geometry, *, source_crs, target_crs, settings):
    """Transform polygon edges with explicit source/target coordinate tolerances.

    Straight source-coordinate edges are densified before transformation.
    Refinement must meet a Hausdorff-distance check in target CRS units.
    This is a numerical refinement diagnostic, not a bound on source-map error.
    Unknown-accuracy or ballpark datum operations are not accepted.
    """
    polygon(geometry)
    if geometry.has_z:
        raise ValueError('Two-dimensional polygons required; Z values cannot be silently discarded.')
    if not isinstance(settings,TransformSettings) or any(not math.isfinite(x) or x <= 0 for x in
            (settings.max_source_segment,settings.target_tolerance)):
        raise ValueError('Positive source segment length and target tolerance required.')
    if not math.isfinite(settings.maximum_accuracy_metres) or settings.maximum_accuracy_metres < 0:
        raise ValueError('Nonnegative transformation accuracy limit required.')
    if type(settings.maximum_refinements) is not int or not 1 <= settings.maximum_refinements <= 16:
        raise ValueError('Transformation refinement count must be between 1 and 16.')
    source,target = CRS.from_user_input(source_crs),CRS.from_user_input(target_crs)
    if source.is_geographic and geometry.bounds[2]-geometry.bounds[0] >= 180:
        raise ValueError('Antimeridian/global-width polygons require explicit preprocessing.')
    converter = Transformer.from_crs(source,target,always_xy=True,allow_ballpark=False,only_best=True)
    def projected(length):
        dense = segmentize(geometry,length)
        result = transform(lambda x,y,z=None: converter.transform(x,y,errcheck=True),dense)
        polygon(result)
        if target.is_geographic and result.bounds[2]-result.bounds[0] >= 180:
            raise ValueError('Transformed polygon crosses the longitude wrap.')
        return result
    coarse = projected(settings.max_source_segment)
    for refinement in range(1,settings.maximum_refinements+1):
        length = settings.max_source_segment/(2**refinement)
        fine = projected(length)
        difference = coarse.hausdorff_distance(fine)
        if difference <= settings.target_tolerance:
            operation = converter.get_last_used_operation()
            accuracy = operation.accuracy
            if accuracy < 0 or accuracy > settings.maximum_accuracy_metres:
                raise ValueError('Transformation accuracy is unknown or exceeds the explicit limit.')
            return fine,dict(source_crs=source.to_wkt(),target_crs=target.to_wkt(),
                operation=operation.definition,accuracy_metres=accuracy,
                source_segment_length=length,target_tolerance=settings.target_tolerance,
                refinement_distance=difference,refinements=refinement,
                axis_order='x_y',pyproj_version=pyproj.__version__,proj_version=pyproj.proj_version_str)
        coarse = fine
    raise ValueError('Polygon transformation did not meet the configured refinement tolerance.')


@dataclass(frozen=True)
class CategoricalSupport:
    selected: tuple
    cells: tuple
    audit: dict


def categorical_support(*, spec, domain, expected_crs, rules, area_measure,transformation_settings=None,maximum_block_cells=65536):
    """Validate every class cell intersecting the full requested domain.

    Rules map integer class codes to explicit booleans. Missing/unmapped data
    fails even where a resource would otherwise be excluded. Categorical cells
    need not match the stock resolution: polygons intersect the stock grid
    later. Native class-cell IDs are retained separately for classification
    uncertainty; merging cells must not create independent observations.
    """
    polygon(domain)
    if spec.units != 'class_code':
        raise ValueError('Categorical raster units must be class_code.')
    if not isinstance(area_measure,(PlanarArea,WGS84Area)):
        raise ValueError('Explicit supported area measure required.')
    if not isinstance(rules,dict) or not rules or any(type(k) is not int or type(v) is not bool for k,v in rules.items()):
        raise ValueError('Explicit integer-class to boolean rules required.')
    with RasterSource(spec) as source:
        different=not source.crs.IsSame(expected_crs)
        operations=[]
        if different and transformation_settings is None:
            raise ValueError('Categorical CRS differs; explicit transformation settings required.')
        if transformation_settings is not None:
            if not different:raise ValueError('Categorical transformation settings supplied for matching CRSs.')
            if set(transformation_settings)!= {'domain_to_source','cells_to_stock'}:
                raise ValueError('Supply domain_to_source and cells_to_stock transformation settings.')
        if isinstance(area_measure,WGS84Area):
            from .gis_inputs import spatial_reference
            if not expected_crs.IsSame(spatial_reference('EPSG:4326')):
                raise ValueError('WGS84 area measurement requires WGS84 coordinates.')
        elif not expected_crs.IsProjected() or not math.isclose(expected_crs.GetLinearUnits(),1.0,abs_tol=1e-12):
            raise ValueError('Planar area measurement requires projected metre coordinates.')
        if source.scale != 1 or source.offset != 0:
            raise ValueError('Categorical raster must contain unscaled class codes.')
        native_domain=domain
        domain_operation=None
        if different:
            native_domain,domain_operation=transform_polygon(domain,source_crs=expected_crs.ExportToWkt(),
                target_crs=source.crs.ExportToWkt(),settings=transformation_settings['domain_to_source'])
            # Expand only the read window. Final support is clipped in stock CRS.
            native_domain=native_domain.buffer(transformation_settings['domain_to_source'].target_tolerance).intersection(source.footprint())
            if native_domain.is_empty:raise ValueError('Categorical raster does not cover the domain.')
        window = source.window_for(native_domain)
        col0,row0,width,height = window
        cells,selected,areas = [],[],{}
        for r,c,value in categorical_values(source,window,maximum_block_cells):
                t = source.transform
                def xy(rr,cc):
                    return (t[0]+cc*t[1]+rr*t[2],t[3]+cc*t[4]+rr*t[5])
                shape = Polygon([xy(r,c),xy(r,c+1),xy(r+1,c+1),xy(r+1,c)])
                identity = r*source.shape[1]+c
                operation=None
                if different:
                    shape,operation=transform_polygon(shape,source_crs=source.crs.ExportToWkt(),
                        target_crs=expected_crs.ExportToWkt(),settings=transformation_settings['cells_to_stock'])
                shape=shape.intersection(domain)
                if shape.area == 0:
                    continue
                if operation is not None:operations.append(dict(source_cell_id=identity,**operation))
                if not math.isfinite(value) or value != math.floor(value):
                    raise ValueError(f'Missing or noninteger class at source cell {identity}.')
                code = int(value)
                if code not in rules:
                    raise ValueError(f'No explicit rule for class {code} at source cell {identity}.')
                area = area_measure(shape)
                areas[code] = areas.get(code,0)+area
                cells.append(dict(source_cell_id=identity,class_code=code,selected=rules[code],
                                  geometry=shape,area_m2=area))
                if rules[code]:
                    selected.append(shape)
        if not math.isclose(sum(areas.values()),area_measure(domain),rel_tol=1e-9,abs_tol=1e-6):
            raise ValueError('Categorical coverage does not reconcile with the requested domain.')
        coverage=unary_union([cell['geometry'] for cell in cells])
        gap=domain.difference(coverage)
        gap_area=area_measure(gap) if not gap.is_empty and gap.area>0 else 0
        if gap_area>max(1e-6,area_measure(domain)*1e-9):
            raise ValueError('Transformed categorical cells leave gaps in domain coverage; refine transformation settings.')
        return CategoricalSupport(tuple(selected),tuple(cells),dict(source=source.metadata(),
            native_window=list(window),rules={str(k):v for k,v in rules.items()},
            area_by_class_m2={str(k):v for k,v in areas.items()},area_method=area_measure.method,
            support_crs_wkt=expected_crs.ExportToWkt(),domain_transformation=domain_operation,
            cell_transformations=operations,coverage_gap_m2=gap_area,maximum_raster_block_cells=maximum_block_cells))


def households_from_raster(*, spec, administrative_areas, boundary, expected_crs,
                           rules, area_measure,transformation_settings=None,maximum_block_cells=65536):
    """Read built-up support over entire administrative units before allocation."""
    units = list(administrative_areas)
    if not units:
        raise ValueError('Administrative units are required for household allocation.')
    domain = unary_union([polygon(item[2]) for item in units])
    support = categorical_support(spec=spec,domain=domain,expected_crs=expected_crs,
                                  rules=rules,area_measure=area_measure,transformation_settings=transformation_settings,
                                  maximum_block_cells=maximum_block_cells)
    rows = allocate_households(administrative_areas=units,built_up_support=support.selected,
                               boundary=boundary,area_measure=area_measure)
    return rows,support
