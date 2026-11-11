# SPDX-License-Identifier: GPL-3.0-or-later
"""Square-metre areas for planar and WGS84 native-grid polygon support."""
import math
import numpy as np


class PlanarArea:
    method = 'planar_projected_metres'

    def __call__(self, geometry):
        return geometry.area


class WGS84Area:
    """Ellipsoid surface area bounded by straight longitude/latitude segments.

    Geographic raster edges follow their coordinate grid, not great circles.
    Integrate the ellipsoid area primitive around each polygon ring using
    16-point Gauss-Legendre quadrature, subdividing latitude spans above five
    degrees. Shared straight edges cancel when polygons are partitioned.
    Supports regional polygons within [-180,180] longitude; antimeridian
    crossings and spans of 180 degrees or more require explicit preprocessing.
    No raster values, resolution or source identities are transformed.
    """
    method = 'wgs84_ellipsoid_linear_lonlat_edges_gauss16'
    _a = 6378137.0
    _f = 1 / 298.257223563
    _e2 = _f*(2-_f)
    _e = math.sqrt(_e2)
    _nodes, _weights = np.polynomial.legendre.leggauss(16)

    def _q(self, latitude):
        s = np.sin(latitude)
        return (1-self._e2)*(s/(1-self._e2*s*s)+np.arctanh(self._e*s)/self._e)

    def _ring(self, ring):
        coords = np.asarray(ring.coords,float)[:,:2]
        if not np.all(np.isfinite(coords)) or np.any(np.abs(coords[:,0])>180) or np.any(np.abs(coords[:,1])>90):
            raise ValueError('Invalid WGS84 longitude/latitude coordinates.')
        if np.ptp(coords[:,0]) >= 180:
            raise ValueError('Antimeridian or global-width polygons require explicit preprocessing.')
        radians = np.deg2rad(coords)
        reference = self._q(np.mean(radians[:,1]))
        pieces = []
        for start,end in zip(radians[:-1],radians[1:]):
            dlon,dlat = end-start
            count = max(1,math.ceil(abs(dlat)/math.radians(5)))
            for part in range(count):
                u = (part+(self._nodes+1)/2)/count
                q = self._q(start[1]+u*dlat)-reference
                pieces.append(float(dlon*np.dot(self._weights,q)/(2*count)))
        return abs(self._a*self._a/2*math.fsum(pieces))

    def __call__(self, geometry):
        if geometry.is_empty:
            return 0.0
        if geometry.geom_type == 'Polygon':
            area = self._ring(geometry.exterior)-math.fsum(self._ring(r) for r in geometry.interiors)
            if area < -1e-6:
                raise ValueError('Polygon holes exceed ellipsoidal exterior area.')
            return max(0.0,area)
        if geometry.geom_type in ('MultiPolygon','GeometryCollection'):
            return math.fsum(self(g) for g in geometry.geoms)
        if geometry.geom_type in ('Point','MultiPoint','LineString','MultiLineString','LinearRing'):
            return 0.0
        raise ValueError('Unsupported geometry for area measurement.')
