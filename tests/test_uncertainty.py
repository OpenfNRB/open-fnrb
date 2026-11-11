# SPDX-License-Identifier: GPL-3.0-or-later
"""Known-distribution and source-identity checks without project datasets."""
import unittest
import numpy as np
from scipy.special import ndtri
from open_fnrb.uncertainty import (cell_uniforms, positive_lognormal, parameter_draw,
                                  sample_agb, sample_cover, sample_classes, bootstrap_household_woody_biomass_use)


class UncertaintyTests(unittest.TestCase):
    def test_lognormal_matches_arithmetic_moments(self):
        z = ndtri((np.arange(100000) + .5) / 100000)
        x = positive_lognormal(50., 10., z)
        self.assertAlmostEqual(float(x.mean()), 50., delta=.002)
        self.assertAlmostEqual(float(x.std()), 10., delta=.01)
        np.testing.assert_array_equal(positive_lognormal([13.], [0.], [2.]), [13.])

    def test_cell_draws_survive_order_and_tiles(self):
        ids = np.array([100, 5, 100, 24], dtype=np.int64)
        all_values = cell_uniforms(ids, 19, 3, 'stock/source-a', 'independent')
        split = np.r_[cell_uniforms(ids[:2], 19, 3, 'stock/source-a', 'independent'),
                      cell_uniforms(ids[2:], 19, 3, 'stock/source-a', 'independent')]
        np.testing.assert_array_equal(all_values, split)
        np.testing.assert_array_equal(all_values[::-1], cell_uniforms(ids[::-1], 19, 3, 'stock/source-a', 'independent'))
        self.assertEqual(all_values[0], all_values[2])
        shared = cell_uniforms(ids, 19, 3, 'stock/source-a', 'shared')
        self.assertEqual(len(np.unique(shared)), 1)

    def test_parameter_group_is_reproducible_and_separate(self):
        self.assertEqual(parameter_draw(20, 4, 8, 2, 'capacity/zone'), parameter_draw(20, 4, 8, 2, 'capacity/zone'))
        self.assertNotEqual(parameter_draw(20, 4, 8, 2, 'capacity/zone'), parameter_draw(20, 4, 8, 2, 'growth/zone'))

    def test_agb_zero_policies_are_explicit(self):
        kwargs = dict(seed=1, iteration=0, stream='stock', dependence='independent', acknowledged=True)
        ids = np.array([1, 2, 3])
        x, info = sample_agb([0, 0, 40], [0, 5, 0], ids, zero_policy='fixed_zero', **kwargs)
        np.testing.assert_array_equal(x, [0, 0, 40])
        self.assertTrue(info['zero_uncertainty_omitted'][1])
        _, info = sample_agb([0, 0, 40], [0, 5, 0], ids, zero_policy='censored_normal', **kwargs)
        self.assertAlmostEqual(info['expected_mean_shift'][1], 5 / np.sqrt(2*np.pi))
        with self.assertRaises(ValueError):
            sample_agb([0], [1], np.array([1]), zero_policy='automatic', **kwargs)

    def test_cover_bounds_and_mean_shift(self):
        x, info = sample_cover([0., .5, 1.], [.1, .1, .1], np.array([1, 2, 3]),
                seed=1, iteration=0, stream='cover', dependence='shared', acknowledged=True)
        self.assertTrue(np.all((x >= 0) & (x <= 1)))
        self.assertAlmostEqual(info['expected_mean'][1], .5)
        self.assertGreater(info['expected_mean_shift'][0], 0)
        self.assertLess(info['expected_mean_shift'][2], 0)

    def test_repeated_cell_disagreement_and_missing_are_errors(self):
        kwargs = dict(seed=1, iteration=0, stream='stock', dependence='independent', acknowledged=True, zero_policy='fixed_zero')
        with self.assertRaises(ValueError):
            sample_agb([10, 11], [2, 2], np.array([1, 1]), **kwargs)
        with self.assertRaises(ValueError):
            sample_agb([np.nan], [1], np.array([1]), **kwargs)

    def test_classification_orientation_and_impossible_transitions(self):
        labels = sample_classes(np.ones(100, dtype=int), np.array([1, 2]), [[0, 10], [5, 0]],
                np.arange(100), seed=1, iteration=2, stream='classes', acknowledged=True)
        np.testing.assert_array_equal(labels, np.full(100, 2))

    def test_bootstrap_grouping_and_zero_household_use(self):
        kwargs = dict(seed=5, iteration=2, stream='survey', design='independent_units', acknowledged=True)
        a = bootstrap_household_woody_biomass_use([1, 1, 5, 5], unit_ids=['a', 'a', 'b', 'b'], **kwargs)
        b = bootstrap_household_woody_biomass_use([1, 5], unit_ids=['a', 'b'], **kwargs)
        self.assertEqual(a, b)
        self.assertEqual(bootstrap_household_woody_biomass_use([0, 0], unit_ids=['a', 'b'], **kwargs), 0.)
        with self.assertRaises(ValueError):
            bootstrap_household_woody_biomass_use([1, 2], design='unknown', seed=1, iteration=0, stream='survey')


if __name__ == '__main__':
    unittest.main()
