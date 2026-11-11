# SPDX-License-Identifier: GPL-3.0-or-later
"""Annual model and MC sampling integration with synthetic native-cell records."""
from pathlib import Path
import tempfile
import unittest
import numpy as np
from open_fnrb.simulation import Simulation, ZoneParameters, METRICS
from open_fnrb.monte_carlo import Settings, run


def model(mode='agb', **changes):
    args = dict(area=[1.,2.],zone_index=np.array([0,0]),source_cell_ids=np.array([4,9]),
                mapped_stock=[10.,40.] if mode == 'agb' else [.25,.75],
                stock_scale=[2.,5.] if mode == 'agb' else [.05,.08],
                parameters=[ZoneParameters('zone',3.,.5,50.,5.,'growth-z','capacity-z')],
                stock_mode=mode,dependence='independent',zero_policy='fixed_zero' if mode=='agb' else 'bounded_cover',
                prescribed_annual_harvest_tonnes=15.,uncertainty_acknowledged=True,source_identity='synthetic-stock',
                uncertainty_interpretation='Synthetic SD for tests')
    args.update(changes)
    return Simulation(**args)


class SimulationTests(unittest.TestCase):
    def test_both_routes_replay(self):
        for mode in ('agb','canopy'):
            m=model(mode)
            self.assertEqual(m.draw(4,7),m.draw(4,7))
            self.assertTrue(0 <= m.nominal().summary['fnrb'] <= 1)

    def test_fixed_uncertainty_equals_nominal(self):
        m=model(stock_scale=[0.,0.],parameters=[ZoneParameters('zone',3.,0.,50.,0.,'g','k')])
        self.assertEqual(m.draw(1,4).metrics['fnrb'],m.nominal().summary['fnrb'])

    def test_duplicate_parameter_records_share_draw(self):
        m=model(parameters=[ZoneParameters('a',3.,1.,50.,10.,'g','k'),ZoneParameters('b',3.,1.,50.,10.,'g','k')],
                zone_index=np.array([0,1]))
        p=m.draw(1,1).parameters
        self.assertEqual(p['increment'][0],p['increment'][1])
        self.assertEqual(p['reference_capacity'][0],p['reference_capacity'][1])

    def test_inconsistent_shared_parameter_fails(self):
        with self.assertRaises(ValueError):
            model(parameters=[ZoneParameters('a',3.,1.,50.,10.,'g','k'),ZoneParameters('b',4.,1.,50.,10.,'g','k')])

    def test_bootstrap_household_use_and_contract(self):
        m=model(prescribed_annual_harvest_tonnes=15.,harvest_model=dict(kind='household_bootstrap',households=5.,
                annual_household_woody_biomass_use_tonnes=[1.,3.,5.],design='assumed_iid',source_id='survey',acknowledged=True))
        self.assertIn(m.draw(2,0).metrics['prescribed_annual_harvest_tonnes'],[5., 25/3, 35/3, 15., 55/3, 65/3, 25.])
        self.assertEqual(m.contract()['harvest_model']['households'],5.)

    def test_real_annual_engine_runs_with_checkpoint(self):
        m=model('canopy')
        with tempfile.TemporaryDirectory() as folder:
            result=run(m.draw,settings=Settings(4,32,16,64,.5),contract=m.contract(),
                       metric_names=METRICS,fnrb_fields=('fnrb',),output=Path(folder)/'run')
            self.assertEqual(result['status'],'precision_met')
            self.assertEqual(result['iterations'],48)
            self.assertIn('p10',result['summaries']['fnrb'])


if __name__=='__main__':
    unittest.main()
