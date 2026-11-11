# SPDX-License-Identifier: GPL-3.0-or-later
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
from openpyxl import load_workbook
from osgeo import gdal,ogr,osr
from open_fnrb.workflow import run_nominal
from open_fnrb.annual import assess_year

EXAMPLE=Path(__file__).resolve().parents[1]/'examples'/'create_nominal_example.py'
spec=importlib.util.spec_from_file_location('synthetic_example',EXAMPLE)
example=importlib.util.module_from_spec(spec);spec.loader.exec_module(example)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_both_routes_match_known_prepared_calculation(self):
        expected=assess_year([1.]*4,[20.]*4,[100.]*4,[2.]*4,10).summary
        for mode in ('agb','canopy'):
            config=example.create(self.root/mode,mode)
            out=self.root/(mode+'_results')
            actual=run_nominal(config,out)
            self.assertEqual(actual,expected)
            workbook=load_workbook(out/'summary.xlsx',read_only=True)
            cells={row[0]:row[1] for row in workbook['Summary'].iter_rows(min_row=7,values_only=True)}
            self.assertAlmostEqual(cells['fNRB'],actual['fnrb'])
            self.assertEqual(cells['prescribed annual harvest tonnes'],actual['prescribed_annual_harvest_tonnes'])
            self.assertIs(cells['zero prescribed harvest'],False)
            self.assertEqual(workbook['Uncertainty']['B7'].value,'Not requested')
            workbook.close()
            record=json.loads((out/'run_record.json').read_text())
            self.assertEqual(record['output_scope'],'nominal_tables_gis_and_excel')
            self.assertIn('qgis.core',record['runtime']['dependencies'])
            self.assertIn('version',record['runtime']['dependencies']['scipy'])
            self.assertTrue(record['vectors'][0]['files'][0]['sha256'])
            self.assertTrue((out/'manifest.json').exists())
            ds=gdal.Open(str(out/'gis'/'annual_regeneration_t_ha_total.tif'))
            self.assertAlmostEqual(float(ds.ReadAsArray().sum()),actual['annual_woody_biomass_regeneration_tonnes'])
            self.assertEqual(ds.GetGeoTransform(),(0,100,0,200,0,-100))
            self.assertEqual(ds.GetRasterBand(1).GetUnitType(),'t_dry_matter')
            ds=None
            for suffix in ('.shp','.shx','.dbf','.prj','.cpg'):
                self.assertTrue((out/'gis'/('calculation_records'+suffix)).exists())
            dictionary=json.loads((out/'gis'/'calculation_records.fields.json').read_text())
            self.assertTrue(any(v['name']=='source_cell_id' for v in dictionary.values()))
            self.assertTrue(any(f['path'].endswith('.tif') for f in json.loads((out/'manifest.json').read_text())['files']))

    def test_failed_input_keeps_logs(self):
        config=example.create(self.root/'inputs')
        (config.parent/'uncertainty.tif').unlink()
        out=self.root/'failed'
        with self.assertRaises(FileNotFoundError):run_nominal(config,out)
        self.assertEqual(json.loads((out/'status.json').read_text())['status'],'failed')
        self.assertIn('uncertainty.tif',(out/'failure.json').read_text())
        self.assertIn('failed',(out/'events.jsonl').read_text())

    def test_different_land_cover_crs_retains_native_audit_raster(self):
        from pyproj import Transformer
        config=example.create(self.root/'different_crs')
        cfg=json.loads(config.read_text())
        transform=Transformer.from_crs(6933,4326,always_xy=True)
        xmax,ymax=transform.transform(200,200)
        source=config.parent/'classes.tif'
        ds=gdal.Open(str(source),gdal.GA_Update)
        crs=osr.SpatialReference();crs.ImportFromEPSG(4326)
        affine=(0,xmax/2,0,ymax,0,-ymax/2)
        ds.SetProjection(crs.ExportToWkt());ds.SetGeoTransform(affine);ds=None
        cfg['land_cover_transform']={
            'domain_to_source':dict(max_source_segment=100,target_tolerance=1e-10,maximum_accuracy_metres=0),
            'cells_to_stock':dict(max_source_segment=.001,target_tolerance=.00001,maximum_accuracy_metres=0)}
        config.write_text(json.dumps(cfg))
        out=self.root/'different_crs_results'
        result=run_nominal(config,out)
        self.assertAlmostEqual(result['eligible_area_ha'],4,places=7)
        ds=gdal.Open(str(out/'gis'/'land_cover.tif'))
        self.assertEqual(ds.GetGeoTransform(),affine)
        self.assertTrue(ds.GetSpatialRef().IsGeographic());ds=None
        vector=ogr.Open(str(out/'gis'/'land_cover.shp'))
        self.assertTrue(vector.GetLayer().GetSpatialRef().IsProjected());vector=None
        record=json.loads((out/'run_record.json').read_text())
        self.assertIn('domain_transformation',json.dumps(record))

    def test_existing_output_is_preserved(self):
        config=example.create(self.root/'inputs');out=self.root/'results'
        run_nominal(config,out);before=(out/'manifest.json').read_bytes()
        with self.assertRaises(FileExistsError):run_nominal(config,out)
        self.assertEqual((out/'manifest.json').read_bytes(),before)

    def test_built_up_allocation_through_files(self):
        config=example.create(self.root/'inputs');folder=config.parent
        (folder/'harvest.csv').write_text('assessment_id,mode,estimated_annual_harvest_tonnes,households,woody_biomass_use_tonnes_per_household_year,source\nsynthetic,built_up_allocation,,,2.5,Invented example\n')
        (folder/'admin.csv').write_text('administrative_id,households,source\nsynthetic_zone,100,Invented example\n')
        inputs=json.loads((folder/'inputs.json').read_text());inputs['tables']['AdminHouseholds']='admin.csv'
        (folder/'inputs.json').write_text(json.dumps(inputs))
        workflow=json.loads(config.read_text())
        workflow['household_allocation']=dict(administrative_vector={'path':'geometry.gpkg','layer':'area'},
                    id_field='zone_id',built_up=workflow['land_cover'],rules_table='eligibility.csv')
        config.write_text(json.dumps(workflow))
        out=self.root/'allocated';actual=run_nominal(config,out)
        self.assertEqual(actual,assess_year([1.]*4,[20.]*4,[100.]*4,[2.]*4,250).summary)
        audit=json.loads((out/'run_record.json').read_text())
        self.assertEqual(audit['harvest']['audit']['households'],100)

    def test_explicit_exclusions_and_unknown_fields(self):
        config=example.create(self.root/'inputs');value=json.loads(config.read_text())
        value.pop('exclusions');config.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'Configuration requires'):
            run_nominal(config,self.root/'failed')

    def test_no_eligible_resources_exports_nodata_and_empty_records(self):
        config=example.create(self.root/'inputs')
        p=config.parent/'eligibility.csv';p.write_text(p.read_text().replace('TRUE','FALSE'))
        out=self.root/'empty';result=run_nominal(config,out)
        self.assertEqual(result['fnrb'],1)
        ds=gdal.Open(str(out/'gis'/'eligible_area.tif'))
        self.assertTrue(np.all(ds.ReadAsArray()==ds.GetRasterBand(1).GetNoDataValue()));ds=None
        vector=ogr.Open(str(out/'gis'/'calculation_records.shp'))
        self.assertEqual(vector.GetLayer(0).GetFeatureCount(),0);vector=None

    def test_fragment_weighted_raster_reconciles(self):
        config=example.create(self.root/'inputs');folder=config.parent
        with (folder/'parameters.csv').open('a') as f:
            f.write('second_zone,4,0.4,100,10,growth2,capacity,Invented example\n')
        ds=ogr.Open(str(folder/'geometry.gpkg'),1)
        crs=osr.SpatialReference();crs.ImportFromEPSG(6933)
        layer=ds.CreateLayer('zones',crs,ogr.wkbPolygon);layer.CreateField(ogr.FieldDefn('zone_id',ogr.OFTString))
        for identity,left,right in [('synthetic_zone',0,50),('second_zone',50,200)]:
            feature=ogr.Feature(layer.GetLayerDefn());feature.SetField('zone_id',identity)
            feature.SetGeometry(ogr.CreateGeometryFromWkt(f'POLYGON (({left} 0,{right} 0,{right} 200,{left} 200,{left} 0))'))
            layer.CreateFeature(feature);feature=None
        layer=None;ds=None
        cfg=json.loads(config.read_text());cfg['zones']['vector']['layer']='zones';config.write_text(json.dumps(cfg))
        out=self.root/'split';result=run_nominal(config,out)
        with np.load(out/'prepared_nominal.npz') as records:
            self.assertEqual(len(records['area_ha']),6)
            cell=records['source_cell_id']==0
            expected=float(np.sum(records['annual_regeneration_t_ha'][cell]*records['area_ha'][cell])/np.sum(records['area_ha'][cell]))
        ds=gdal.Open(str(out/'gis'/'annual_regeneration_t_ha.tif'));self.assertAlmostEqual(ds.ReadAsArray()[0,0],expected);ds=None
        ds=gdal.Open(str(out/'gis'/'annual_regeneration_t_ha_total.tif'))
        self.assertAlmostEqual(float(ds.ReadAsArray().sum()),result['annual_woody_biomass_regeneration_tonnes']);ds=None

    def test_cli_from_unrelated_working_directory(self):
        config=example.create(self.root/'inputs');out=self.root/'cli_results'
        env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[1]/'src')
        proc=subprocess.run([sys.executable,'-m','open_fnrb','nominal',str(config),'--output',str(out)],
                            cwd=self.root,env=env,capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertGreaterEqual(json.loads(proc.stdout)['fnrb'],0)
        self.assertIn('Excel summary complete',proc.stderr)
