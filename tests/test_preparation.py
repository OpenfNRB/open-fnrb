# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
import numpy as np
from shapely.geometry import box
from open_fnrb.preparation import (prepare_native_grid, union_boundaries,
    travel_radius_metres, allocate_households, estimate_annual_harvest)
from open_fnrb.simulation import Simulation, ZoneParameters


class PreparationTests(unittest.TestCase):
    def fixture(self, **changes):
        args = dict(stock=[[20.,40.]], uncertainty=[[2.,4.]],
                    transform=(0,100,0,100,0,-100), boundary=box(0,0,150,100),
                    zones=[(0,box(0,0,50,100)),(1,box(50,0,200,100))],
                    eligibility=[box(0,0,200,100)], exclusions=[], area_crs_confirmed=True)
        args.update(changes)
        return prepare_native_grid(**args)

    def test_partial_cells_preserve_stock_and_source_identity(self):
        p = self.fixture()
        np.testing.assert_array_equal(p.source_cell_ids,[0,0,1])
        np.testing.assert_allclose(p.area_ha,[.5,.5,.5])
        self.assertEqual(float(np.dot(p.area_ha,p.mapped_stock)),40.)
        self.assertEqual(p.audit['eligible_area_ha'],1.5)
        self.assertEqual(p.audit['source_cells'],2)

    def test_overlap_union_and_exclusions(self):
        boundary = union_boundaries([box(0,0,100,100),box(50,0,150,100)])
        p = self.fixture(boundary=boundary, exclusions=[box(0,0,25,100)])
        self.assertAlmostEqual(p.area_ha.sum(),1.25)
        self.assertAlmostEqual(p.audit['noneligible_area_ha'],.25)

    def test_missing_data_not_hidden_by_exclusions(self):
        with self.assertRaisesRegex(ValueError,'source cell 1'):
            self.fixture(stock=[[20,np.nan]],exclusions=[box(100,0,200,100)])
        with self.assertRaises(ValueError):
            self.fixture(uncertainty=[[2,np.nan]])

    def test_coverage_and_ambiguous_zones_fail(self):
        for changes in [dict(boundary=box(0,0,201,100)),
                        dict(zones=[(0,box(0,0,100,100))]),
                        dict(zones=[(0,box(0,0,150,100)),(1,box(100,0,200,100))]),
                        dict(area_crs_confirmed=False)]:
            with self.assertRaises(ValueError):
                self.fixture(**changes)

    def test_explicit_no_resources(self):
        p = self.fixture(eligibility=[])
        self.assertEqual(len(p.area_ha),0)
        self.assertEqual(p.audit['eligible_area_ha'],0)

    def test_full_administrative_denominator(self):
        rows = allocate_households(administrative_areas=[('A',100,box(0,0,200,100))],
                    built_up_support=[box(0,0,100,100),box(150,0,200,100)],
                    boundary=box(0,0,100,100))
        self.assertAlmostEqual(rows[0]['households_allocated'],100*2/3)
        self.assertEqual(rows[0]['full_support_m2'],15000)
        self.assertAlmostEqual(estimate_annual_harvest(households=rows[0]['households_allocated'],
                             woody_biomass_use_tonnes_per_household_year=3),200)
        with self.assertRaisesRegex(ValueError,'Zero built-up'):
            allocate_households(administrative_areas=[('A',100,box(0,0,100,100))],
                                built_up_support=[],boundary=box(0,0,100,100))

    def test_household_overlap_rejected_and_travel_units(self):
        with self.assertRaisesRegex(ValueError,'overlaps'):
            allocate_households(administrative_areas=[('A',100,box(0,0,100,100)),
                ('B',100,box(50,0,150,100))],built_up_support=[box(0,0,200,100)],
                boundary=box(0,0,100,100))
        self.assertEqual(travel_radius_metres(round_trip_hours=2,travelling_share=.5,speed_kmh=4),2000)

    def test_prepared_records_feed_both_routes(self):
        for mode, stock in [('agb',[[20,40]]),('canopy',[[.2,.4]])]:
            p = self.fixture(stock=stock,uncertainty=[[0,0]])
            s = Simulation(area=p.area_ha,zone_index=p.zone_index,source_cell_ids=p.source_cell_ids,
                mapped_stock=p.mapped_stock,stock_scale=p.stock_scale,
                parameters=[ZoneParameters('A',2,0,100,0,'g','k'),
                            ZoneParameters('B',2,0,100,0,'g','k')],
                stock_mode=mode,dependence='independent',
                zero_policy='fixed_zero' if mode=='agb' else 'bounded_cover',prescribed_annual_harvest_tonnes=5,
                uncertainty_acknowledged=True,source_identity='synthetic',
                uncertainty_interpretation='standard deviation')
            self.assertTrue(np.isfinite(s.draw(1,0).metrics['fnrb']))


if __name__ == '__main__':
    unittest.main()
