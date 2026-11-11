# SPDX-License-Identifier: GPL-3.0-or-later
"""Decode a local raster once, preserving its native grid and an audit record."""
import argparse
import hashlib
import json
import math
import platform
from pathlib import Path
import numpy as np
from osgeo import gdal


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda:handle.read(1024*1024),b''):
            value.update(block)
    return value.hexdigest()


def prepare(config_file,output):
    config_file=Path(config_file).resolve()
    config=json.loads(config_file.read_text())
    required={'source','source_sha256','source_reference','encoding_evidence','acknowledged',
              'expected_data_type','expected_gdal_scale','expected_gdal_offset','raw_nodata',
              'multiplier','offset','output_units','minimum','maximum'}
    if set(config)!=required or config['acknowledged'] is not True:
        raise ValueError('Supply the complete explicit encoding contract and acknowledgement.')
    if not all(isinstance(config[k],str) and config[k].strip() for k in ('source_reference','encoding_evidence','output_units')):
        raise ValueError('Source, encoding evidence and output units are required.')
    for key in ('multiplier','offset','minimum'):
        if isinstance(config[key],bool) or not isinstance(config[key],(int,float)) or not math.isfinite(config[key]):
            raise ValueError('Finite numeric encoding values required.')
    if config['multiplier']<=0 or config['minimum']<0:
        raise ValueError('Positive multiplier and nonnegative output domain required.')
    upper=config['maximum']
    if upper is not None and (isinstance(upper,bool) or not isinstance(upper,(int,float)) or not math.isfinite(upper) or upper<config['minimum']):
        raise ValueError('Invalid maximum.')
    if not isinstance(config['raw_nodata'],list) or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in config['raw_nodata']):
        raise ValueError('Raw missing-value overrides must be a list of finite numbers.')
    source_path=(config_file.parent/config['source']).resolve(strict=True)
    output=Path(output).resolve()
    output.mkdir(parents=True,exist_ok=False)
    record=dict(status='running',config=config,source_path=str(source_path),missing_cells=0,valid_cells=0,
                config_sha256=digest(config_file),runtime=dict(python=platform.python_version(),numpy=np.__version__,gdal=gdal.VersionInfo()),
                interpretation='Encoding conversion only; no uncertainty distribution or coverage inference.')
    source=target=None
    try:
        if digest(source_path)!=config['source_sha256']:
            raise ValueError('Source checksum differs from the encoding contract.')
        source=gdal.Open(str(source_path),gdal.GA_ReadOnly)
        if source is None or source.RasterCount!=1:
            raise ValueError('A readable single-band local raster is required.')
        files=source.GetFileList() or [str(source_path)]
        if {Path(p).resolve() for p in files}!={source_path}:
            raise ValueError('Use a self-contained raster; unpinned sidecars or VRT dependencies are unsupported.')
        band=source.GetRasterBand(1)
        if gdal.DataTypeIsComplex(band.DataType):
            raise ValueError('Complex raster values are unsupported.')
        if gdal.GetDataTypeName(band.DataType)!=config['expected_data_type']:
            raise ValueError('Source data type differs from the encoding contract.')
        if band.GetScale()!=config['expected_gdal_scale'] or band.GetOffset()!=config['expected_gdal_offset']:
            raise ValueError('Stored scale/offset differs; possible already-decoded or changed source.')
        # Explicit raw conversion only. Do not multiply by GDAL scale again.
        transform=source.GetGeoTransform(can_return_null=True)
        projection=source.GetProjectionRef()
        if transform is None or not all(math.isfinite(v) for v in transform) or gdal.InvGeoTransform(transform) is None or not projection:
            raise ValueError('Native georeferencing is required.')
        target=gdal.GetDriverByName('GTiff').Create(str(output/'decoded.tif'),source.RasterXSize,source.RasterYSize,1,
                    gdal.GDT_Float64,options=['TILED=YES','COMPRESS=DEFLATE','BIGTIFF=IF_SAFER'])
        if target is None:
            raise ValueError('Could not create decoded output.')
        target.SetGeoTransform(transform)
        target.SetProjection(projection)
        dest=target.GetRasterBand(1)
        dest.SetNoDataValue(-9999)
        dest.SetUnitType(config['output_units'])
        dest.SetScale(1)
        dest.SetOffset(0)
        native_nodata=band.GetNoDataValue()
        record['input_metadata']=dict(shape=[source.RasterYSize,source.RasterXSize],transform=transform,
              crs_wkt=projection,nodata=repr(native_nodata),units=band.GetUnitType(),scale=band.GetScale(),offset=band.GetOffset())
        for row in range(0,source.RasterYSize,256):
            height=min(256,source.RasterYSize-row)
            for col in range(0,source.RasterXSize,256):
                width=min(256,source.RasterXSize-col)
                raw=band.ReadAsArray(col,row,width,height)
                mask=band.GetMaskBand().ReadAsArray(col,row,width,height)
                if raw is None or mask is None:
                    raise ValueError('Raster block read failed.')
                raw=raw.astype(np.float64)
                missing=mask==0
                for value in config['raw_nodata']+([] if native_nodata is None else [native_nodata]):
                    missing |= np.isnan(raw) if math.isnan(value) else raw==value
                if np.any(~np.isfinite(raw[~missing])):
                    raise ValueError('Unmasked nonfinite input value.')
                decoded=raw*config['multiplier']+config['offset']
                valid=decoded[~missing]
                if np.any(~np.isfinite(valid)) or np.any(valid<config['minimum']) or (upper is not None and np.any(valid>upper)):
                    raise ValueError('Decoded values outside the declared physical domain; values were not clipped.')
                decoded[missing]=-9999
                if dest.WriteArray(decoded,col,row)!=0:
                    raise ValueError('Decoded raster block write failed.')
                record['missing_cells']+=int(np.sum(missing))
                record['valid_cells']+=int(valid.size)
        dest.FlushCache()
        target.FlushCache()
        dest=None
        target=None
        band=None
        source=None
        if digest(source_path)!=config['source_sha256']:
            raise ValueError('Source changed during preparation.')
        record.update(status='complete',output_sha256=digest(output/'decoded.tif'),native_grid_preserved=True)
    except Exception as error:
        record.update(status='failed',error_type=type(error).__name__,error=str(error))
        raise
    finally:
        target=None
        source=None
        (output/'preparation_record.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.config,args.output),indent=2))
