# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest
from osgeo import gdal
from open_fnrb.mc_workflow import run_assessment
from open_fnrb.replay import replay_iteration
from test_workflow import example


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)

    def tearDown(self):self.temp.cleanup()

    def create_run(self,mode='agb'):
        config=example.create(self.root/mode,mode)
        sampling=config.parent/'sampling.json';value=json.loads(sampling.read_text())
        value['settings'].update(initial_iterations=32,extension_iterations=16,maximum_iterations=32)
        sampling.write_text(json.dumps(value))
        out=self.root/(mode+'_run');run_assessment(config,sampling,out)
        return out

    def test_first_middle_last_and_source_unchanged(self):
        run=self.create_run();before=(run/'manifest.json').read_bytes()
        for iteration in (0,16,31):
            out=self.root/f'replay{iteration}'
            result=replay_iteration(run,iteration,out)
            self.assertEqual(result['verification'],'exact')
            self.assertTrue((out/'iteration_cells.npz').exists())
        self.assertEqual((run/'manifest.json').read_bytes(),before)

    def test_canopy_gis_reconciles_with_replayed_growth(self):
        run=self.create_run('canopy');out=self.root/'spatial'
        replay_iteration(run,7,out,gis=True)
        saved=json.loads((out/'iteration.json').read_text())
        ds=gdal.Open(str(out/'gis'/'annual_regeneration_t_ha_total.tif'))
        self.assertAlmostEqual(float(ds.ReadAsArray().sum()),saved['result']['annual_woody_biomass_regeneration_tonnes']);ds=None
        for suffix in ('.shp','.dbf','.shx','.prj','.cpg'):
            self.assertTrue((out/'gis'/('iteration_records'+suffix)).exists())

    def test_out_of_range_and_protected_source(self):
        run=self.create_run()
        with self.assertRaisesRegex(ValueError,'not completed'):
            replay_iteration(run,32,self.root/'invalid')
        self.assertEqual(json.loads((self.root/'invalid'/'status.json').read_text())['status'],'failed')
        with self.assertRaisesRegex(ValueError,'separate'):
            replay_iteration(run,0,run/'replay')

    def test_corruption_and_active_lock_rejected(self):
        run=self.create_run();lock=run/'assessment.lock';lock.write_text('test lock')
        with self.assertRaisesRegex(ValueError,'locked'):
            replay_iteration(run,0,self.root/'locked')
        lock.unlink()
        checkpoint=run/'monte_carlo'/'checkpoint.json';value=json.loads(checkpoint.read_text())
        value['payload']['rows'][0][0]=.123;checkpoint.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'integrity'):
            replay_iteration(run,0,self.root/'corrupt')
