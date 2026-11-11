# SPDX-License-Identifier: GPL-3.0-or-later
"""Auditable iteration execution with bounded extension and compatible restart.

The caller provides a deterministic evaluator(seed, iteration) returning a
Draw. Scientific inputs and assumptions belong in the explicit run contract.
"""
from dataclasses import asdict, dataclass
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import io
import inspect
import json
import math
import os
import platform
import traceback
import numpy as np


@dataclass(frozen=True)
class Settings:
    seed: int
    initial_iterations: int
    extension_iterations: int
    maximum_iterations: int
    precision_target: float
    required_passes: int = 2
    checkpoint_interval: int = 100

    def validate(self):
        for name in ('initial_iterations', 'extension_iterations', 'maximum_iterations',
                     'required_passes', 'checkpoint_interval'):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f'{name} must be a positive integer.')
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError('Seed must be a nonnegative integer.')
        if self.initial_iterations < 32 or self.maximum_iterations < self.initial_iterations:
            raise ValueError('Require at least 32 initial draws and maximum >= initial.')
        if not math.isfinite(self.precision_target) or not 0 < self.precision_target < 1:
            raise ValueError('Precision target must be in (0,1).')


@dataclass(frozen=True)
class Draw:
    metrics: dict[str, float]
    parameters: dict


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _time():
    return datetime.now(timezone.utc).isoformat()


def _atomic(path, content):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _json(path, value):
    _atomic(path, json.dumps(value, indent=2, allow_nan=False).encode())


