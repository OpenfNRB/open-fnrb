# SPDX-License-Identifier: GPL-3.0-or-later
"""Launch Open fNRB from a source package using the QGIS Python environment."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from open_fnrb.__main__ import main

if __name__=='__main__':
    sys.exit(main())
