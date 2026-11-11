# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated local GIS inputs with native-grid windows and source fingerprints."""
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr
from shapely import from_wkb
from shapely.geometry import Polygon

from .preparation import polygon, prepare_native_grid
from .area import PlanarArea, WGS84Area


def fingerprint(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024*1024), b''):
            digest.update(block)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=digest.hexdigest())


def spatial_reference(wkt):
    if not wkt:
        raise ValueError('Missing coordinate reference system.')
    crs = osr.SpatialReference()
    if crs.SetFromUserInput(wkt) != 0 or crs.Validate() != 0:
        raise ValueError('Invalid coordinate reference system.')
    crs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return crs


def require_area_crs(crs, *, distortion_acknowledged):
    """Guard the planar preparation adapter; suitability remains explicit.

    Projected metre units alone do not establish area accuracy. The caller must
    acknowledge the selected projection's suitability for the assessment area.
    Geographic inputs are readable but cannot use this planar adapter.
    """
    if not crs.IsProjected() or not math.isclose(crs.GetLinearUnits(),1.0,rel_tol=0,abs_tol=1e-12):
        raise ValueError('Planar preparation requires a projected metre-based CRS; geographic grids need an area adapter.')
    if distortion_acknowledged is not True:
        raise ValueError('Area-projection suitability must be explicitly acknowledged.')


@dataclass(frozen=True)
class RasterSpec:
    path: str
    units: str
    source: str
    version: str
    date: str
    band: int = 1


class RasterSource:
    """A single band with explicit physical units and GDAL mask semantics.

    Nodata/masks are applied in encoded units before band scale and offset.
    The uncertainty reader does not interpret SD versus SE or interval bounds.
    That scientific interpretation is mandatory in the calling input contract.
    """
    def __init__(self, spec):
        if not isinstance(spec,RasterSpec) or not all((spec.units,spec.source,spec.version,spec.date)):
            raise ValueError('Raster units, source, version and date are required.')
        self.spec = spec
        self.path = str(Path(spec.path).resolve(strict=True))
        self.dataset = gdal.Open(self.path,gdal.GA_ReadOnly)
        if self.dataset is None:
            raise ValueError('Cannot open raster input.')
        if not isinstance(spec.band,int) or not 1 <= spec.band <= self.dataset.RasterCount:
            raise ValueError('Requested raster band is unavailable.')
        self.band = self.dataset.GetRasterBand(spec.band)
        if gdal.DataTypeIsComplex(self.band.DataType):
            raise ValueError('Complex raster values are unsupported.')
        self.crs = spatial_reference(self.dataset.GetProjectionRef())
        self.transform = self.dataset.GetGeoTransform(can_return_null=True)
        if self.transform is None or not np.all(np.isfinite(self.transform)) or gdal.InvGeoTransform(self.transform) is None:
            raise ValueError('Raster requires a valid nonsingular affine geotransform.')
        self.shape = (self.dataset.RasterYSize,self.dataset.RasterXSize)
        self.scale = self.band.GetScale()
        self.offset = self.band.GetOffset()
        self.scale = 1.0 if self.scale is None else self.scale
        self.offset = 0.0 if self.offset is None else self.offset
        if not math.isfinite(self.scale) or self.scale <= 0 or not math.isfinite(self.offset):
            raise ValueError('Invalid raster encoding scale/offset.')
        encoded_units = self.band.GetUnitType()
        if encoded_units and encoded_units != spec.units:
            raise ValueError('Declared units conflict with raster band metadata.')

    def close(self):
        self.band = None
        self.dataset = None

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()

    def footprint(self):
        h,w = self.shape
        return Polygon([gdal.ApplyGeoTransform(self.transform,c,r) for c,r in [(0,0),(w,0),(w,h),(0,h)]])

    def window_for(self,boundary):
        polygon(boundary)
        tolerance = max(1e-12,boundary.area*1e-10)
        if boundary.difference(self.footprint()).area > tolerance:
            raise ValueError('Raster does not cover the full assessment boundary.')
        xmin,ymin,xmax,ymax = boundary.bounds
        inv = gdal.InvGeoTransform(self.transform)
        pixels = np.array([gdal.ApplyGeoTransform(inv,x,y) for x,y in
                           [(xmin,ymin),(xmin,ymax),(xmax,ymin),(xmax,ymax)]])
        h,w = self.shape
        c0,r0 = np.maximum(np.floor(pixels.min(axis=0)),0).astype(int)
        c1,r1 = np.minimum(np.ceil(pixels.max(axis=0)),[w,h]).astype(int)
        if c1 <= c0 or r1 <= r0:
            raise ValueError('Assessment has no raster-cell area.')
        return (int(c0),int(r0),int(c1-c0),int(r1-r0))

    def read(self,window):
        c,r,w,h = window
        if any(not isinstance(x,int) for x in window) or min(c,r) < 0 or min(w,h) <= 0 or c+w > self.shape[1] or r+h > self.shape[0]:
            raise ValueError('Invalid native raster window.')
        raw = self.band.ReadAsArray(c,r,w,h)
        mask = self.band.GetMaskBand().ReadAsArray(c,r,w,h)
        if raw is None or mask is None:
            raise ValueError('Raster window read failed.')
        values = np.asarray(raw,dtype=float)
        missing = (mask == 0) | ~np.isfinite(values)
        nodata = self.band.GetNoDataValue()
        if nodata is not None:
            missing |= np.isnan(values) if math.isnan(nodata) else values == nodata
        values = values*self.scale+self.offset
        values[missing] = np.nan
        return values

    def metadata(self):
        files = self.dataset.GetFileList() or [self.path]
        return dict(source=self.spec.source,version=self.spec.version,date=self.spec.date,
                    units=self.spec.units,band=self.spec.band,crs_wkt=self.crs.ExportToWkt(),
                    shape=list(self.shape),transform=list(self.transform),scale=self.scale,
                    offset=self.offset,nodata=repr(self.band.GetNoDataValue()),
                    mask_flags=self.band.GetMaskFlags(),files=[fingerprint(p) for p in sorted(set(files))])


