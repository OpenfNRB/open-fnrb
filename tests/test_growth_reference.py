# SPDX-License-Identifier: GPL-3.0-or-later
"""Compare the annual closed form with an independent time-domain solver."""
import unittest
import numpy as np
from scipy.integrate import solve_ivp
from open_fnrb.growth import annual_logistic


class GrowthReferenceTests(unittest.TestCase):
    def test_against_independent_integration_across_harvest_regimes(self):
        for b0 in (2.,20.,50.,100.):
            for h in (0.,2.,4.,10.,150.):
                with self.subTest(stock=b0,harvest=h):
                    k,peak=100.,4.
                    def rhs(t,y):
                        growth=4*peak*y[0]/k*(1-y[0]/k)
                        return [growth-h,growth]
                    def exhausted(t,y): return y[0]
                    exhausted.terminal=True
                    exhausted.direction=-1
                    numerical=solve_ivp(rhs,(0.,1.),[b0,0.],events=exhausted,
                        rtol=1e-11,atol=1e-12,max_step=.01)
                    self.assertTrue(numerical.success)
                    actual=annual_logistic(b0,k,peak,h)
                    self.assertAlmostEqual(float(actual.end),max(0.,numerical.y[0,-1]),delta=2e-8)
                    self.assertAlmostEqual(float(actual.regeneration),numerical.y[1,-1],delta=2e-8)
                    self.assertAlmostEqual(float(actual.realised_harvest),h*numerical.t[-1],delta=2e-8)

    def test_capacity_is_zero_growth_without_harvest(self):
        actual=annual_logistic(np.array([0.,100.]),100.,4.,0.)
        np.testing.assert_array_equal(actual.regeneration,[0.,0.])
