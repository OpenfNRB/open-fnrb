# SPDX-License-Identifier: GPL-3.0-or-later
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
from osgeo import gdal,ogr,osr
from shapely.geometry import box

from open_fnrb.gis_inputs import (RasterSpec,RasterSource,prepare_raster_pair,
    read_polygons,spatial_reference,require_aligned,require_area_crs)
from open_fnrb.area import WGS84Area
from open_fnrb.spatial_inputs import TransformSettings


class GISInputTests(unittest.TestCase):
    def test_block_limits_preserve_native_records_and_bound_reads(self):
        boundary=box(10,10,390,290)
        args=dict(stock_spec=self.raster('blocked_stock',np.arange(12).reshape(3,4)+20),
            uncertainty_spec=self.raster('blocked_sd',np.full((3,4),2)),stock_mode='agb',
            boundary=boundary,zones=[(0,box(0,0,150,300)),(1,box(150,0,400,300))],
            eligibility=[boundary],exclusions=[],distortion_acknowledged=True,uncertainty_interpretation='standard_deviation')
        reference=prepare_raster_pair(**args,maximum_block_cells=100)
        reader=RasterSource.read
        for limit in (1,3,5,8):
            reads=[]
            def recorded(source,window):
                reads.append(window[2]*window[3]);return reader(source,window)
            with patch.object(RasterSource,'read',recorded):
                actual=prepare_raster_pair(**args,maximum_block_cells=limit)
            self.assertLessEqual(max(reads),limit)
            for name in ('area_ha','source_cell_ids','zone_index','mapped_stock','stock_scale'):
                np.testing.assert_array_equal(getattr(actual,name),getattr(reference,name))
            self.assertEqual([g.wkb for g in actual.geometries],[g.wkb for g in reference.geometries])
        bad=self.raster('bad_last',[[2]*4,[2]*4,[2,2,2,-9999]],nodata=-9999)
        with self.assertRaisesRegex(ValueError,'source cell 11'):
            prepare_raster_pair(**dict(args,uncertainty_spec=bad),maximum_block_cells=3)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.crs = spatial_reference('EPSG:6933')

    def tearDown(self):
        self.temp.cleanup()

    def raster(self,name,values,units='t_dry_matter/ha',transform=(0,100,0,300,0,-100),
               nodata=None,scale=None,offset=None,epsg=6933):
        values = np.array(values,float)
        path = self.root/(name+'.tif')
        ds = gdal.GetDriverByName('GTiff').Create(str(path),values.shape[1],values.shape[0],1,gdal.GDT_Float64)
        crs = osr.SpatialReference(); crs.ImportFromEPSG(epsg)
        ds.SetProjection(crs.ExportToWkt()); ds.SetGeoTransform(transform)
        band = ds.GetRasterBand(1); band.WriteArray(values); band.SetUnitType(units)
        if nodata is not None: band.SetNoDataValue(nodata)
        if scale is not None: band.SetScale(scale)
        if offset is not None: band.SetOffset(offset)
        band = None; ds = None
        return RasterSpec(str(path),units,'synthetic','1','2026-01-01')

    def pair(self,**overrides):
        args = dict(stock_spec=self.raster('stock',np.full((3,4),20)),
                    uncertainty_spec=self.raster('sd',np.full((3,4),2)),stock_mode='agb',
                    boundary=box(110,10,190,90),zones=[(0,box(0,0,400,300))],
                    eligibility=[box(0,0,400,300)],exclusions=[],distortion_acknowledged=True,
                    uncertainty_interpretation='standard_deviation')
        args.update(overrides)
        return prepare_raster_pair(**args)

    def test_cropped_window_global_id_and_fingerprints(self):
        p = self.pair()
        self.assertEqual(p.source_cell_ids.tolist(),[9])
        self.assertAlmostEqual(p.area_ha.sum(),.64)
        self.assertEqual(p.audit['native_window'],[1,2,1,1])
        self.assertEqual(p.audit['source_shape'],[3,4])
        self.assertEqual(len(p.audit['stock_source']['files'][0]['sha256']),64)

    def test_encoded_nodata_before_scale_offset(self):
        spec = self.raster('encoded',[[0,10,-9999]],scale=2,offset=1,nodata=-9999)
        with RasterSource(spec) as source:
            actual = source.read((0,0,3,1))
            np.testing.assert_allclose(actual[0,:2],[1,21])
            self.assertTrue(np.isnan(actual[0,2]))

    def test_missing_source_cell_is_an_error(self):
        values = np.full((3,4),20.); values[2,1] = -9999
        spec = self.raster('missing',values,nodata=-9999)
        with self.assertRaisesRegex(ValueError,'source cell 9'):
            self.pair(stock_spec=spec)

    def test_misalignment_and_conflicting_units(self):
        a = self.raster('a',[[1,2]])
        b = self.raster('b',[[1,2]],transform=(1,100,0,300,0,-100))
        with RasterSource(a) as first,RasterSource(b) as second:
            with self.assertRaisesRegex(ValueError,'native grid'):
                require_aligned(first,second)
        with self.assertRaisesRegex(ValueError,'units conflict'):
            RasterSource(RasterSpec(a.path,'percent','synthetic','1','2026-01-01'))

    def test_canopy_percent_conversion_and_interpretation(self):
        stock = self.raster('cover',np.full((3,4),50),'percent')
        error = self.raster('cover_error',np.full((3,4),10),'percent')
        p = self.pair(stock_spec=stock,uncertainty_spec=error,stock_mode='canopy',
                      uncertainty_interpretation='pre_truncation_normal_scale')
        np.testing.assert_allclose(p.mapped_stock,[.5]); np.testing.assert_allclose(p.stock_scale,[.1])
        with self.assertRaisesRegex(ValueError,'interpretation'):
            self.pair(uncertainty_interpretation='standard_error')

    def test_geographic_not_misinterpreted_as_planar(self):
        with self.assertRaisesRegex(ValueError,'geographic'):
            require_area_crs(spatial_reference('EPSG:4326'),distortion_acknowledged=True)
        with self.assertRaisesRegex(ValueError,'acknowledged'):
            require_area_crs(self.crs,distortion_acknowledged=False)

    def test_geographic_file_pair_preserves_native_grid(self):
        affine = (28,.01,0,-25,0,-.01)
        stock = self.raster('geo_stock',[[20,40]],transform=affine,epsg=4326)
        error = self.raster('geo_error',[[2,4]],transform=affine,epsg=4326)
        boundary = box(28.002,-25.009,28.015,-25.001)
        p = prepare_raster_pair(stock_spec=stock,uncertainty_spec=error,stock_mode='agb',
            boundary=boundary,zones=[(0,boundary)],eligibility=[boundary],exclusions=[],
            distortion_acknowledged=False,uncertainty_interpretation='standard_deviation')
        self.assertEqual(p.source_cell_ids.tolist(),[0,1])
        self.assertEqual(p.mapped_stock.tolist(),[20,40])
        self.assertEqual(p.audit['stock_source']['transform'],list(affine))
        self.assertEqual(p.audit['area_measurement'],WGS84Area.method)
        self.assertAlmostEqual(sum(p.area_ha)*10000/WGS84Area()(boundary),1,places=9)

    def test_coverage_and_window_bounds(self):
        spec = self.raster('small',[[1,2]])
        with RasterSource(spec) as source:
            with self.assertRaisesRegex(ValueError,'cover'):
                source.window_for(box(-10,200,10,300))
            with self.assertRaisesRegex(ValueError,'window'):
                source.read((0,0,3,1))

    def test_polygon_reader_fields_and_crs(self):
        path = self.root/'zones.gpkg'
        ds = ogr.GetDriverByName('GPKG').CreateDataSource(str(path))
        layer = ds.CreateLayer('zones',self.crs,ogr.wkbPolygon)
        layer.CreateField(ogr.FieldDefn('zone',ogr.OFTInteger))
        feature = ogr.Feature(layer.GetLayerDefn()); feature.SetField('zone',2)
        feature.SetGeometry(ogr.CreateGeometryFromWkt(box(0,0,100,100).wkt))
        layer.CreateFeature(feature)
        feature = None; layer = None; ds = None
        rows = read_polygons(path,expected_crs=self.crs,required_fields=('zone',))
        self.assertEqual(rows[0]['fields']['zone'],2)
        self.assertEqual(rows[0]['geometry'].area,10000)
        with self.assertRaisesRegex(ValueError,'CRS differ'):
            read_polygons(path,expected_crs=spatial_reference('EPSG:4326'))
        with self.assertRaisesRegex(ValueError,'Missing required'):
            read_polygons(path,expected_crs=self.crs,required_fields=('missing',))
        transformed = read_polygons(path,expected_crs=spatial_reference('EPSG:4326'),
                required_fields=('zone',),transformation_settings=TransformSettings(50,1e-8,0))
        self.assertEqual(transformed[0]['fields']['zone'],2)
        self.assertIsNotNone(transformed[0]['transformation'])
        self.assertAlmostEqual(WGS84Area()(transformed[0]['geometry'])/10000,1,places=7)


if __name__ == '__main__':
    unittest.main()
