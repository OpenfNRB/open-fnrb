# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from osgeo import gdal,ogr,osr
from open_fnrb.mc_workflow import run_assessment
from open_fnrb.replay import verified_assessment
from open_fnrb.spatial_summary import export_spatial_summary
from test_workflow import example


class SpatialSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def make_run(self,stop=None,split=False):
        config=example.create(self.root/'inputs')
        if split:
            with (config.parent/'parameters.csv').open('a') as f:
                f.write('second_zone,4,0.8,120,20,growth2,capacity2,Invented example\n')
            ds=ogr.Open(str(config.parent/'geometry.gpkg'),1)
            crs=osr.SpatialReference();crs.ImportFromEPSG(6933)
            layer=ds.CreateLayer('zones',crs,ogr.wkbPolygon);layer.CreateField(ogr.FieldDefn('zone_id',ogr.OFTString))
            for identity,left,right in [('synthetic_zone',0,50),('second_zone',50,200)]:
                feature=ogr.Feature(layer.GetLayerDefn());feature.SetField('zone_id',identity)
                feature.SetGeometry(ogr.CreateGeometryFromWkt(f'POLYGON (({left} 0,{right} 0,{right} 200,{left} 200,{left} 0))'))
                layer.CreateFeature(feature);feature=None
            layer=None;ds=None
            cfg=json.loads(config.read_text());cfg['zones']['vector']['layer']='zones';config.write_text(json.dumps(cfg))
        sampling=config.parent/'sampling.json';s=json.loads(sampling.read_text())
        s['settings'].update(initial_iterations=32,extension_iterations=16,maximum_iterations=32)
        sampling.write_text(json.dumps(s))
        run=self.root/'run';run_assessment(config,sampling,run,stop_after=stop);return run

    def test_exact_statistics_and_raster_totals(self):
        run=self.make_run();out=self.root/'spatial'
        result=export_spatial_summary(run,out,cell_block_size=1)
        sim,record,identity,payload=verified_assessment(run)
        draws=np.array([sim.realization(identity['settings']['seed'],i)[0].cells['annual_regeneration_t_ha'] for i in range(32)])
        with np.load(out/'spatial_uncertainty.npz') as values:
            np.testing.assert_allclose(values['annual_regeneration_t_ha_mean'],draws.mean(axis=0),rtol=1e-14)
            np.testing.assert_allclose(values['annual_regeneration_t_ha_p10'],np.quantile(draws,.1,axis=0),rtol=1e-14)
            np.testing.assert_allclose(values['annual_regeneration_t_ha_p90'],np.quantile(draws,.9,axis=0),rtol=1e-14)
            np.testing.assert_allclose(values['annual_regeneration_t_ha_standard_deviation'],draws.std(axis=0,ddof=1),rtol=1e-14)
        ds=gdal.Open(str(out/'gis'/'annual_regeneration_t_ha_mean_total.tif'))
        self.assertAlmostEqual(ds.ReadAsArray().sum(),draws.sum(axis=1).mean());ds=None
        self.assertEqual(result['verification'],'all_iterations_exact')
        self.assertFalse(list(out.glob('spatial_samples_*')))

    def test_budget_failure_preserves_audit(self):
        run=self.make_run();out=self.root/'too_small'
        with self.assertRaisesRegex(ValueError,'scratch bytes'):
            export_spatial_summary(run,out,maximum_scratch_bytes=1)
        self.assertEqual(json.loads((out/'status.json').read_text())['status'],'failed')

    def test_partial_run_is_not_reported_as_complete_uncertainty(self):
        run=self.make_run(stop=5)
        with self.assertRaisesRegex(ValueError,'completed Monte Carlo'):
            export_spatial_summary(run,self.root/'partial')

    def test_fragments_aggregated_before_percentiles(self):
        run=self.make_run(split=True);out=self.root/'split_summary'
        export_spatial_summary(run,out,cell_block_size=1)
        sim,_,identity,_=verified_assessment(run)
        cell=sim.cell_ids==0
        draws=[]
        for i in range(32):
            annual,_=sim.realization(identity['settings']['seed'],i)
            draws.append(float(np.dot(annual.cells['annual_regeneration_t_ha'][cell],sim.area[cell])/sim.area[cell].sum()))
        with np.load(out/'spatial_uncertainty.npz') as values:
            self.assertEqual(values['source_cell_id'][0],0)
            self.assertAlmostEqual(values['annual_regeneration_t_ha_p10'][0],np.quantile(draws,.1))
            self.assertAlmostEqual(values['annual_regeneration_t_ha_standard_deviation'][0],np.std(draws,ddof=1))
