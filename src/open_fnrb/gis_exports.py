# SPDX-License-Identifier: GPL-3.0-or-later
"""Native-grid audit rasters and polygon shapefiles with explicit support metadata."""
import json
from pathlib import Path
import numpy as np
from osgeo import gdal,ogr
from shapely.geometry import Polygon
from shapely.ops import unary_union
from .gis_inputs import RasterSource,spatial_reference


NODATA = -9999.0


def polygonal(g):
    if g.geom_type in ('Polygon','MultiPolygon'):
        return g
    if hasattr(g,'geoms'):
        return unary_union([polygonal(p) for p in g.geoms if p.geom_type in ('Polygon','MultiPolygon','GeometryCollection')])
    raise ValueError('Polygon geometry required for spatial audit export.')


def write_raster(path,values,transform,crs,*,units,support):
    path=Path(path)
    if path.exists():
        raise FileExistsError(path)
    data=np.asarray(values,float)
    if data.ndim != 2 or np.any(np.isinf(data)):
        raise ValueError('Raster export requires a finite-or-missing two-dimensional array.')
    if np.any(data == NODATA):
        raise ValueError('A valid value collides with the export nodata marker.')
    ds=gdal.GetDriverByName('GTiff').Create(str(path),data.shape[1],data.shape[0],1,gdal.GDT_Float64,
                                          options=['COMPRESS=DEFLATE','TILED=YES'])
    if ds is None:
        raise OSError('GeoTIFF creation failed.')
    ds.SetGeoTransform(tuple(transform));ds.SetProjection(crs.ExportToWkt())
    ds.SetMetadata(dict(UNITS=units,SPATIAL_SUPPORT=support,NODATA_MEANING='No value on the stated support'))
    band=ds.GetRasterBand(1);band.SetNoDataValue(NODATA);band.SetUnitType(units)
    band.SetDescription(path.stem)
    if band.WriteArray(np.where(np.isnan(data),NODATA,data)) != 0:
        raise OSError('GeoTIFF write failed.')
    band.FlushCache();band=None;ds.FlushCache();ds=None
    return dict(file=path.name,units=units,support=support,nodata=NODATA,shape=list(data.shape),transform=list(transform))


def write_polygons(path,geometries,columns,crs,*,units=None,point_geometry=False):
    """Use deterministic short field names; the JSON dictionary owns full names."""
    path=Path(path)
    if any(path.with_suffix(s).exists() for s in ('.shp','.shx','.dbf','.prj','.cpg')):
        raise FileExistsError(path)
    geometries=list(geometries)
    if any(len(v) != len(geometries) for v in columns.values()):
        raise ValueError('Shapefile attributes must match geometry records.')
    ds=ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(str(path))
    if ds is None:
        raise OSError('Shapefile creation failed.')
    layer=ds.CreateLayer(path.stem,crs,ogr.wkbPoint if point_geometry else ogr.wkbMultiPolygon,options=['ENCODING=UTF-8'])
    dictionary={}
    for i,(name,values) in enumerate(columns.items()):
        short=f'f{i:03d}'
        a=np.asarray(values)
        kind=ogr.OFTInteger64 if a.dtype.kind in 'iub' else ogr.OFTReal
        if a.dtype.kind not in 'iubf':
            raise ValueError('Numeric audit attributes required; labels belong in the dictionary.')
        definition=ogr.FieldDefn(short,kind)
        if kind==ogr.OFTReal:
            definition.SetWidth(32);definition.SetPrecision(12)
        if layer.CreateField(definition)!=0:
            raise OSError('Shapefile field creation failed.')
        dictionary[short]=dict(name=name,units=(units or {}).get(name,'identifier' if kind==ogr.OFTInteger64 else 'see run record'))
    for i,g in enumerate(geometries):
        feature=ogr.Feature(layer.GetLayerDefn())
        if point_geometry and (g.geom_type!='Point' or g.is_empty or g.has_z):
            raise ValueError('Two-dimensional points required for point export.')
        geometry=ogr.CreateGeometryFromWkb((g if point_geometry else polygonal(g)).wkb)
        feature.SetGeometry(geometry if point_geometry else ogr.ForceToMultiPolygon(geometry))
        for short,entry in dictionary.items():
            value=np.asarray(columns[entry['name']])[i]
            feature.SetField(short,int(value) if np.asarray(value).dtype.kind in 'iub' else float(value))
        if layer.CreateFeature(feature)!=0:
            raise OSError('Shapefile feature write failed.')
        feature=None
    layer=None;ds=None
    for suffix in ('.shp','.shx','.dbf','.prj','.cpg'):
        if not path.with_suffix(suffix).exists():
            raise OSError(f'Missing shapefile sidecar: {suffix}.')
    dictionary_path=path.with_suffix('.fields.json')
    dictionary_path.write_text(json.dumps(dictionary,indent=2),encoding='utf-8')
    return dict(file=path.name,records=len(geometries),field_dictionary=dictionary_path.name,
                support=('Point positions' if point_geometry else 'Exact prepared polygon fragments')+'; decimal attributes rounded to 12 places; machine records retain full precision')


