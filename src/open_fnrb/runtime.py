# SPDX-License-Identifier: GPL-3.0-or-later
"""Resolved runtime versions for assessment audit records."""
import importlib
import platform
import sys


def runtime_record():
    result = dict(python=platform.python_version(), executable=sys.executable,
                  platform=platform.platform(), dependencies={})
    for name in ('qgis.core', 'numpy', 'scipy', 'osgeo.gdal', 'shapely', 'pyproj', 'openpyxl'):
        try:
            module = importlib.import_module(name)
            version = (module.Qgis.QGIS_VERSION if name == 'qgis.core' else
                       module.VersionInfo() if name == 'osgeo.gdal' else module.__version__)
            result['dependencies'][name] = dict(version=version, path=module.__file__)
        except ImportError as error:
            result['dependencies'][name] = dict(status='unavailable', message=str(error))
    return result
