# SPDX-License-Identifier: GPL-3.0-or-later
"""Create small invented GIS inputs for checking a QGIS Python installation."""
from pathlib import Path
import argparse
import csv
import json
from osgeo import gdal,ogr,osr
import numpy as np


def create(output,stock_mode='agb',boundary_mode='polygon',classification_uncertainty=False):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    crs=osr.SpatialReference();crs.ImportFromEPSG(6933)
    def raster(name,value,units):
        ds=gdal.GetDriverByName('GTiff').Create(str(output/name),2,2,1,gdal.GDT_Float64)
        ds.SetProjection(crs.ExportToWkt());ds.SetGeoTransform((0,100,0,200,0,-100))
        band=ds.GetRasterBand(1);band.WriteArray(np.full((2,2),value,dtype=float));band.SetUnitType(units)
        band=None;ds=None
        return dict(path=name,units=units,source='Invented installation example',version='1',date='2026-01-01')
    stock=raster('stock.tif',20 if stock_mode=='agb' else .2,'t_dry_matter/ha' if stock_mode=='agb' else 'fraction')
    uncertainty=raster('uncertainty.tif',2 if stock_mode=='agb' else .02,stock['units'])
    land=raster('classes.tif',1,'class_code')
    ds=ogr.GetDriverByName('GPKG').CreateDataSource(str(output/'geometry.gpkg'))
    layer=ds.CreateLayer('area',crs,ogr.wkbPolygon)
    layer.CreateField(ogr.FieldDefn('zone_id',ogr.OFTString))
    feature=ogr.Feature(layer.GetLayerDefn());feature.SetField('zone_id','synthetic_zone')
    feature.SetGeometry(ogr.CreateGeometryFromWkt('POLYGON ((0 0, 200 0, 200 200, 0 200, 0 0))'))
    layer.CreateFeature(feature);feature=None;layer=None;ds=None
    tables={
      'Harvest':[['assessment_id','mode','estimated_annual_harvest_tonnes','households','woody_biomass_use_tonnes_per_household_year','source'],['synthetic','annual_total',10,'','','Invented example']],
      'Parameters':[['zone_id','increment_mean','increment_sd','capacity_mean','capacity_sd','increment_group','capacity_group','source'],['synthetic_zone',2,.2,100,10,'growth','capacity','Invented example; not IPCC defaults']],
      'Eligibility':[['class_code','eligible','source'],[1,'TRUE','Invented class']]}
    for name,rows in tables.items():
        with (output/(name.lower()+'.csv')).open('w',newline='',encoding='utf-8') as handle:
            csv.writer(handle).writerows(rows)
    intake=dict(schema_version=2,assessment_id='synthetic',tables={name:name.lower()+'.csv' for name in tables},harvest_uncertainty={'kind':'fixed'})
    (output/'inputs.json').write_text(json.dumps(intake,indent=2),encoding='utf-8')
    config=dict(schema_version=1,tabular_config='inputs.json',stock_mode=stock_mode,stock=stock,
        stock_uncertainty=uncertainty,uncertainty_interpretation='standard_deviation' if stock_mode=='agb' else 'pre_truncation_normal_scale',
        boundary={'path':'geometry.gpkg','layer':'area'},zones={'vector':{'path':'geometry.gpkg','layer':'area'},'zone_field':'zone_id'},
        land_cover=land,exclusions=[],projection_suitability_acknowledged=True)
    if boundary_mode=='travel':
        ds=ogr.Open(str(output/'geometry.gpkg'),1)
        layer=ds.CreateLayer('collection_points',crs,ogr.wkbPoint)
        layer.CreateField(ogr.FieldDefn('point_id',ogr.OFTString))
        for identity,x in [('synthetic_point_a',90),('synthetic_point_b',110)]:
            feature=ogr.Feature(layer.GetLayerDefn());feature.SetField('point_id',identity)
            feature.SetGeometry(ogr.CreateGeometryFromWkt(f'POINT ({x} 100)'))
            layer.CreateFeature(feature);feature=None
        layer=None;ds=None
        with (output/'travel.csv').open('w',newline='',encoding='utf-8') as handle:
            csv.writer(handle).writerows([
                ['assessment_id','round_trip_hours','travelling_share','speed_kmh','edge_tolerance_metres','source'],
                ['synthetic',.04,.5,4,.1,'Invented installation example']])
        intake['tables']['Travel']='travel.csv'
        (output/'inputs.json').write_text(json.dumps(intake,indent=2),encoding='utf-8')
        config['boundary']={'kind':'travel','points':{'path':'geometry.gpkg','layer':'collection_points','id_field':'point_id'}}
    elif boundary_mode!='polygon':
        raise ValueError('Unsupported example boundary mode.')
    if classification_uncertainty:
        ds=gdal.Open(str(output/'classes.tif'),gdal.GA_Update)
        ds.GetRasterBand(1).WriteArray(np.array([[1,2],[1,2]]));ds=None
        with (output/'eligibility.csv').open('a',encoding='utf-8') as handle:handle.write('2,FALSE,Invented second class\n')
        (output/'classification_matrix.csv').write_text('mapped_class,reference_class,count\n1,1,9\n1,2,1\n2,1,1\n2,2,9\n',encoding='utf-8')
        config['classification_uncertainty']=dict(matrix='classification_matrix.csv',source_id='Invented illustration; not validation data',
            orientation='mapped_rows_reference_columns',dependence='independent_native_cells',acknowledged=True,scope='resource_eligibility_only')
    (output/'workflow.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    sampling=dict(schema_version=1,
        stock={'dependence':'independent','zero_policy':'fixed_zero' if stock_mode=='agb' else 'bounded_cover','acknowledged':True},
        parameters={'dependence':'independent_shared_groups','acknowledged':True},
        settings={'seed':20261027,'initial_iterations':10000,'extension_iterations':2500,
                  'maximum_iterations':50000,'precision_target':.005,'required_passes':2,'checkpoint_interval':100})
    (output/'sampling.json').write_text(json.dumps(sampling,indent=2),encoding='utf-8')
    return output/'workflow.json'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('output')
    parser.add_argument('--stock-mode',choices=['agb','canopy'],default='agb')
    parser.add_argument('--boundary-mode',choices=['polygon','travel'],default='polygon')
    parser.add_argument('--classification-uncertainty',action='store_true')
    args=parser.parse_args();print(create(args.output,args.stock_mode,args.boundary_mode,args.classification_uncertainty))
