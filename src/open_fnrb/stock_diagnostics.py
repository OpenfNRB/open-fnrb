# SPDX-License-Identifier: GPL-3.0-or-later
"""Analytical bounded-cover moments retained independently of MC draws."""
import csv
from .uncertainty import sample_cover


def export_cover_diagnostics(simulation, output):
    if simulation.mode != 'canopy':
        return
    _, moments = sample_cover(simulation.mapped, simulation.scale, simulation.cell_ids,
        seed=0, iteration=0, stream='diagnostic', dependence=simulation.dependence, acknowledged=True)
    with (output/'canopy_uncertainty.csv').open('w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(['record_id', 'source_cell_id', 'mapped_fraction', 'input_normal_sd',
                         'bounded_mean_fraction', 'bounded_sd_fraction', 'expected_mean_shift'])
        for index, cell in enumerate(simulation.cell_ids):
            writer.writerow([index, int(cell), simulation.mapped[index], simulation.scale[index],
                moments['expected_mean'][index], moments['resulting_sd'][index],
                moments['expected_mean_shift'][index]])
