# SPDX-License-Identifier: GPL-3.0-or-later
import json
import math
from pathlib import Path
import tempfile
import unittest
from osgeo import ogr,osr
from pyproj import Transformer
from open_fnrb.point_inputs import read_points
from open_fnrb.gis_inputs import spatial_reference
from open_fnrb.workflow import run_nominal
from test_workflow import example


class PointInputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def make_points(self,path,records,epsg=6933):
        crs=osr.SpatialReference();crs.ImportFromEPSG(epsg)
        ds=ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
        layer=ds.CreateLayer('points',crs,ogr.wkbPoint);layer.CreateField(ogr.FieldDefn('point_id',ogr.OFTString))
        for identity,x,y in records:
            feature=ogr.Feature(layer.GetLayerDefn());feature.SetField('point_id',identity)
            feature.SetGeometry(ogr.CreateGeometryFromWkt(f'POINT ({x} {y})'))
            layer.CreateFeature(feature);feature=None
        layer=None;ds=None

    def test_ids_and_positions_are_retained(self):
        path=self.root/'points.gpkg';self.make_points(path,[('001',100,100),('002',100,100)])
        points,audit=read_points(path,expected_crs=spatial_reference('EPSG:6933'),id_field='point_id')
        self.assertEqual([i for i,_ in points],['001','002'])
        self.assertEqual(audit['records'][0]['source_x'],100)
        self.assertEqual(len(audit['files'][0]['sha256']),64)

    def test_duplicate_and_empty_identifiers_fail(self):
        for n,records in enumerate([[('A',1,2),('A',3,4)],[('',1,2)],[(' A ',1,2)]]):
            path=self.root/f'points{n}.gpkg';self.make_points(path,records)
            with self.assertRaisesRegex(ValueError,'Point IDs'):
                read_points(path,expected_crs=spatial_reference('EPSG:6933'),id_field='point_id')

    def test_explicit_transform_and_original_coordinates(self):
        path=self.root/'points.gpkg'
        lon,lat=Transformer.from_crs(6933,4326,always_xy=True).transform(100,100)
        self.make_points(path,[('A',lon,lat)],4326)
        crs=spatial_reference('EPSG:6933')
        with self.assertRaisesRegex(ValueError,'explicit transformation'):
            read_points(path,expected_crs=crs,id_field='point_id')
        points,audit=read_points(path,expected_crs=crs,id_field='point_id',maximum_accuracy_metres=0)
        self.assertAlmostEqual(points[0][1].x,100,places=5)
        self.assertAlmostEqual(points[0][1].y,100,places=5)
        self.assertEqual(audit['records'][0]['source_x'],lon)
        self.assertEqual(audit['records'][0]['operation']['accuracy_metres'],0)

    def travel_config(self):
        config=example.create(self.root/'inputs');folder=config.parent
        self.make_points(folder/'points.gpkg',[('001',100,100),('002',100,100)])
        (folder/'travel.csv').write_text('assessment_id,round_trip_hours,travelling_share,speed_kmh,edge_tolerance_metres,source\nsynthetic,0.04,0.5,4,0.1,Invented example\n')
        tabular=json.loads((folder/'inputs.json').read_text());tabular['tables']['Travel']='travel.csv'
        (folder/'inputs.json').write_text(json.dumps(tabular))
        value=json.loads(config.read_text());value['boundary']={'kind':'travel','points':{'path':'points.gpkg','id_field':'point_id'}}
        config.write_text(json.dumps(value));return config

    def test_travel_workflow_exports_points_buffers_and_union(self):
        config=self.travel_config();out=self.root/'results';summary=run_nominal(config,out)
        audit=json.loads((out/'run_record.json').read_text())
        self.assertEqual(audit['travel']['radius_metres'],40)
        self.assertAlmostEqual(audit['travel']['overlap_area_m2'],audit['travel']['union_area_m2'])
        self.assertAlmostEqual(summary['eligible_area_ha'],audit['travel']['union_area_m2']/10000)
        self.assertLess(abs(summary['eligible_area_ha']/(math.pi*40**2/10000)-1),.01)
        for name,count in [('collection_points',2),('travel_buffers',2),('assessment',1)]:
            ds=ogr.Open(str(out/'gis'/(name+'.shp')))
            self.assertEqual(ds.GetLayer(0).GetFeatureCount(),count);ds=None
            for suffix in ('.shp','.shx','.dbf','.prj','.cpg'):
                self.assertTrue((out/'gis'/(name+suffix)).exists())
        self.assertEqual(json.loads((out/'gis'/'collection_point_ids.json').read_text()),{'0':'001','1':'002'})

    def test_missing_travel_table_retains_failure_audit(self):
        config=self.travel_config();p=config.parent/'inputs.json'
        value=json.loads(p.read_text());value['tables'].pop('Travel');p.write_text(json.dumps(value))
        out=self.root/'failed'
        with self.assertRaisesRegex(ValueError,'Travel table'):run_nominal(config,out)
        self.assertEqual(json.loads((out/'status.json').read_text())['status'],'failed')
