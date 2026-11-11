# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from osgeo import gdal
from open_fnrb.mc_workflow import run_assessment
from open_fnrb.replay import replay_iteration
from test_workflow import example


class IterationExportTests(unittest.TestCase):
    def test_recovery_reuses_complete_iterations_and_preserves_failed_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);config=example.create(root/'inputs')
            sampling=config.parent/'sampling.json'
            settings=json.loads(sampling.read_text())
            settings['settings'].update(initial_iterations=32,maximum_iterations=32)
            sampling.write_text(json.dumps(settings))
            output=root/'results'
            def failing(assessment,iteration,destination,**options):
                if iteration==2:
                    destination.mkdir()
                    (destination/'failure.json').write_text('{"error":"simulated storage failure"}')
                    raise OSError('simulated storage failure')
                return replay_iteration(assessment,iteration,destination,**options)
            with patch('open_fnrb.iteration_exports.replay_iteration',side_effect=failing):
                with self.assertRaisesRegex(OSError,'storage failure'):
                    run_assessment(config,sampling,output,full_iteration_gis=True)
            self.assertEqual(json.loads((output/'status.json').read_text())['pending_exports'],['full-iteration GIS'])
            parent=output/'iteration_exports'
            first=parent/'iteration_000000'/'complete.json'
            first_bytes=first.read_bytes()
            checkpoint=(output/'monte_carlo'/'checkpoint.json').read_bytes()
            # Request persists even when the flag is omitted on resume.
            final=run_assessment(config,sampling,output,resume=True)
            self.assertEqual(final['pending_exports'],[])
            self.assertEqual(final['iteration_export']['iterations'],32)
            self.assertEqual(first.read_bytes(),first_bytes)
            self.assertEqual((output/'monte_carlo'/'checkpoint.json').read_bytes(),checkpoint)
            self.assertTrue((parent/'iteration_000002'/'attempt_0001'/'failure.json').exists())
            self.assertTrue((parent/'iteration_000002'/'attempt_0002'/'gis'/'iteration_records.shp').exists())
            index=json.loads((parent/'index.json').read_text())
            self.assertEqual([r['iteration'] for r in index['records']],list(range(32)))
            for iteration in (0,15,31):
                folder=output/index['records'][iteration]['directory']
                result=json.loads((folder/'iteration.json').read_text())
                raster=gdal.Open(str(folder/'gis'/'annual_regeneration_t_ha_total.tif'))
                self.assertAlmostEqual(float(raster.ReadAsArray().sum()),result['result']['annual_woody_biomass_regeneration_tonnes'])
                raster=None
            target=output/index['records'][0]['directory']/'iteration_cells.csv'
            target.write_text('altered')
            with self.assertRaisesRegex(ValueError,'Changed file'):
                run_assessment(config,sampling,output,resume=True)

    def test_optional_export_deferred_until_simulation_finishes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);config=example.create(root/'inputs')
            output=root/'results'
            result=run_assessment(config,config.parent/'sampling.json',output,stop_after=3,full_iteration_gis=True)
            self.assertTrue(result['full_iteration_gis_requested'])
            self.assertIn('full-iteration GIS',result['pending_exports'])
            self.assertFalse((output/'iteration_exports').exists())
