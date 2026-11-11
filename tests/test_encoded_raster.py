# SPDX-License-Identifier: GPL-3.0-or-later
import json
import sys
import tempfile
import unittest
from pathlib import Path
import numpy as np
from osgeo import gdal,osr

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from prepare_encoded_raster import prepare,digest
from open_fnrb.gis_inputs import RasterSource,RasterSpec


class EncodingTests(unittest.TestCase):
    def fixture(self,root,values=None):
        path=root/'raw.tif'
        ds=gdal.GetDriverByName('GTiff').Create(str(path),2,2,1,gdal.GDT_Int16)
        ds.SetGeoTransform((20,0.001,0,-20,0,-0.001))
        crs=osr.SpatialReference();crs.ImportFromEPSG(4326)
        ds.SetProjection(crs.ExportToWkt())
        ds.GetRasterBand(1).WriteArray(np.array(values if values is not None else [[0,100],[-9999,250]],dtype=np.int16))
        ds=None
        config=dict(source='raw.tif',source_sha256=digest(path),source_reference='Synthetic test',encoding_evidence='Invented raw tenths',
                    acknowledged=True,expected_data_type='Int16',expected_gdal_scale=None,expected_gdal_offset=None,
                    raw_nodata=[-9999],multiplier=0.1,offset=0,output_units='t/ha',minimum=0,maximum=None)
        (root/'config.json').write_text(json.dumps(config))
        return config

    def test_decode_preserves_zero_mask_and_grid(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root)
            record=prepare(root/'config.json',root/'output')
            self.assertEqual((record['valid_cells'],record['missing_cells']),(3,1))
            ds=gdal.Open(str(root/'output/decoded.tif'))
            values=ds.ReadAsArray()
            transform=ds.GetGeoTransform()
            scale=ds.GetRasterBand(1).GetScale()
            ds=None
            np.testing.assert_array_equal(values,[[0,10],[-9999,25]])
            self.assertEqual(transform,(20,0.001,0,-20,0,-0.001))
            # GeoTIFF may omit the identity scale; GDAL then returns None.
            self.assertIn(scale,(None,1))
            with RasterSource(RasterSpec(str(root/'output/decoded.tif'),'t/ha','Synthetic','test','2020')) as reader:
                values=reader.read((0,0,2,2))
                self.assertTrue(np.isnan(values[1,0]))
                self.assertEqual(values[1,1],25)  # Assessment intake must not decode a second time.

    def test_stored_scale_change_rejected_and_failure_retained(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=self.fixture(root)
            ds=gdal.Open(str(root/'raw.tif'),gdal.GA_Update)
            ds.GetRasterBand(1).SetScale(0.1);ds=None
            config['source_sha256']=digest(root/'raw.tif')
            (root/'config.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'scale/offset'):
                prepare(root/'config.json',root/'output')
            self.assertEqual(json.loads((root/'output/preparation_record.json').read_text())['status'],'failed')

    def test_invalid_values_not_clipped(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.fixture(root,[[0,100],[-1,250]])
            with self.assertRaisesRegex(ValueError,'physical domain'):
                prepare(root/'config.json',root/'output')
            self.assertEqual(json.loads((root/'output/preparation_record.json').read_text())['status'],'failed')

    def test_wrong_hash_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);config=self.fixture(root)
            config['source_sha256']='0'*64
            (root/'config.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError,'checksum'):
                prepare(root/'config.json',root/'output')
