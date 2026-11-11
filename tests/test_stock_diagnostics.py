# SPDX-License-Identifier: GPL-3.0-or-later
import csv
import math
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import numpy as np
from open_fnrb.stock_diagnostics import export_cover_diagnostics


class StockDiagnosticsTests(unittest.TestCase):
    def test_boundary_moments_and_shared_source_identity(self):
        simulation=SimpleNamespace(mode='canopy',mapped=np.array([0.,0.,1.]),
            scale=np.array([.1,.1,0.]),cell_ids=np.array([5,5,7]),dependence='shared')
        with tempfile.TemporaryDirectory() as folder:
            export_cover_diagnostics(simulation,Path(folder))
            with (Path(folder)/'canopy_uncertainty.csv').open(newline='') as handle:
                rows=list(csv.DictReader(handle))
        self.assertAlmostEqual(float(rows[0]['bounded_mean_fraction']),.1*math.sqrt(2/math.pi))
        self.assertAlmostEqual(float(rows[0]['bounded_sd_fraction']),.1*math.sqrt(1-2/math.pi))
        self.assertEqual(rows[0]['source_cell_id'],rows[1]['source_cell_id'])
        self.assertEqual(float(rows[2]['bounded_mean_fraction']),1.)
        self.assertEqual(float(rows[2]['bounded_sd_fraction']),0.)
