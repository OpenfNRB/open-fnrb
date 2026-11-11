# SPDX-License-Identifier: GPL-3.0-or-later
"""Dissolved collection buffers from explicitly defined travel assumptions."""
from dataclasses import dataclass
import math
import numpy as np
from pyproj import CRS, Geod
from shapely.geometry import Polygon
from shapely.ops import unary_union
from .area import PlanarArea, WGS84Area
from .preparation import polygon, travel_radius_metres


@dataclass(frozen=True)
class TravelBoundary:
    geometry: object
    buffers: tuple
    audit: dict


def collection_boundary(*, points, crs, round_trip_hours, travelling_share,
                        speed_kmh, edge_tolerance_metres, distortion_acknowledged=False):
    """Points are unique (ID, Shapely Point) pairs in the declared CRS.

    WGS84 circles use ellipsoidal distance; their straight lon/lat segments are
    refined until sampled edge midpoints meet the radial tolerance. Projected
    circles require acknowledged metre-based distance/area suitability.
    Buffers model straight-line access, not terrain, permissions or routes.
    """
    radius = travel_radius_metres(round_trip_hours=round_trip_hours,
                 travelling_share=travelling_share,speed_kmh=speed_kmh)
    if not math.isfinite(edge_tolerance_metres) or not 0 < edge_tolerance_metres < radius:
        raise ValueError('Edge tolerance must be positive and smaller than the travel radius.')
    crs = CRS.from_user_input(crs)
    geographic = crs.equals(CRS.from_epsg(4326),ignore_axis_order=True)
    if not geographic and (not crs.is_projected or any(a.unit_conversion_factor != 1 for a in crs.axis_info[:2]) or distortion_acknowledged is not True):
        raise ValueError('Use WGS84 or an explicitly acknowledged projected metre-based CRS.')
    points = list(points)
    if not points:
        raise ValueError('At least one household/stove point is required.')
    geod = Geod(ellps='WGS84')
    measure = WGS84Area() if geographic else PlanarArea()
    seen,buffers,records = set(),[],[]
    segments = max(16,4*math.ceil(math.pi/(4*math.acos(1-edge_tolerance_metres/radius))))
    for identity,point in points:
        if not isinstance(identity,str) or not identity.strip() or identity in seen:
            raise ValueError('Unique nonempty point IDs required.')
        seen.add(identity)
        if point.geom_type != 'Point' or point.is_empty or point.has_z or not all(math.isfinite(v) for v in (point.x,point.y)):
            raise ValueError('Valid two-dimensional points required.')
        n = segments
        if geographic:
            if not -180 <= point.x <= 180 or not -90 < point.y < 90:
                raise ValueError('Invalid WGS84 point coordinates.')
            while n <= 131072:
                bearings = np.linspace(0,360,n,endpoint=False)
                lon,lat,_ = geod.fwd(np.full(n,point.x),np.full(n,point.y),bearings,np.full(n,radius))
                if np.ptp(lon) >= 180:
                    raise ValueError('Travel buffer crosses the longitude wrap; explicit preprocessing required.')
                midlon = (lon+np.roll(lon,-1))/2
                midlat = (lat+np.roll(lat,-1))/2
                _,_,distance = geod.inv(np.full(n,point.x),np.full(n,point.y),midlon,midlat)
                error = float(np.max(np.abs(distance-radius)))
                if error <= edge_tolerance_metres:
                    shape = polygon(Polygon(zip(lon,lat)))
                    break
                n *= 2
            else:
                raise ValueError('Travel buffer refinement exceeds supported vertex limit.')
        else:
            if n > 131072:
                raise ValueError('Travel buffer tolerance requires too many vertices.')
            shape = point.buffer(radius,quad_segs=n//4)
            error = radius*(1-math.cos(math.pi/n))
        buffers.append(shape)
        records.append(dict(point_id=identity,radius_metres=radius,vertices=n,
                            sampled_edge_error_metres=error,area_m2=measure(shape)))
    dissolved = polygon(unary_union(buffers))
    return TravelBoundary(dissolved,tuple(buffers),dict(crs_wkt=crs.to_wkt(),
        round_trip_hours=round_trip_hours,travelling_share=travelling_share,speed_kmh=speed_kmh,
        radius_metres=radius,edge_tolerance_metres=edge_tolerance_metres,
        distance_method='wgs84_ellipsoid' if geographic else 'projected_metres',
        area_method=measure.method,points=records,union_area_m2=measure(dissolved),
        overlap_area_m2=sum(r['area_m2'] for r in records)-measure(dissolved)))
