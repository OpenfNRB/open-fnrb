# SPDX-License-Identifier: GPL-3.0-or-later
"""Traceable household/stove point intake for travel-based boundaries."""
import math
from pathlib import Path
from osgeo import gdal,ogr
from pyproj import Transformer
from shapely import from_wkb
from shapely.geometry import Point
from .gis_inputs import spatial_reference,fingerprint


def read_points(path,*,expected_crs,id_field,layer_name=None,maximum_accuracy_metres=None):
    """Read unique text IDs and two-dimensional points; never infer an ID.

    CRS changes require an explicit accepted operation accuracy. Point positions
    are transformed with x/y axis order and no ballpark operation. Original
    coordinates and the transformation remain in the returned audit record.
    """
    path=Path(path).resolve(strict=True)
    if not isinstance(id_field,str) or not id_field:
        raise ValueError('Explicit point identifier field required.')
    source=ogr.Open(str(path),0)
    if source is None:
        raise ValueError('Cannot open point input.')
    if layer_name is None and source.GetLayerCount()!=1:
        raise ValueError('Select a layer explicitly in a multi-layer point input.')
    layer=source.GetLayerByName(layer_name) if layer_name else source.GetLayer(0)
    if layer is None:
        raise ValueError('Requested point layer is unavailable.')
    reference=layer.GetSpatialRef()
    if reference is None:
        raise ValueError('Point input has no coordinate reference system.')
    crs=spatial_reference(reference.ExportToWkt())
    index=layer.GetLayerDefn().GetFieldIndex(id_field)
    if index<0 or layer.GetLayerDefn().GetFieldDefn(index).GetType()!=ogr.OFTString:
        raise ValueError('Point identifier field must exist and contain text.')
    converter=None
    if maximum_accuracy_metres is not None and (isinstance(maximum_accuracy_metres,bool) or
            not isinstance(maximum_accuracy_metres,(int,float)) or not math.isfinite(maximum_accuracy_metres) or maximum_accuracy_metres<0):
        raise ValueError('Point transformation accuracy must be finite and nonnegative.')
    if not crs.IsSame(expected_crs):
        if maximum_accuracy_metres is None:
            raise ValueError('Point CRS differs; explicit transformation accuracy is required.')
        converter=Transformer.from_crs(crs.ExportToWkt(),expected_crs.ExportToWkt(),always_xy=True,allow_ballpark=False,only_best=True)
    records,points,seen=[],[],set()
    for feature in layer:
        identity=feature.GetField(id_field)
        if not isinstance(identity,str) or not identity.strip() or identity!=identity.strip() or identity in seen:
            raise ValueError('Point IDs must be unique nonempty text without surrounding spaces.')
        seen.add(identity)
        geometry=feature.GetGeometryRef()
        if geometry is None or geometry.Is3D() or geometry.IsMeasured():
            raise ValueError('Point geometry must be present and two-dimensional.')
        point=from_wkb(bytes(geometry.ExportToWkb()))
        if point.geom_type!='Point' or point.is_empty or not all(math.isfinite(v) for v in (point.x,point.y)):
            raise ValueError('Each record must contain one valid two-dimensional point.')
        original=(point.x,point.y)
        operation=None
        if converter:
            x,y=converter.transform(point.x,point.y,errcheck=True)
            if not all(math.isfinite(v) for v in (x,y)):
                raise ValueError('Point transformation produced nonfinite coordinates.')
            point=Point(x,y)
            used=converter.get_last_used_operation()
            if used.accuracy<0 or used.accuracy>maximum_accuracy_metres:
                raise ValueError('Point transformation accuracy is unknown or exceeds the accepted limit.')
            operation=dict(definition=used.definition,accuracy_metres=used.accuracy)
        points.append((identity,point))
        records.append(dict(point_id=identity,source_feature_id=feature.GetFID(),
                            source_x=original[0],source_y=original[1],x=point.x,y=point.y,operation=operation))
    if not records:
        raise ValueError('Point layer contains no records.')
    dataset=gdal.OpenEx(str(path),gdal.OF_VECTOR|gdal.OF_READONLY)
    files=dataset.GetFileList() if dataset else None
    dataset=None
    if not files:
        raise ValueError('Cannot enumerate point-input dependencies for audit.')
    return points,dict(files=[fingerprint(f) for f in sorted(set(files))],layer=layer.GetName(),
                       id_field=id_field,source_crs_wkt=crs.ExportToWkt(),target_crs_wkt=expected_crs.ExportToWkt(),records=records)
