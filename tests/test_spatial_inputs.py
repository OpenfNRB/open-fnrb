# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
from pathlib import Path
import unittest
import numpy as np
from osgeo import gdal
from shapely.geometry import box
from shapely.ops import unary_union
from open_fnrb.gis_inputs import RasterSpec, spatial_reference, prepare_raster_pair
from open_fnrb.spatial_inputs import (TransformSettings,transform_polygon,
                                     categorical_support,households_from_raster)
from open_fnrb.area import PlanarArea,WGS84Area


class SpatialInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.crs = spatial_reference('EPSG:6933')

    def tearDown(self):
        self.temp.cleanup()

    def raster(self,name,values,units='class_code',step=50):
        a = np.array(values,float)
        path = Path(self.temp.name)/(name+'.tif')
        ds = gdal.GetDriverByName('GTiff').Create(str(path),a.shape[1],a.shape[0],1,gdal.GDT_Float64)
        ds.SetProjection(self.crs.ExportToWkt()); ds.SetGeoTransform((0,step,0,100,0,-step))
        band = ds.GetRasterBand(1); band.WriteArray(a); band.SetNoDataValue(-9999)
        band.SetUnitType(units); band = None; ds = None
        return RasterSpec(str(path),units,'synthetic','1','2026-01-01')

    def support(self,values,**overrides):
        args=dict(spec=self.raster('classes',values),domain=box(0,0,100,100),
                  expected_crs=self.crs,rules={1:True,2:False},area_measure=PlanarArea())
        args.update(overrides)
        return categorical_support(**args)

    def test_all_classes_retained_and_selection_explicit(self):
        result = self.support([[1,2],[2,1]])
        self.assertEqual(len(result.cells),4)
        self.assertEqual([c['source_cell_id'] for c in result.cells],[0,1,2,3])
        self.assertEqual(unary_union(result.selected).area,5000)
        self.assertEqual(result.audit['area_by_class_m2'],{'1':5000,'2':5000})

    def test_categorical_block_sizes_preserve_ids_geometry_and_areas(self):
        reference=self.support([[1,2],[2,1]],maximum_block_cells=4)
        for limit in (1,2,3):
            result=self.support([[1,2],[2,1]],maximum_block_cells=limit)
            self.assertEqual(result.audit['area_by_class_m2'],reference.audit['area_by_class_m2'])
            self.assertEqual([(c['source_cell_id'],c['class_code'],c['geometry'].wkb) for c in result.cells],
                [(c['source_cell_id'],c['class_code'],c['geometry'].wkb) for c in reference.cells])

    def test_unknown_missing_noninteger_classes_fail(self):
        for value,pattern in [(3,'No explicit rule'),(-9999,'Missing'),(1.5,'noninteger')]:
            with self.assertRaisesRegex(ValueError,pattern):
                self.support([[1,value],[2,1]])
        with self.assertRaisesRegex(ValueError,'boolean'):
            self.support([[1,2],[2,1]],rules={1:1,2:0})

    def test_fine_class_grid_splits_coarse_stock_without_resampling(self):
        support = self.support([[1,2],[2,1]])
        stock = self.raster('stock',[[20]],'t_dry_matter/ha',100)
        sd = self.raster('sd',[[2]],'t_dry_matter/ha',100)
        boundary = box(0,0,100,100)
        p = prepare_raster_pair(stock_spec=stock,uncertainty_spec=sd,stock_mode='agb',
            boundary=boundary,zones=[(0,boundary)],eligibility=support.selected,exclusions=[],
            distortion_acknowledged=True,uncertainty_interpretation='standard_deviation')
        self.assertEqual(p.source_cell_ids.tolist(),[0])
        self.assertAlmostEqual(p.area_ha.sum(),.5)
        self.assertEqual(p.mapped_stock.tolist(),[20])

    def test_missing_outside_harvest_still_blocks_denominator(self):
        spec = self.raster('built_up',[[1,1],[1,-9999]])
        with self.assertRaisesRegex(ValueError,'source cell 3'):
            households_from_raster(spec=spec,administrative_areas=[('A',100,box(0,0,100,100))],
                boundary=box(0,50,100,100),expected_crs=self.crs,rules={1:True},area_measure=PlanarArea())

    def test_full_denominator_allocation(self):
        spec = self.raster('built_up',[[1,1],[1,2]])
        rows,support = households_from_raster(spec=spec,
            administrative_areas=[('A',90,box(0,0,100,100))],boundary=box(0,50,100,100),
            expected_crs=self.crs,rules={1:True,2:False},area_measure=PlanarArea())
        self.assertEqual(rows[0]['households_allocated'],60)
        self.assertEqual(rows[0]['full_support_m2'],7500)

    def test_transformation_preserves_area_and_records_operation(self):
        g = box(28,-25,28.01,-24.99)
        result,audit = transform_polygon(g,source_crs=4326,target_crs=6933,
            settings=TransformSettings(.01,.001,0))
        self.assertAlmostEqual(result.area/WGS84Area()(g),1,places=8)
        self.assertEqual(audit['accuracy_metres'],0)
        self.assertIn('proj',audit['operation'])
        recovered,_ = transform_polygon(result,source_crs=6933,target_crs=4326,
            settings=TransformSettings(100,.00000001,0))
        self.assertLess(recovered.hausdorff_distance(g),1e-7)

    def test_curved_transformation_and_tolerance_failure(self):
        g = box(26,-30,30,-24)
        result,audit = transform_polygon(g,source_crs=4326,target_crs=32735,
            settings=TransformSettings(2,1,0))
        self.assertGreater(audit['refinements'],1)
        self.assertLessEqual(audit['refinement_distance'],1)
        with self.assertRaisesRegex(ValueError,'refinement tolerance'):
            transform_polygon(g,source_crs=4326,target_crs=32735,
                settings=TransformSettings(2,1e-10,0,maximum_refinements=1))

    def test_missing_coverage_and_wrong_crs(self):
        with self.assertRaisesRegex(ValueError,'cover'):
            self.support([[1]],domain=box(0,0,100,100))
        with self.assertRaisesRegex(ValueError,'CRS'):
            self.support([[1,2],[2,1]],expected_crs=spatial_reference('EPSG:4326'))

    def test_geographic_classes_projected_support_and_household_denominator(self):
        from pyproj import Transformer
        spec=self.raster('geographic',[[1,1],[1,2]])
        ds=gdal.Open(spec.path,gdal.GA_Update)
        ds.SetProjection(spatial_reference('EPSG:4326').ExportToWkt())
        ds.SetGeoTransform((28,.005,0,-24.99,0,-.005));ds=None
        settings={'domain_to_source':TransformSettings(500,1e-9,0),
                  'cells_to_stock':TransformSettings(.005,.0001,0)}
        transform=Transformer.from_crs(4326,6933,always_xy=True)
        x0,y0=transform.transform(28,-25);x1,y1=transform.transform(28.01,-24.99)
        domain=box(x0,y0,x1,y1)
        support=categorical_support(spec=spec,domain=domain,expected_crs=self.crs,
            rules={1:True,2:False},area_measure=PlanarArea(),transformation_settings=settings)
        self.assertEqual([c['source_cell_id'] for c in support.cells],[0,1,2,3])
        self.assertAlmostEqual(sum(c['area_m2'] for c in support.cells)/domain.area,1,places=9)
        self.assertEqual(len(support.audit['cell_transformations']),4)
        rows,_=households_from_raster(spec=spec,administrative_areas=[('A',90,domain)],
            boundary=box(x0,y0,(x0+x1)/2,y1),expected_crs=self.crs,rules={1:True,2:False},
            area_measure=PlanarArea(),transformation_settings=settings)
        expected=90*domain.area/2/support.audit['area_by_class_m2']['1']
        self.assertAlmostEqual(rows[0]['households_allocated'],expected,places=7)
        with self.assertRaisesRegex(ValueError,'coverage'):
            categorical_support(spec=spec,domain=box(x0,y0,x1+100,y1),expected_crs=self.crs,
                rules={1:True,2:False},area_measure=PlanarArea(),transformation_settings=settings)
