# SPDX-License-Identifier: GPL-3.0-or-later
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from openpyxl import load_workbook
from open_fnrb.mc_workflow import run_assessment
from test_workflow import example


class MCWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.config=example.create(self.root/'inputs')
        self.sampling=self.root/'sampling.json'
        self.settings=dict(schema_version=1,stock={'dependence':'independent','zero_policy':'fixed_zero','acknowledged':True},
            parameters={'dependence':'independent_shared_groups','acknowledged':True},
            settings={'seed':42,'initial_iterations':32,'extension_iterations':16,'maximum_iterations':64,
                      'precision_target':.000001,'required_passes':2,'checkpoint_interval':8})
        self.sampling.write_text(json.dumps(self.settings))

    def tearDown(self):self.temp.cleanup()

    def test_resume_matches_uninterrupted_sequence(self):
        full=run_assessment(self.config,self.sampling,self.root/'full')
        stopped=run_assessment(self.config,self.sampling,self.root/'resumed',stop_after=17)
        self.assertEqual(stopped['monte_carlo']['status'],'interrupted')
        self.assertFalse((self.root/'resumed'/'spatial_exports').exists())
        self.check_excel(self.root/'resumed',stopped)
        final=run_assessment(self.config,self.sampling,self.root/'resumed',resume=True)
        self.check_excel(self.root/'resumed',final)
        spatial=self.root/'resumed'/final['spatial_export']['directory']
        self.assertTrue((spatial/'gis'/'spatial_uncertainty.shp').exists())
        self.assertTrue((spatial/'gis'/'annual_regeneration_t_ha_p10.tif').exists())
        self.assertEqual(full['monte_carlo']['summaries'],final['monte_carlo']['summaries'])
        self.assertEqual(full['monte_carlo']['precision_history'],final['monte_carlo']['precision_history'])
        for name in ('iterations.csv','parameter_draws.jsonl'):
            self.assertEqual((self.root/'full'/'monte_carlo'/name).read_bytes(),(self.root/'resumed'/'monte_carlo'/name).read_bytes())

    def check_excel(self,out,result):
        workbook=load_workbook(out/'summary.xlsx',read_only=True)
        rows={row[0]:row[1:] for row in workbook['Uncertainty'].iter_rows(min_row=7,values_only=True)}
        stats=result['monte_carlo']['summaries']['fnrb']
        for actual,key in zip(rows['fNRB'][1:6],('mean','median','standard_deviation','p10','p90')):
            self.assertAlmostEqual(actual,stats[key])
        diagnostics={row[0]:row[1] for row in workbook['Diagnostics'].iter_rows(min_row=7,values_only=True)}
        self.assertEqual(diagnostics['Completed iterations'],result['monte_carlo']['iterations'])
        self.assertEqual(diagnostics['Monte Carlo status'],result['monte_carlo']['status'])
        workbook.close()

    def test_export_budget_failure_can_resume_without_resampling(self):
        out=self.root/'budget'
        with self.assertRaisesRegex(ValueError,'scratch bytes'):
            run_assessment(self.config,self.sampling,out,maximum_scratch_bytes=1)
        status=json.loads((out/'status.json').read_text())
        self.assertEqual(status['status'],'export_failed')
        self.assertEqual(status['monte_carlo_status'],'precision_limit_reached')
        checkpoint=(out/'monte_carlo'/'checkpoint.json').read_bytes()
        draws=(out/'monte_carlo'/'parameter_draws.jsonl').read_bytes()
        failed=out/'spatial_exports'/'attempt_0001'
        failure=(failed/'failure.json').read_bytes()
        final=run_assessment(self.config,self.sampling,out,resume=True)
        self.assertEqual(final['spatial_export']['directory'],'spatial_exports/attempt_0002')
        self.assertEqual((out/'monte_carlo'/'checkpoint.json').read_bytes(),checkpoint)
        self.assertEqual((out/'monte_carlo'/'parameter_draws.jsonl').read_bytes(),draws)
        self.assertEqual((failed/'failure.json').read_bytes(),failure)
        self.assertNotIn('spatial Monte Carlo summaries',final['pending_exports'])
        again=run_assessment(self.config,self.sampling,out,resume=True)
        self.assertEqual(again['spatial_export'],final['spatial_export'])
        self.assertEqual(len(list((out/'spatial_exports').iterdir())),2)

    def test_changed_automatic_export_is_not_silently_reused(self):
        out=self.root/'changed_export'
        final=run_assessment(self.config,self.sampling,out)
        target=out/final['spatial_export']['directory']/'spatial_uncertainty.csv'
        target.write_text('Changed output')
        with self.assertRaisesRegex(ValueError,'Changed file'):
            run_assessment(self.config,self.sampling,out,resume=True)
        self.assertEqual(json.loads((out/'status.json').read_text())['status'],'export_failed')

    def test_changed_input_rejected_without_replacing_checkpoint(self):
        out=self.root/'result';run_assessment(self.config,self.sampling,out,stop_after=9)
        checkpoint=(out/'monte_carlo'/'checkpoint.json').read_bytes()
        status=(out/'status.json').read_bytes()
        p=self.config.parent/'harvest.csv';p.write_text(p.read_text().replace(',10,',',11,'))
        with self.assertRaisesRegex(ValueError,'Changed file'):
            run_assessment(self.config,self.sampling,out,resume=True)
        self.assertEqual((out/'monte_carlo'/'checkpoint.json').read_bytes(),checkpoint)
        self.assertEqual((out/'status.json').read_bytes(),status)
        self.assertIn('resume_failed',(out/'attempts.jsonl').read_text())

    def test_changed_settings_and_existing_output_rejected(self):
        out=self.root/'result';run_assessment(self.config,self.sampling,out,stop_after=9)
        self.settings['settings']['seed']=43;self.sampling.write_text(json.dumps(self.settings))
        with self.assertRaisesRegex(ValueError,'Changed workflow or sampling'):
            run_assessment(self.config,self.sampling,out,resume=True)
        with self.assertRaises(FileExistsError):run_assessment(self.config,self.sampling,out)

    def test_canopy_route_and_cli_resume(self):
        config=example.create(self.root/'canopy','canopy')
        self.settings['stock']['zero_policy']='bounded_cover';self.sampling.write_text(json.dumps(self.settings))
        out=self.root/'canopy_results';run_assessment(config,self.sampling,out,stop_after=5)
        env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[1]/'src')
        p=subprocess.run([sys.executable,'-m','open_fnrb','resume',str(config),'--sampling',str(self.sampling),
            '--output',str(out)],env=env,cwd=self.root,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)['monte_carlo']['iterations'],64)
        self.assertTrue((out/'nominal'/'gis'/'mapped_stock.tif').exists())
