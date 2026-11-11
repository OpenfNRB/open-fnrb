# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
from pathlib import Path
import unittest
import numpy as np
from shapely.geometry import box
from open_fnrb.classification import load_classification_matrix,prepare_classification_support,assess_classified_year
from open_fnrb.annual import assess_year
from open_fnrb.spatial_inputs import categorical_support
from open_fnrb.gis_inputs import RasterSpec,spatial_reference
from open_fnrb.area import PlanarArea
from test_workflow import example


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        example.create(self.root/'inputs')

    def tearDown(self):self.temp.cleanup()

    def matrix(self,counts):
        path=self.root/'matrix.csv'
        path.write_text('mapped_class,reference_class,count\n'+''.join(f'{a},{b},{counts[a-1][b-1]}\n' for a in (1,2) for b in (1,2)))
        return load_classification_matrix(path,source_id='Invented validation evidence',
            orientation='mapped_rows_reference_columns',dependence='independent_native_cells',acknowledged=True)

    def support(self,model):
        from osgeo import gdal
        folder=self.root/'inputs'
        ds=gdal.Open(str(folder/'classes.tif'),gdal.GA_Update)
        ds.GetRasterBand(1).WriteArray(np.array([[1,2],[1,2]]));ds=None
        def spec(name,units):return RasterSpec(str(folder/name),units,'Invented','1','2026-01-01')
        boundary=box(0,0,200,200)
        classes=categorical_support(spec=spec('classes.tif','class_code'),domain=boundary,
            expected_crs=spatial_reference('EPSG:6933'),rules={1:True,2:False},area_measure=PlanarArea())
        return prepare_classification_support(classes=classes,model=model,rules={1:True,2:False},area_measure=PlanarArea(),
            stock_spec=spec('stock.tif','t_dry_matter/ha'),uncertainty_spec=spec('uncertainty.tif','t_dry_matter/ha'),
            stock_mode='agb',boundary=boundary,zones=[(0,box(0,0,200,50)),(1,box(0,50,200,200))],
            exclusions=[box(175,0,200,200)],distortion_acknowledged=True,uncertainty_interpretation='standard_deviation')

    def calculate(self,support,model):
        n=len(support.prepared.area_ha)
        return assess_classified_year(support,model,{1:True,2:False},seed=5,iteration=0,stock_mode='agb',
            mapped_stock=np.full(n,20.),reference_capacity=np.full(n,100.),peak_increment=np.full(n,2.),prescribed_annual_harvest_tonnes=10)

    def test_class_switch_can_add_and_remove_resource_and_keep_exclusions(self):
        model=self.matrix([[0,1],[1,0]]);support=self.support(model)
        self.assertAlmostEqual(support.prepared.area_ha.sum(),3.5)
        self.assertAlmostEqual(support.prepared.area_ha[support.nominal_eligible].sum(),2)
        result,draw=self.calculate(support,model)
        self.assertAlmostEqual(result.summary['eligible_area_ha'],1.5)
        expected=assess_year([1.5],[20],[100],[2],10)
        self.assertAlmostEqual(result.summary['fnrb'],expected.summary['fnrb'])
        self.assertTrue(all(support.mapped_classes[i]==2 for i in draw['record_indices']))
        for identity in set(support.class_cell_ids):
            sampled=np.array(draw['sampled_classes'])[support.class_cell_ids==identity]
            self.assertEqual(len(set(sampled)),1)

    def test_all_ineligible_draw_retains_harvest(self):
        model=self.matrix([[0,1],[0,1]]);support=self.support(model)
        result,draw=self.calculate(support,model)
        self.assertEqual(result.summary['fnrb'],1)
        self.assertEqual(result.summary['unrealised_harvest_tonnes'],10)
        self.assertEqual(draw['record_indices'],[])

    def test_identity_matrix_matches_nominal_eligible_area(self):
        model=self.matrix([[1,0],[0,1]]);support=self.support(model)
        result,_=self.calculate(support,model)
        self.assertEqual(result.summary['eligible_area_ha'],2)
        self.assertEqual(support.prepared.area_ha.sum(),2)

    def test_matrix_must_be_complete_and_explicitly_interpreted(self):
        self.matrix([[1,0],[0,1]])
        args=dict(source_id='evidence',orientation='mapped_rows_reference_columns',dependence='independent_native_cells',acknowledged=True)
        path=self.root/'matrix.csv'
        with self.assertRaisesRegex(ValueError,'Acknowledge'):
            load_classification_matrix(path,**dict(args,orientation='reference_rows'))
        path.write_text('mapped_class,reference_class,count\n1,1,3\n1,2,0\n2,2,3\n')
        with self.assertRaisesRegex(ValueError,'every class pair'):load_classification_matrix(path,**args)
        with self.assertRaisesRegex(ValueError,'Invalid classification'):self.matrix([[0,0],[1,1]])

    def test_large_finite_counts_normalize_without_overflow(self):
        model=self.matrix([[1e308,1e308],[1e308,1e308]])
        ids=np.arange(1000,dtype=np.int64);mapped=np.ones(1000,dtype=np.int64)
        sampled=model.draw(mapped,ids,12,3)
        self.assertGreater(np.count_nonzero(sampled==1),400)
        self.assertLess(np.count_nonzero(sampled==1),600)
