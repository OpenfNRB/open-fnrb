# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest
import shutil
import numpy as np
from osgeo import gdal
from openpyxl import load_workbook
from open_fnrb.mc_workflow import run_assessment
from open_fnrb.replay import verified_assessment,replay_iteration
from test_workflow import example


class ClassificationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def configure(self,mode='agb',counts='1,1,1\n1,2,1\n2,1,1\n2,2,1\n'):
        config=example.create(self.root/mode,mode)
        previous=gdal.Open(str(config.parent/'classes.tif'));projection=previous.GetProjection();previous=None
        ds=gdal.GetDriverByName('GTiff').Create(str(config.parent/'classes.tif'),4,4,1,gdal.GDT_Float64)
        ds.SetProjection(projection);ds.SetGeoTransform((0,50,0,200,0,-50))
        ds.GetRasterBand(1).WriteArray(np.tile([1,2,1,2],(4,1)));ds.GetRasterBand(1).SetUnitType('class_code');ds=None
        with (config.parent/'eligibility.csv').open('a') as handle:handle.write('2,false,Invented exclusion class\n')
        (config.parent/'matrix.csv').write_text('mapped_class,reference_class,count\n'+counts)
        value=json.loads(config.read_text())
        value['classification_uncertainty']=dict(matrix='matrix.csv',source_id='Synthetic validation matrix',
            orientation='mapped_rows_reference_columns',dependence='independent_native_cells',acknowledged=True,scope='resource_eligibility_only')
        config.write_text(json.dumps(value))
        sampling=config.parent/'sampling.json';settings=json.loads(sampling.read_text())
        settings['settings'].update(initial_iterations=32,maximum_iterations=32,checkpoint_interval=8)
        sampling.write_text(json.dumps(settings))
        return config,sampling

    def test_classification_resume_replay_and_all_exports(self):
        config,sampling=self.configure();out=self.root/'result'
        stopped=run_assessment(config,sampling,out,stop_after=5,full_iteration_gis=True)
        self.assertEqual(stopped['monte_carlo']['status'],'interrupted')
        final=run_assessment(config,sampling,out,resume=True)
        self.assertEqual(final['pending_exports'],[])
        sim,record,identity,payload=verified_assessment(out)
        draws=[sim.realization(identity['settings']['seed'],i)[0] for i in range(32)]
        areas=np.array([d.summary['eligible_area_ha'] for d in draws])
        self.assertGreater(len(set(areas)),1)
        self.assertAlmostEqual(final['nominal']['eligible_area_ha'],2)
        self.assertEqual(final['iteration_export']['iterations'],32)
        spatial=out/final['spatial_export']['directory']
        with np.load(spatial/'spatial_uncertainty.npz') as values:
            self.assertAlmostEqual(values['eligible_area_ha_mean'].sum(),areas.mean())
            self.assertAlmostEqual(np.dot(values['annual_regeneration_t_ha_mean'],values['candidate_area_ha']),
                np.mean([d.summary['annual_woody_biomass_regeneration_tonnes'] for d in draws]))
            self.assertTrue(np.all((values['eligible_fraction_mean']>=0)&(values['eligible_fraction_mean']<=1)))
        replay=self.root/'replay';replay_iteration(out,7,replay,gis=True)
        raster=gdal.Open(str(replay/'gis'/'eligible_area.tif'))
        self.assertAlmostEqual(float(raster.ReadAsArray().sum()),areas[7]);raster=None
        raster=gdal.Open(str(replay/'gis'/'sampled_class.tif'))
        self.assertEqual((raster.RasterYSize,raster.RasterXSize),(4,4));raster=None
        with np.load(replay/'iteration_cells.npz') as values:
            self.assertIn('sampled_class',values.files)
            self.assertAlmostEqual(values['area_ha'].sum(),areas[7])
        wb=load_workbook(out/'summary.xlsx',read_only=True)
        diagnostics={r[0]:r[1] for r in wb['Diagnostics'].iter_rows(min_row=7,values_only=True)}
        self.assertEqual(diagnostics['Land-cover uncertainty'],'Sampled resource eligibility');wb.close()
        # A fresh run has identical draws, despite the interrupted first run.
        full=run_assessment(config,sampling,self.root/'full')
        self.assertEqual(full['monte_carlo']['summaries'],final['monte_carlo']['summaries'])
        checkpoint=(out/'monte_carlo'/'checkpoint.json').read_bytes()
        matrix=config.parent/'matrix.csv';matrix.write_text(matrix.read_text().replace('1,1,1','1,1,2'))
        with self.assertRaisesRegex(ValueError,'Changed file'):run_assessment(config,sampling,out,resume=True)
        self.assertEqual(checkpoint,(out/'monte_carlo'/'checkpoint.json').read_bytes())

    def test_canopy_all_ineligible_draws_export_zero_contributions(self):
        config,sampling=self.configure('canopy','1,1,0\n1,2,1\n2,1,0\n2,2,1\n')
        out=self.root/'canopy_result';result=run_assessment(config,sampling,out)
        self.assertEqual(result['monte_carlo']['summaries']['fnrb']['mean'],1)
        self.assertEqual(result['monte_carlo']['summaries']['eligible_area_ha']['mean'],0)
        replay=self.root/'empty_replay';replay_iteration(out,0,replay,gis=True)
        with np.load(replay/'iteration_cells.npz') as values:
            self.assertEqual(values['area_ha'].sum(),0)
            self.assertEqual(values['annual_regeneration_t_ha'].sum(),0)
        spatial=out/result['spatial_export']['directory']
        with np.load(spatial/'spatial_uncertainty.npz') as values:self.assertEqual(values['eligible_area_ha_p90'].sum(),0)

    def test_excel_matrix_and_no_candidate_resource(self):
        config,sampling=self.configure()
        example_matrix=Path(__file__).resolve().parents[1]/'examples'/'tables'/'classification_matrix.xlsx'
        shutil.copyfile(example_matrix,config.parent/'matrix.xlsx')
        cfg=json.loads(config.read_text());cfg['classification_uncertainty']['matrix']='matrix.xlsx'
        config.write_text(json.dumps(cfg))
        (config.parent/'eligibility.csv').write_text('class_code,eligible,source\n1,FALSE,Synthetic\n2,FALSE,Synthetic\n')
        out=self.root/'no_candidates';result=run_assessment(config,sampling,out)
        self.assertEqual(result['nominal']['eligible_area_ha'],0)
        self.assertEqual(result['monte_carlo']['summaries']['fnrb']['mean'],1)
        sim,_,_,_=verified_assessment(out);self.assertEqual(len(sim.area),0)
        self.assertEqual(sim.classification['model'].counts,((9.,1.),(1.,9.)))
