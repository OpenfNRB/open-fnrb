# SPDX-License-Identifier: GPL-3.0-or-later
"""Export in-area missing-stock cells as diagnostic TIFF and shapefile."""
import argparse
import json
from pathlib import Path
import numpy as np
from osgeo import gdal,ogr,osr
from prepare_encoded_raster import digest


def export(stock,support,output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    record=dict(status='running',interpretation='Gap diagnostic only: 1 denotes missing stock at a cell centre inside the assessment support. Background 0 is not a stock value. No gap filling.',inputs={'stock_sha256':digest(stock),'support_sha256':digest(support)})
    source=country=mask=vector=None
    try:
        with gdal.ExceptionMgr():
            source=gdal.Open(str(stock));country=gdal.Open(str(support))
            if (source.RasterXSize,source.RasterYSize,source.GetGeoTransform(),source.GetProjection())!=(country.RasterXSize,country.RasterYSize,country.GetGeoTransform(),country.GetProjection()):raise ValueError('Support grid differs from stock.')
            mask=gdal.GetDriverByName('GTiff').Create(str(output/'missing_stock.tif'),source.RasterXSize,source.RasterYSize,1,gdal.GDT_Byte,options=['TILED=YES','COMPRESS=DEFLATE','BIGTIFF=IF_SAFER'])
            mask.SetGeoTransform(source.GetGeoTransform());mask.SetProjection(source.GetProjection())
            band=mask.GetRasterBand(1);band.SetNoDataValue(0);count=0
            for y in range(0,source.RasterYSize,1024):
                for x in range(0,source.RasterXSize,1024):
                    w=min(1024,source.RasterXSize-x);h=min(1024,source.RasterYSize-y)
                    values=source.ReadAsArray(x,y,w,h)
                    missing=((values==source.GetRasterBand(1).GetNoDataValue())|~np.isfinite(values))&(country.GetRasterBand(1).ReadAsArray(x,y,w,h)>0)
                    band.WriteArray(missing.astype(np.uint8),x,y);count+=int(missing.sum())
            mask.FlushCache()
            vector=ogr.GetDriverByName('ESRI Shapefile').CreateDataSource(str(output/'missing_stock.shp'))
            crs=osr.SpatialReference(wkt=source.GetProjection())
            layer=vector.CreateLayer('missing_stock',crs,ogr.wkbPolygon,options=['ENCODING=UTF-8'])
            layer.CreateField(ogr.FieldDefn('gap',ogr.OFTInteger))
            gdal.Polygonize(band,band,layer,0)
            record.update(status='complete',missing_cells=count,polygon_count=layer.GetFeatureCount())
            layer=None;vector=None;band=None;mask=None;source=None;country=None
            record['files']=[dict(file=p.name,sha256=digest(p),bytes=p.stat().st_size) for p in sorted(output.iterdir()) if p.is_file()]
    except Exception as error:
        record.update(status='failed',error_type=type(error).__name__,error=str(error));raise
    finally:
        source=country=mask=vector=None
        (output/'gap_record.json').write_text(json.dumps(record,indent=2))
    return record


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('stock','support','output'):parser.add_argument('--'+name,required=True)
    args=parser.parse_args();print(json.dumps(export(args.stock,args.support,args.output),indent=2))