def require_aligned(first,second):
    if first.shape != second.shape or first.transform != second.transform or not first.crs.IsSame(second.crs):
        raise ValueError('Stock and uncertainty must share the same native grid and CRS; no implicit resampling.')


def read_polygons(path, *, expected_crs, layer_name=None, required_fields=(), transformation_settings=None):
    """Read valid polygons; CRS changes require explicit transformation settings."""
    source = ogr.Open(str(Path(path).resolve(strict=True)),0)
    if source is None:
        raise ValueError('Cannot open vector input.')
    if layer_name is None and source.GetLayerCount() != 1:
        raise ValueError('Select an explicit layer in a multi-layer vector input.')
    layer = source.GetLayerByName(layer_name) if layer_name else source.GetLayer(0)
    if layer is None:
        raise ValueError('Requested vector layer is unavailable.')
    crs = layer.GetSpatialRef()
    if crs is None:
        raise ValueError('Vector input has no CRS.')
    crs = spatial_reference(crs.ExportToWkt())
    needs_transform = not crs.IsSame(expected_crs)
    if needs_transform and transformation_settings is None:
        raise ValueError('Vector and native grid CRS differ; explicit transformation is required.')
    definition = layer.GetLayerDefn()
    for name in required_fields:
        if definition.GetFieldIndex(name) < 0:
            raise ValueError(f'Missing required vector field: {name}.')
    records = []
    for feature in layer:
        geometry = feature.GetGeometryRef()
        if geometry is None:
            raise ValueError(f'Missing geometry for feature {feature.GetFID()}.')
        shape = polygon(from_wkb(bytes(geometry.ExportToWkb())))
        transformation = None
        if needs_transform:
            from .spatial_inputs import transform_polygon
            shape,transformation = transform_polygon(shape,source_crs=crs.ExportToWkt(),
                        target_crs=expected_crs.ExportToWkt(),settings=transformation_settings)
        fields = {name:feature.GetField(name) for name in required_fields}
        if any(value is None for value in fields.values()):
            raise ValueError(f'Missing required field value for feature {feature.GetFID()}.')
        records.append(dict(feature_id=feature.GetFID(),geometry=shape,fields=fields,
                            transformation=transformation))
    if not records:
        raise ValueError('Vector input contains no polygon features.')
    return records


