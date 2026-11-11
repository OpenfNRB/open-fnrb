# SPDX-License-Identifier: GPL-3.0-or-later
"""Restart, failure and precision-limit tests with small synthetic runs."""
from pathlib import Path
import json
import tempfile
import unittest
import numpy as np
from open_fnrb.monte_carlo import Draw, Settings, precision, run
from open_fnrb.uncertainty import generator


def constant(seed, iteration):
    return Draw(dict(fnrb=.4, prescribed_annual_harvest=10.), dict(value=.4))


def variable(seed, iteration):
    value = float(generator(seed, iteration, 'test').uniform())
    return Draw(dict(fnrb=value, prescribed_annual_harvest=10.), dict(value=value))


class MonteCarloTests(unittest.TestCase):
    def args(self, output, target=.005):
        return dict(settings=Settings(123, 32, 16, 64, target, checkpoint_interval=7),
                    contract={'synthetic_fixture':'v1'}, metric_names=('fnrb', 'prescribed_annual_harvest'),
                    fnrb_fields=('fnrb',), output=output)

    def test_constant_needs_second_pass_and_exports(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / 'run'
            result = run(constant, **self.args(out))
            self.assertEqual(result['status'], 'precision_met')
            self.assertEqual(result['iterations'], 48)
            import csv
            with (out/'parameter_draws.csv').open(newline='') as handle:
                draws=list(csv.DictReader(handle))
            self.assertEqual(len(draws),48)
            self.assertEqual(json.loads(draws[-1]['value_json']),.4)
            self.assertEqual(draws[-1]['iteration'],'47')
            self.assertEqual(result['summaries']['fnrb']['p10'], .4)
            self.assertEqual(len((out/'parameter_draws.jsonl').read_text().splitlines()), 48)
            self.assertTrue((out/'iterations.csv').exists())
            self.assertFalse((out/'run.lock').exists())

    def test_resume_matches_uninterrupted_and_extends_to_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = Path(folder)/'a', Path(folder)/'b'
            first = run(variable, **self.args(a, 1e-10), stop_after=37)
            self.assertEqual(first['status'], 'interrupted')
            resumed = run(variable, **self.args(a, 1e-10), resume=True)
            straight = run(variable, **self.args(b, 1e-10))
            self.assertEqual(resumed, straight)
            self.assertEqual(resumed['status'], 'precision_limit_reached')
            self.assertEqual(resumed['iterations'], 64)
            self.assertEqual((a/'iterations.csv').read_bytes(), (b/'iterations.csv').read_bytes())

    def test_failed_draw_is_not_replaced(self):
        def failing(seed, iteration):
            if iteration == 13:
                raise ArithmeticError('synthetic failure')
            return variable(seed, iteration)
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'run'
            with self.assertRaises(ArithmeticError):
                run(failing, **self.args(out))
            checkpoint = json.loads((out/'checkpoint.json').read_text())['payload']
            self.assertEqual(len(checkpoint['rows']), 13)
            failure = json.loads((out/'failures.jsonl').read_text())
            self.assertEqual(failure['failed_iteration'], 13)
            self.assertFalse((out/'run.lock').exists())
            with self.assertRaises(ArithmeticError):
                run(failing, **self.args(out), resume=True)
            self.assertEqual(len((out/'failures.jsonl').read_text().splitlines()), 2)

    def test_changed_contract_rejects_without_overwriting_checkpoint(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'run'
            run(variable, **self.args(out), stop_after=8)
            before = (out/'checkpoint.json').read_bytes()
            args = self.args(out)
            args['contract'] = {'synthetic_fixture':'changed'}
            with self.assertRaises(ValueError):
                run(variable, **args, resume=True)
            self.assertEqual(before, (out/'checkpoint.json').read_bytes())

    def test_corrupt_checkpoint_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'run'
            run(variable, **self.args(out), stop_after=8)
            saved = json.loads((out/'checkpoint.json').read_text())
            saved['payload']['rows'][0][0] = .99
            (out/'checkpoint.json').write_text(json.dumps(saved))
            with self.assertRaises(ValueError):
                run(variable, **self.args(out), resume=True)

    def test_changed_evaluator_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'run'
            run(variable, **self.args(out), stop_after=8)
            with self.assertRaises(ValueError):
                run(constant, **self.args(out), resume=True)

    def test_lock_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)/'run'
            run(variable, **self.args(out), stop_after=8)
            with self.assertRaises(FileExistsError):
                run(variable, **self.args(out))
            (out/'run.lock').write_text('another writer')
            with self.assertRaises(FileExistsError):
                run(variable, **self.args(out), resume=True)

    def test_precision_uses_requested_percentiles_and_zero_mass(self):
        x = np.r_[np.zeros(48), np.ones(16)]
        result = precision(x, .005)
        self.assertEqual(result['zero_fraction'], .75)
        self.assertFalse(result['passed'])
        self.assertTrue(precision(np.zeros(64), .005)['passed'])


if __name__ == '__main__':
    unittest.main()
