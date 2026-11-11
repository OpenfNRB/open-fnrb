# SPDX-License-Identifier: GPL-3.0-or-later
"""Self-contained annual accounting tests using synthetic inputs."""
import unittest
import numpy as np
from open_fnrb import assess_year, stock_from_canopy


class AnnualTests(unittest.TestCase):
    def test_no_growth_known_answer(self):
        result = assess_year([2.], [10.], [20.], [0.], 6.)
        self.assertEqual(result.summary['fnrb'], 1.)
        self.assertEqual(result.summary['realised_harvest_tonnes'], 6.)
        self.assertEqual(result.summary['end_woody_stock_tonnes'], 14.)

    def test_stock_exhaustion_retains_harvest(self):
        result = assess_year([1.], [2.], [10.], [0.], 5.)
        self.assertEqual(result.summary['prescribed_annual_harvest_tonnes'], 5.)
        self.assertEqual(result.summary['unrealised_harvest_tonnes'], 3.)
        self.assertEqual(result.summary['fnrb'], 1.)

    def test_zero_stock_and_harvest(self):
        result = assess_year([1.], [0.], [10.], [2.], 0.)
        self.assertTrue(result.summary['zero_prescribed_harvest'])
        self.assertEqual(result.summary['fnrb'], 0.)
        self.assertEqual(result.summary['annual_woody_biomass_regeneration_tonnes'], 0.)

    def test_no_eligible_area(self):
        result = assess_year([], [], [], [], 15.)
        self.assertEqual(result.summary['fnrb'], 1.)
        self.assertEqual(result.summary['unrealised_harvest_tonnes'], 15.)

    def test_fixed_peak_capacity_adjustment(self):
        result = assess_year([1.], [100.], [70.], [3.], 10.)
        self.assertEqual(result.cells['effective_capacity_t_ha'][0], 100.)
        self.assertEqual(result.cells['peak_increment_t_ha_year'][0], 3.)
        self.assertEqual(result.summary['capacity_adjustment_tonnes'], 30.)
        self.assertGreater(result.summary['annual_woody_biomass_regeneration_tonnes'], 0.)

    def test_canopy_route_matches_direct_stock(self):
        capacity = np.array([40., 60.])
        stock = stock_from_canopy([.25, .75], capacity)
        np.testing.assert_array_equal(stock, [10., 45.])
        a = assess_year([1., 2.], stock, capacity, [2., 3.], 12.)
        b = assess_year([1., 2.], [10., 45.], capacity, [2., 3.], 12.)
        self.assertEqual(a.summary, b.summary)

    def test_same_capacity_draw_is_used_for_canopy(self):
        np.testing.assert_array_equal(stock_from_canopy([.5], [80.]), [40.])
        np.testing.assert_array_equal(stock_from_canopy([.5], [40.]), [20.])

    def test_uniform_prescribed_harvest_and_conservation(self):
        result = assess_year([1., 3.], [1., 80.], [100., 100.], [2., 2.], 20.)
        c = result.cells
        np.testing.assert_array_equal(c['prescribed_harvest_t_ha'], [5., 5.])
        np.testing.assert_allclose(c['starting_stock_t_ha'] + c['annual_regeneration_t_ha'] -
                                   c['realised_harvest_t_ha'], c['closing_stock_t_ha'])
        self.assertGreater(result.summary['unrealised_harvest_tonnes'], 0.)
        self.assertGreater(c['closing_stock_t_ha'][1], 0.)

    def test_chunk_size_does_not_change_results_materially(self):
        args = ([1., 2., 3.], [10., 20., 90.], [40., 60., 70.], [2., 4., 3.], 20.)
        a = assess_year(*args, chunk_size=1)
        b = assess_year(*args, chunk_size=10)
        for key in a.cells:
            np.testing.assert_allclose(a.cells[key], b.cells[key])
        self.assertAlmostEqual(a.summary['fnrb'], b.summary['fnrb'], places=12)

    def test_invalid_inputs_fail(self):
        for stock in ([np.nan], [-1.], [np.inf]):
            with self.assertRaises(ValueError):
                assess_year([1.], stock, [10.], [2.], 5.)
        with self.assertRaises(ValueError):
            stock_from_canopy([1.1], [10.])
        with self.assertRaises(ValueError):
            assess_year([0.], [2.], [10.], [2.], 5.)

    def test_independent_no_harvest_logistic_solution(self):
        b0, k, peak = 20., 80., 4.
        expected = k / (1. + (k / b0 - 1.) * np.exp(-4 * peak / k))
        result = assess_year([1.], [b0], [k], [peak], 0.)
        self.assertAlmostEqual(result.summary['end_woody_stock_tonnes'], expected, places=12)


if __name__ == '__main__':
    unittest.main()
