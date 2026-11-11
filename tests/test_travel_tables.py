# SPDX-License-Identifier: GPL-3.0-or-later
import csv
import math
from pathlib import Path
import tempfile
import unittest
from shapely.geometry import Point
from pyproj import Geod
from open_fnrb.travel import collection_boundary
from open_fnrb.tables import SCHEMAS,read_table,validate_rows


class TravelTests(unittest.TestCase):
    def run_buffer(self,**updates):
        args=dict(points=[('A',Point(0,0))],crs=6933,round_trip_hours=2,
                  travelling_share=.5,speed_kmh=4,edge_tolerance_metres=1,distortion_acknowledged=True)
        args.update(updates)
        return collection_boundary(**args)

    def test_projected_known_radius_and_area(self):
        b = self.run_buffer()
        self.assertEqual(b.audit['radius_metres'],2000)
        self.assertLess(abs(b.geometry.area/(math.pi*2000**2)-1),.002)
        self.assertLessEqual(b.audit['points'][0]['sampled_edge_error_metres'],1)

    def test_overlapping_and_coincident_points_dissolve(self):
        one = self.run_buffer()
        two = self.run_buffer(points=[('A',Point(0,0)),('B',Point(0,0))])
        self.assertAlmostEqual(one.geometry.area,two.geometry.area)
        self.assertAlmostEqual(two.audit['overlap_area_m2'],one.geometry.area)
        overlap = self.run_buffer(points=[('A',Point(0,0)),('B',Point(1000,0))])
        self.assertLess(overlap.geometry.area,2*one.geometry.area)

    def test_geographic_radius(self):
        b = self.run_buffer(points=[('A',Point(28,-25))],crs=4326,distortion_acknowledged=False)
        geod = Geod(ellps='WGS84')
        for lon,lat in list(b.geometry.exterior.coords)[::10]:
            self.assertAlmostEqual(geod.inv(28,-25,lon,lat)[2],2000,places=5)
        self.assertGreater(b.audit['union_area_m2'],12_000_000)

    def test_invalid_inputs_fail(self):
        for update in [dict(points=[]),dict(points=[('A',Point(0,0)),('A',Point(1,0))]),
                       dict(travelling_share=50),dict(edge_tolerance_metres=2000),
                       dict(distortion_acknowledged=False)]:
            with self.assertRaises(ValueError): self.run_buffer(**update)


class TableTests(unittest.TestCase):
    def row(self,**changes):
        r=dict(assessment_id='synthetic',mode='annual_total',estimated_annual_harvest_tonnes=0,
               households='',woody_biomass_use_tonnes_per_household_year='',source='synthetic')
        r.update(changes)
        return r

    def test_zero_missing_and_competing_routes(self):
        self.assertEqual(validate_rows('Harvest',[self.row()])[0]['estimated_annual_harvest_tonnes'],0)
        for row in [self.row(estimated_annual_harvest_tonnes=''),self.row(households=10),
                    self.row(estimated_annual_harvest_tonnes='=1+1'),self.row(estimated_annual_harvest_tonnes='NaN')]:
            with self.assertRaises(ValueError): validate_rows('Harvest',[row])
        row = self.row(mode='household_count',estimated_annual_harvest_tonnes='',households=10,
                       woody_biomass_use_tonnes_per_household_year=2)
        self.assertEqual(validate_rows('Harvest',[row])[0]['households'],10)

    def test_duplicate_identifiers_and_explicit_boolean(self):
        with self.assertRaises(ValueError): validate_rows('Harvest',[self.row(),self.row()])
        self.assertFalse(validate_rows('Eligibility',[dict(class_code='20',eligible='FALSE',source='synthetic')])[0]['eligible'])
        with self.assertRaises(ValueError):
            validate_rows('Eligibility',[dict(class_code=20,eligible=0,source='synthetic')])

    def test_csv_reader_and_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'harvest.csv'
            with p.open('w',newline='',encoding='utf-8') as f:
                writer=csv.DictWriter(f,fieldnames=SCHEMAS['Harvest']);writer.writeheader();writer.writerow(self.row())
            self.assertEqual(read_table(p,'Harvest')[0]['estimated_annual_harvest_tonnes'],0)
            p.write_text('wrong,header\n1,2\n')
            with self.assertRaises(ValueError): read_table(p,'Harvest')

    def test_shipped_workbook_headers_and_blank_rows(self):
        from openpyxl import load_workbook
        p=Path(__file__).resolve().parents[1]/'templates'/'Open_fNRB_input_template.xlsx'
        wb=load_workbook(p,read_only=True,data_only=False)
        try:
            for name,fields in SCHEMAS.items():
                self.assertEqual(list(next(wb[name].iter_rows(values_only=True))),fields)
                with self.assertRaisesRegex(ValueError,'no completed input rows'): read_table(p,name)
        finally: wb.close()

    def test_parameter_source_dependence_consistency(self):
        r=dict(zone_id='A',increment_mean=2,increment_sd=.2,capacity_mean=100,capacity_sd=10,
               increment_group='g',capacity_group='k',source='synthetic')
        self.assertEqual(len(validate_rows('Parameters',[r,dict(r,zone_id='B')])),2)
        with self.assertRaisesRegex(ValueError,'identical moments'):
            validate_rows('Parameters',[r,dict(r,zone_id='B',capacity_mean=120)])