def export_nominal_gis(output,*,prepared,result,crs,measure,boundary,zones,exclusions,
                       classes,stock_spec,uncertainty_spec,built_up=None,administrative=None,travel=None,points=None):
    output=Path(output);output.mkdir(exist_ok=False)
    layers=[]
    shape=tuple(prepared.audit['shape']);transform=prepared.audit['transform']
    origin=prepared.audit['source_origin'];full_width=prepared.audit['source_shape'][1]
    ids=prepared.source_cell_ids
    rows=ids//full_width-origin[0];cols=ids%full_width-origin[1]
    if np.any(rows<0) or np.any(rows>=shape[0]) or np.any(cols<0) or np.any(cols>=shape[1]):
        raise ValueError('Prepared source IDs fall outside the export window.')
    area=np.zeros(shape);np.add.at(area,(rows,cols),prepared.area_ha)
    def raster(name,values,units,support):
        layers.append(write_raster(output/(name+'.tif'),values,transform,crs,units=units,support=support))
    raster('eligible_area',np.where(area>0,area,np.nan),'ha','Sum of eligible fragments in each native stock cell; nodata means no eligible resource')
    fraction=np.full(shape,np.nan)
    for r,c in zip(*np.nonzero(area>0)):
        def xy(rr,cc):return (transform[0]+cc*transform[1]+rr*transform[2],transform[3]+cc*transform[4]+rr*transform[5])
        full=Polygon([xy(r,c),xy(r,c+1),xy(r+1,c+1),xy(r+1,c)])
        fraction[r,c]=area[r,c]*10000/measure(full)
    raster('eligible_fraction',fraction,'fraction','Eligible area divided by complete native stock-cell area')
    window=tuple(prepared.audit['native_window'])
    for name,spec in [('mapped_stock',stock_spec),('stock_uncertainty',uncertainty_spec)]:
        with RasterSource(spec) as source:
            data=source.read(window)*prepared.audit['physical_unit_factor']
        units='fraction' if prepared.audit['stock_mode']=='canopy' else 't_dry_matter/ha'
        raster(name,data,units,'Source observations across the native bounding window, including outside the assessment; source nodata preserved')
    grid_ids=(np.arange(shape[0])[:,None]+origin[0])*full_width+np.arange(shape[1])[None,:]+origin[1]
    if np.any(grid_ids>2**53):
        raise ValueError('Source IDs exceed exact Float64 representation.')
    raster('source_cell_id',grid_ids,'identifier','Full-raster row-major source-cell identity across the native bounding window')
    units={'area_ha':'ha','source_cell_id':'identifier','zone_index':'identifier'}
    for name,values in result.cells.items():
        if name=='area_ha':continue
        units[name]='fraction' if name=='active_year_fraction' else ('t_dry_matter/ha/year' if name=='peak_increment_t_ha_year' else 't_dry_matter/ha')
        summed=np.zeros(shape);np.add.at(summed,(rows,cols),values*prepared.area_ha)
        weighted=np.full(shape,np.nan);np.divide(summed,area,out=weighted,where=area>0)
        raster(name,weighted,units[name],'Eligible-area-weighted mean across fragments of each native stock cell; multiply by eligible_area to recover totals')
        if name!='active_year_fraction':
            raster(name+'_total',np.where(area>0,summed,np.nan),
                   't_dry_matter/year' if name=='peak_increment_t_ha_year' else 't_dry_matter',
                   'Sum across eligible fragments of each native stock cell')
    columns=dict(record_id=np.arange(len(ids)),source_cell_id=ids,zone_index=prepared.zone_index,**result.cells)
    layers.append(write_polygons(output/'calculation_records.shp',prepared.geometries,columns,crs,units=units))
    layers.append(write_polygons(output/'assessment.shp',[boundary],{'record_id':[0]},crs))
    if travel is not None:
        indices=np.arange(len(points))
        layers.append(write_polygons(output/'collection_points.shp',[g for _,g in points],{'record_id':indices},crs,point_geometry=True))
        layers.append(write_polygons(output/'travel_buffers.shp',travel.buffers,
            {'record_id':indices,'radius_metres':np.full(len(points),travel.audit['radius_metres'])},crs,units={'radius_metres':'m'}))
        (output/'collection_point_ids.json').write_text(json.dumps(
            {str(i):identity for i,(identity,_) in enumerate(points)},indent=2),encoding='utf-8')
    layers.append(write_polygons(output/'zones.shp',[g for _,g in zones],{'zone_index':[i for i,_ in zones]},crs))
    layers.append(write_polygons(output/'exclusions.shp',exclusions,{'record_id':np.arange(len(exclusions))},crs))
    def categorical(name,support):
        cells=support.cells
        layers.append(write_polygons(output/(name+'.shp'),[r['geometry'] for r in cells],
            {k:np.array([r[k] for r in cells],dtype=int if k!='area_m2' else float) for k in ('source_cell_id','class_code','selected','area_m2')},crs,units={'area_m2':'m2'}))
        c,r,w,h=support.audit['native_window'];source=support.audit['source'];t=source['transform']
        affine=(t[0]+c*t[1]+r*t[2],t[1],t[2],t[3]+c*t[4]+r*t[5],t[4],t[5])
        grid=np.full((h,w),np.nan)
        for cell in cells:
            rr,cc=divmod(cell['source_cell_id'],source['shape'][1]);grid[rr-r,cc-c]=cell['class_code']
        layers.append(write_raster(output/(name+'.tif'),grid,affine,spatial_reference(source['crs_wkt']),units='class_code',
            support='Native categorical cells intersecting domain; polygon file retains exact partial-cell support'))
    categorical('land_cover',classes)
    if built_up is not None:categorical('built_up',built_up)
    if administrative is not None:
        layers.append(write_polygons(output/'household_allocation.shp',administrative['geometries'],administrative['columns'],crs))
    catalog=dict(crs_wkt=crs.ExportToWkt(),layers=layers,
                 note='Vector support uses the assessment CRS; categorical TIFFs retain their own source CRS and native grid. No pixel-level fNRB is exported.')
    (output/'layers.json').write_text(json.dumps(catalog,indent=2,allow_nan=False),encoding='utf-8')
    return catalog
