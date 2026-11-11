# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
import numpy as np
from pyproj import Transformer
from shapely.geometry import box, Polygon, MultiPolygon
from shapely.ops import transform
from shapely import segmentize
from open_fnrb.area import WGS84Area
from open_fnrb.preparation import prepare_native_grid, allocate_households


class AreaTests(unittest.TestCase):
    def setUp(self):
        self.measure = WGS84Area()
        self.project = Transformer.from_crs(4326,6933,always_xy=True).transform

    def test_rectangles_match_independent_equal_area_projection(self):
        for latitude in (-70,-30,0,30,70):
            g = box(28,latitude,28.01,latitude+.01)
            expected = transform(self.project,g).area
            self.assertAlmostEqual(self.measure(g)/expected,1,places=8)

    def test_sloped_edges_match_densified_equal_area_projection(self):
        g = Polygon([(20,-30),(30,-20),(32,-32),(20,-30)])
        expected = transform(self.project,segmentize(g,.001)).area
        self.assertAlmostEqual(self.measure(g)/expected,1,places=8)

    def test_split_additivity_and_holes(self):
        outer = box(28,-25,28.01,-24.99)
        hole = box(28.002,-24.998,28.004,-24.996)
        g = outer.difference(hole)
        a = g.intersection(box(27,-26,28.005,-24))
        b = g.difference(a)
        self.assertAlmostEqual((self.measure(a)+self.measure(b))/self.measure(g),1,places=9)
        self.assertAlmostEqual(self.measure(g),self.measure(outer)-self.measure(hole),places=5)
        self.assertAlmostEqual(self.measure(MultiPolygon([a,b]))/self.measure(g),1,places=9)

    def test_native_grid_split_identity_and_area(self):
        boundary = box(28,-25.01,28.02,-25)
        split = 28.005
        p = prepare_native_grid(stock=[[20,30]],uncertainty=[[2,3]],
            transform=(28,.01,0,-25,0,-.01),boundary=boundary,
            zones=[(0,box(28,-25.01,split,-25)),(1,box(split,-25.01,28.02,-25))],
            eligibility=[boundary],exclusions=[],area_crs_confirmed=True,area_measure=self.measure)
        self.assertEqual(p.source_cell_ids.tolist(),[0,0,1])
        self.assertAlmostEqual(sum(p.area_ha)*10000/self.measure(boundary),1,places=9)
        self.assertEqual(p.mapped_stock.tolist(),[20,20,30])

    def test_households_use_surface_area_not_square_degrees(self):
        full = box(20,-60,21,0)
        boundary = box(20,-30,21,0)
        rows = allocate_households(administrative_areas=[('A',100,full)],
            built_up_support=[full],boundary=boundary,area_measure=self.measure)
        self.assertAlmostEqual(rows[0]['households_allocated'],100*self.measure(boundary)/self.measure(full))
        self.assertGreater(rows[0]['households_allocated'],50)

    def test_reject_ambiguous_wrap_and_invalid_coordinates(self):
        for g in [box(-179,-20,179,-19),box(181,-20,182,-19),box(20,91,21,92)]:
            with self.assertRaises(ValueError):
                self.measure(g)