def precision(values, target):
    """Mean MC error and P10/P90 batch/prefix stability diagnostics.

    These are numerical diagnostics, not proof of uncertainty coverage. An atom
    near a percentile boundary can make a finite prefix misleading.
    """
    x = np.asarray(values, float)
    if x.ndim != 1 or np.any(~np.isfinite(x)) or np.any((x < 0) | (x > 1)):
        raise ValueError('Precision values must be finite fNRB in [0,1].')
    if len(x) < 32:
        return dict(assessed=False, passed=False, iterations=len(x))
    batch_q = np.array([np.quantile(part, [.1, .9]) for part in np.array_split(x, 8)])
    endpoint_error = batch_q.std(axis=0, ddof=1) / np.sqrt(8)
    mean_error = float(x.std(ddof=1) / np.sqrt(len(x)))
    q = np.quantile(x, [.1, .9])
    prefix = np.quantile(x[:len(x)//2], [.1, .9])
    changes = np.abs(q - prefix)
    mean_change = abs(float(x.mean() - x[:len(x)//2].mean()))
    passed = mean_error <= target and mean_change <= target and bool(np.all(endpoint_error <= target) and np.all(changes <= target))
    return dict(assessed=True, passed=bool(passed), iterations=len(x), target=target,
                mean_standard_error=mean_error, half_prefix_mean_change=mean_change,
                percentile_batch_standard_errors=endpoint_error.tolist(),
                half_prefix_percentile_changes=changes.tolist(),
                zero_fraction=float(np.mean(x == 0)),
                note='Numerical mean/P10/P90 diagnostics; not a coverage guarantee.')


def _summaries(rows, metric_names, fnrb_fields):
    values = np.asarray(rows, float)
    result = {}
    if not len(rows):
        return result
    for index, name in enumerate(metric_names):
        x = values[:, index]
        result[name] = dict(mean=float(x.mean()), median=float(np.median(x)),
                            standard_deviation=float(x.std(ddof=1)) if len(x) > 1 else 0.,
                            p10=float(np.quantile(x, .1)), p90=float(np.quantile(x, .9)))
        if name in fnrb_fields:
            result[name]['zero_fraction'] = float(np.mean(x == 0))
    return result


def run(evaluate, *, settings, contract, metric_names, fnrb_fields, output,
        resume=False, stop_after=None):
    """Run complete draws, retaining parameter records and atomic checkpoints.

    stop_after is a graceful absolute draw-count limit for controlled shutdown.
    It is not a change to the scientific contract. The evaluator must record
    enough parameter/source identities to reproduce spatial draws.
    """
    settings.validate()
    names, targets = tuple(metric_names), tuple(fnrb_fields)
    if not names or len(set(names)) != len(names) or not targets or not set(targets) <= set(names):
        raise ValueError('Unique metric names and existing fNRB precision fields required.')
    if stop_after is not None and (type(stop_after) is not int or stop_after < 1):
        raise ValueError('Graceful stop count must be a positive integer.')
    if not isinstance(contract, dict) or not contract:
        raise ValueError('A nonempty scientific run contract is required.')
    import scipy
    source = Path(__file__).parent
    evaluator_file = inspect.getsourcefile(evaluate)
    if evaluator_file is None or not Path(evaluator_file).is_file():
        raise ValueError('Evaluator must have an identifiable Python source file for replay.')
    evaluator_identity = dict(module=evaluate.__module__, name=evaluate.__qualname__,
                              source_sha256=hashlib.sha256(Path(evaluator_file).read_bytes()).hexdigest())
    identity = dict(settings=asdict(settings), contract=contract, evaluator=evaluator_identity,
                    metric_names=names, fnrb_fields=targets,
                    code={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted(source.rglob('*.py'))},
                    runtime=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                                 system=platform.system(), machine=platform.machine()))
    identity = json.loads(canonical(identity))
    identity_hash = digest(identity)
    output = Path(output)
    if not resume:
        output.mkdir(parents=True, exist_ok=False)
    elif not output.is_dir():
        raise ValueError('No run directory to resume.')
    lock = output / 'run.lock'
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(descriptor, canonical(dict(pid=os.getpid(), time=_time())).encode())
    os.close(descriptor)
    rows, parameters, history, passes = [], [], [], 0
    checkpoint = output / 'checkpoint.json'
    validated = False

    def event(kind, **details):
        with (output / 'events.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(canonical(dict(time=_time(), event=kind, **details)) + '\n')

    def save(status):
        payload = dict(identity=identity_hash, rows=rows, parameters=parameters,
                       precision_history=history, consecutive_passes=passes, status=status)
        _json(checkpoint, dict(payload=payload, sha256=digest(payload)))
        _json(output / 'status.json', dict(status=status, completed_iterations=len(rows),
                                          maximum_iterations=settings.maximum_iterations, time=_time()))

    def export(status):
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow(['iteration', *names])
        writer.writerows([index, *row] for index, row in enumerate(rows))
        _atomic(output / 'iterations.csv', buffer.getvalue().encode())
        _atomic(output / 'parameter_draws.jsonl', ''.join(canonical(dict(iteration=i, parameters=p)) + '\n'
                for i, p in enumerate(parameters)).encode())
        buffer = io.StringIO(newline='')
        writer = csv.writer(buffer)
        writer.writerow(['iteration', 'parameter', 'value_json'])
        for index, parameter_record in enumerate(parameters):
            for name, value in sorted(parameter_record.items()):
                writer.writerow([index, name, canonical(value)])
        _atomic(output / 'parameter_draws.csv', buffer.getvalue().encode())
        result = dict(status=status, iterations=len(rows), summaries=_summaries(rows, names, targets),
                      precision_history=history, identity=identity_hash)
        _json(output / 'summary.json', result)
        return result

    try:
        if resume:
            if json.loads((output / 'run.json').read_text()) != identity:
                raise ValueError('Incompatible inputs, settings, source or runtime; start a new run.')
            saved = json.loads(checkpoint.read_text())
            payload = saved['payload']
            if saved['sha256'] != digest(payload) or payload['identity'] != identity_hash:
                raise ValueError('Checkpoint integrity or run identity mismatch.')
            rows, parameters = payload['rows'], payload['parameters']
            history, passes = payload['precision_history'], payload['consecutive_passes']
            if len(rows) != len(parameters) or len(rows) > settings.maximum_iterations:
                raise ValueError('Checkpoint lengths are inconsistent.')
            if len(rows) and (np.shape(rows) != (len(rows), len(names)) or not np.isfinite(rows).all()):
                raise ValueError('Invalid checkpoint result array.')
            if payload['status'] in ('precision_met', 'precision_limit_reached'):
                validated = True
                event('already_complete', iterations=len(rows))
                return export(payload['status'])
        else:
            _json(output / 'run.json', identity)
            save('prepared')
        validated = True
        event('resumed' if resume else 'started', completed_iterations=len(rows))
        if stop_after is not None and len(rows) >= stop_after:
            save('interrupted')
            return export('interrupted')
        while len(rows) < settings.maximum_iterations:
            iteration = len(rows)
            draw = evaluate(settings.seed, iteration)
            if not isinstance(draw, Draw) or set(draw.metrics) != set(names):
                raise ValueError('Evaluator must return the declared metric set.')
            row = [float(draw.metrics[name]) for name in names]
            if not all(math.isfinite(value) for value in row):
                raise ArithmeticError('Non-finite iteration result.')
            if any(not 0 <= row[names.index(name)] <= 1 for name in targets):
                raise ArithmeticError('fNRB outside [0,1].')
            parameter_record = json.loads(canonical(draw.parameters))
            rows.append(row)
            parameters.append(parameter_record)
            n = len(rows)
            assess = n >= settings.initial_iterations and ((n-settings.initial_iterations) % settings.extension_iterations == 0 or n == settings.maximum_iterations)
            if assess:
                checks = {name: precision(np.asarray(rows)[:, names.index(name)], settings.precision_target) for name in targets}
                all_pass = all(item['passed'] for item in checks.values())
                passes = passes + 1 if all_pass else 0
                history.append(dict(iterations=n, checks=checks, consecutive_passes=passes))
                event('precision_checked', iterations=n, passed=all_pass, consecutive_passes=passes)
                if passes >= settings.required_passes:
                    save('precision_met')
                    event('completed', reason='precision_met', iterations=n)
                    return export('precision_met')
                if n < settings.maximum_iterations:
                    event('extension_scheduled', next_check=min(n+settings.extension_iterations, settings.maximum_iterations))
            if n % settings.checkpoint_interval == 0:
                save('running')
            if stop_after is not None and n >= stop_after and n < settings.maximum_iterations:
                save('interrupted')
                event('graceful_stop', iterations=n)
                return export('interrupted')
        save('precision_limit_reached')
        event('completed', reason='precision_limit_reached', iterations=len(rows))
        return export('precision_limit_reached')
    except BaseException as error:
        if validated:
            status = 'interrupted' if isinstance(error, KeyboardInterrupt) else 'failed'
            save(status)
            failure = dict(time=_time(), status=status, failed_iteration=len(rows),
                           error_type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
            with (output / 'failures.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(canonical(failure) + '\n')
            event(status, completed_iterations=len(rows), error=str(error))
            export(status)
        else:
            event('resume_rejected', error=str(error))
        raise
    finally:
        lock.unlink()
