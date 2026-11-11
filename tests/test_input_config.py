# SPDX-License-Identifier: GPL-3.0-or-later
import csv
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from open_fnrb.input_config import load_tabular_config
from open_fnrb.tables import SCHEMAS,validate_rows
from open_fnrb.simulation import Simulation


class InputConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        source = Path(__file__).resolve().parents[1]/'examples'/'tables'
        for path in source.iterdir():
            shutil.copy2(path,self.root/path.name)
        self.path = self.root/'inputs.json'

    def tearDown(self):
        self.temp.cleanup()

    def change(self,fn):
        config = json.loads(self.path.read_text())
        fn(config)
        self.path.write_text(json.dumps(config))

    def test_unsupported_tabular_schema_is_rejected(self):
        self.change(lambda config: config.update(schema_version=1))
        with self.assertRaisesRegex(ValueError,'schema version'):
            load_tabular_config(self.path)

    def test_packaged_workbook_headers_match_csv_contract(self):
        from openpyxl import load_workbook
        path=Path(__file__).resolve().parents[1]/'templates'/'Open_fNRB_input_template.xlsx'
        workbook=load_workbook(path,read_only=True)
        try:
            for name,headers in SCHEMAS.items():
                with self.subTest(table=name):
                    self.assertEqual(list(next(workbook[name].iter_rows(min_row=1,max_row=1,values_only=True))),headers)
        finally:
            workbook.close()

    def test_relative_paths_and_bootstrap_into_simulation(self):
        intake = load_tabular_config(self.path)
        harvest_inputs = intake.resolve_harvest()
        self.assertEqual(harvest_inputs['prescribed_annual_harvest_tonnes'],250)
        self.assertEqual(harvest_inputs['harvest_model']['households'],100)
        self.assertEqual(len(intake.audit['table_files']['Observations']['sha256']),64)
        sim = Simulation(area=[10.],zone_index=[0],source_cell_ids=[0],mapped_stock=[20.],stock_scale=[2.],
            parameters=intake.parameters(),stock_mode='agb',dependence='independent',zero_policy='fixed_zero',
            prescribed_annual_harvest_tonnes=harvest_inputs['prescribed_annual_harvest_tonnes'],harvest_model=harvest_inputs['harvest_model'],
            uncertainty_acknowledged=True,source_identity='synthetic',uncertainty_interpretation='standard deviation')
        self.assertEqual(sim.draw(42,0).metrics,sim.draw(42,0).metrics)
        self.assertEqual(intake.eligibility(),{1:True,2:False})

    def test_reject_ambiguous_json_and_unknown_fields(self):
        self.path.write_text('{"schema_version":1,"schema_version":2}')
        with self.assertRaisesRegex(ValueError,'Duplicate JSON'): load_tabular_config(self.path)
        self.path.write_text('{"schema_version":NaN}')
        with self.assertRaisesRegex(ValueError,'Invalid JSON'): load_tabular_config(self.path)

    def test_unused_observations_and_missing_acknowledgement(self):
        self.change(lambda c:c.update(harvest_uncertainty={'kind':'fixed'}))
        with self.assertRaisesRegex(ValueError,'not selected'): load_tabular_config(self.path)
        self.change(lambda c:c.update(harvest_uncertainty={'kind':'household_bootstrap',
                    'source_id':'example','design':'assumed_iid','acknowledged':False}))
        with self.assertRaisesRegex(ValueError,'acknowledgement'): load_tabular_config(self.path)

    def test_observation_mean_and_survey_design(self):
        obs = self.root/'observations.csv'
        obs.write_text(obs.read_text().replace('synthetic_obs_b,3,','synthetic_obs_b,4,'))
        with self.assertRaisesRegex(ValueError,'weighted mean'): load_tabular_config(self.path)
        obs.write_text(obs.read_text().replace('synthetic_obs_b,4,','synthetic_obs_b,3,').replace('synthetic_unit_b','synthetic_unit_a'))
        with self.assertRaisesRegex(ValueError,'Repeated survey units'): load_tabular_config(self.path)
        self.change(lambda c:c['harvest_uncertainty'].update(design='independent_units'))
        self.assertEqual(load_tabular_config(self.path).resolve_harvest()['prescribed_annual_harvest_tonnes'],250)

    def test_fixed_and_lognormal_annual_totals(self):
        def configure(c):
            c['tables'].pop('Observations'); c['assessment_id']='synthetic_total'
            c['harvest_uncertainty']={'kind':'fixed'}
        self.change(configure)
        self.assertEqual(load_tabular_config(self.path).resolve_harvest()['prescribed_annual_harvest_tonnes'],250)
        self.change(lambda c:c.update(harvest_uncertainty={'kind':'lognormal','sd':25,'source_id':'synthetic','acknowledged':True}))
        self.assertEqual(load_tabular_config(self.path).resolve_harvest()['harvest_model']['sd'],25)

    def built_up(self):
        with (self.root/'harvest.csv').open('w',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=SCHEMAS['Harvest']);writer.writeheader()
            writer.writerow(dict(assessment_id='synthetic_households',mode='built_up_allocation',
                estimated_annual_harvest_tonnes='',households='',woody_biomass_use_tonnes_per_household_year=2.5,source='synthetic'))
        self.change(lambda c:c['tables'].update(AdminHouseholds='adminhouseholds.csv'))
        return load_tabular_config(self.path)

    def allocations(self):
        return [dict(administrative_id='synthetic_admin_a',households_total=100,households_allocated=50,
                     full_support_m2=1000,inside_support_m2=500),
                dict(administrative_id='synthetic_admin_b',households_total=200,households_allocated=50,
                     full_support_m2=1000,inside_support_m2=250)]

    def test_built_up_requires_and_reconciles_allocations(self):
        inputs=self.built_up()
        with self.assertRaisesRegex(ValueError,'complete spatial'): inputs.resolve_harvest()
        self.assertEqual(inputs.resolve_harvest(allocations=self.allocations())['prescribed_annual_harvest_tonnes'],250)
        bad=self.allocations();bad[0]['households_allocated']=80
        with self.assertRaisesRegex(ValueError,'reconcile'): inputs.resolve_harvest(allocations=bad)
        with self.assertRaisesRegex(ValueError,'identifiers'): inputs.resolve_harvest(allocations=self.allocations()[:1])

    def test_observation_and_administrative_validation(self):
        with self.assertRaises(ValueError):
            validate_rows('Observations',[dict(observation_id='A',annual_household_woody_biomass_use_tonnes=2,weight=0,unit_id='A',source='synthetic')])
        with self.assertRaises(ValueError):
            validate_rows('AdminHouseholds',[dict(administrative_id=1,households=100,source='synthetic')])

    def test_unknown_fields_and_assessment(self):
        self.change(lambda c:c.update(unrecognised=True))
        with self.assertRaisesRegex(ValueError,'Configuration requires'): load_tabular_config(self.path)
        self.change(lambda c:(c.pop('unrecognised'),c.update(assessment_id='missing')))
        with self.assertRaisesRegex(ValueError,'one record'): load_tabular_config(self.path)
