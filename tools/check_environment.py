# SPDX-License-Identifier: GPL-3.0-or-later
"""Report the numerical/GIS environment without installing or changing it."""
import argparse
import importlib
import json
from pathlib import Path
import platform
import sys


def inspect_environment():
    result=dict(python=platform.python_version(),executable=sys.executable,platform=platform.platform(),dependencies={})
    for name in ('qgis.core','numpy','scipy','osgeo.gdal','shapely','pyproj','openpyxl'):
        try:
            module=importlib.import_module(name)
            version=(module.Qgis.QGIS_VERSION if name=='qgis.core' else
                     module.VersionInfo() if name=='osgeo.gdal' else module.__version__)
            result['dependencies'][name]=dict(status='available',version=version,path=module.__file__)
        except Exception as error:
            result['dependencies'][name]=dict(status='failed',error_type=type(error).__name__,message=str(error))
    result['status']='passed' if all(v['status']=='available' for v in result['dependencies'].values()) else 'failed'
    result['meaning']='Import/version check only; run installation checks separately. No dependencies were installed or changed.'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output')
    args=parser.parse_args();path=Path(args.output).resolve() if args.output else None
    if path is not None:
        with path.open('x',encoding='utf-8') as handle:json.dump({'status':'checking'},handle)
    result=inspect_environment();text=json.dumps(result,indent=2)
    if path is not None:path.write_text(text,encoding='utf-8')
    print(text);sys.exit(0 if result['status']=='passed' else 1)