def raster_windows(window,maximum_cells=65536):
    """Bounded native windows in global row-major cell order."""
    if type(maximum_cells) is not int or maximum_cells<=0:
        raise ValueError('Positive integer raster block cell limit required.')
    c,r,w,h=window
    if w<=maximum_cells:
        rows=max(1,maximum_cells//w)
        for start in range(0,h,rows):yield (c,r+start,w,min(rows,h-start))
    else:
        for row in range(r,r+h):
            for start in range(0,w,maximum_cells):yield (c+start,row,min(maximum_cells,w-start),1)


def categorical_values(source,window,maximum_cells):
    for block in raster_windows(window,maximum_cells):
        c,r,w,h=block
        values=source.read(block)
        for row in range(h):
            for col in range(w):yield r+row,c+col,values[row,col]


def prepare_raster_pair(*, stock_spec, uncertainty_spec, stock_mode, boundary,
                        zones, eligibility, exclusions, distortion_acknowledged,
                        uncertainty_interpretation,maximum_block_cells=65536):
    """Read only the boundary window, preserving global source-cell numbering.

    Input uncertainty must already be expressed as SD (AGB) or the explicitly
    chosen pre-truncation normal scale (canopy). This adapter never converts
    confidence intervals or standard errors without a source-specific method.
    """
    expected = 'standard_deviation' if stock_mode == 'agb' else 'pre_truncation_normal_scale'
    if stock_mode not in ('agb','canopy') or uncertainty_interpretation != expected:
        raise ValueError('Explicit supported stock mode and uncertainty interpretation required.')
    allowed_units = ('t_dry_matter/ha',) if stock_mode == 'agb' else ('fraction','percent')
    if stock_spec.units not in allowed_units or uncertainty_spec.units != stock_spec.units:
        raise ValueError('Stock/uncertainty units must be explicit, supported and consistent.')
    with RasterSource(stock_spec) as stock, RasterSource(uncertainty_spec) as uncertainty:
        require_aligned(stock,uncertainty)
        if stock.crs.IsGeographic():
            if not stock.crs.IsSame(spatial_reference('EPSG:4326')):
                raise ValueError('Geographic area measurement currently supports WGS84 longitude/latitude only.')
            measure = WGS84Area()
        else:
            require_area_crs(stock.crs,distortion_acknowledged=distortion_acknowledged)
            measure = PlanarArea()
        window = stock.window_for(boundary)
        factor = .01 if stock_spec.units == 'percent' else 1.0
        c,r,width,height = window
        def cells():
            for block in raster_windows(window,maximum_block_cells):
                bc,br,bw,bh=block
                values,scales=stock.read(block)*factor,uncertainty.read(block)*factor
                if stock_mode=='canopy' and np.any(np.isfinite(values)&((values<0)|(values>1))):
                    raise ValueError('Tree cover must be within the declared fraction/percent range.')
                for row in range(bh):
                    for col in range(bw):yield br+row-r,bc+col-c,values[row,col],scales[row,col]
        x,y = gdal.ApplyGeoTransform(stock.transform,c,r)
        transform = (x,*stock.transform[1:3],y,*stock.transform[4:6])
        prepared = prepare_native_grid(stock=None,uncertainty=None,cell_values=cells(),grid_shape=(height,width),transform=transform,
                    boundary=boundary,zones=zones,eligibility=eligibility,exclusions=exclusions,
                    area_crs_confirmed=True,source_shape=stock.shape,source_origin=(r,c),area_measure=measure)
        prepared.audit.update(stock_source=stock.metadata(),uncertainty_source=uncertainty.metadata(),
                    native_window=list(window),stock_mode=stock_mode,
                    uncertainty_interpretation=uncertainty_interpretation,
                    physical_unit_factor=factor,area_distortion_acknowledged=(distortion_acknowledged is True),
                    area_measurement=measure.method,maximum_raster_block_cells=maximum_block_cells)
        return prepared
