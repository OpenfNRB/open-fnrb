# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit, reproducible uncertainty models on source-cell identities.

Error scales must be interpreted before calling these functions. No provider
accuracy statistic is implicitly converted into a pixel standard deviation.
"""
import hashlib
import math
import numpy as np


def generator(seed, iteration, stream):
    """Independent named stream; repeated identities reproduce the same draw."""
    if type(seed) is not int or seed < 0 or type(iteration) is not int or iteration < 0:
        raise ValueError('Seed and iteration must be nonnegative integers.')
    if not isinstance(stream, str) or not stream:
        raise ValueError('A nonempty source/parameter stream identity is required.')
    key = np.frombuffer(hashlib.sha256(stream.encode('utf-8')).digest(), dtype='<u4').tolist()
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, iteration, *key])))


def _mix(value):
    with np.errstate(over='ignore'):
        value = np.asarray(value, dtype=np.uint64) + np.uint64(0x9E3779B97F4A7C15)
        value = (value ^ (value >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        value = (value ^ (value >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return value ^ (value >> np.uint64(31))


def cell_uniforms(cell_ids, seed, iteration, stream, dependence):
    """Open-interval uniforms stable under tiling, ordering and duplicate cells."""
    ids = np.asarray(cell_ids)
    if ids.ndim != 1 or ids.dtype.kind not in 'iu' or np.any(ids < 0):
        raise ValueError('Source-cell IDs must be a nonnegative integer vector.')
    if dependence not in ('independent', 'shared'):
        raise ValueError('Select independent or shared spatial errors explicitly.')
    rng = generator(seed, iteration, stream)
    key = rng.integers(0, np.iinfo(np.uint64).max, dtype=np.uint64)
    counters = ids.astype(np.uint64) if dependence == 'independent' else np.zeros(ids.shape, np.uint64)
    mixed = _mix(counters ^ key)
    return ((mixed >> np.uint64(12)).astype(float) + .5) / 2**52


def lognormal_moments(mean, sd):
    mean, sd = np.broadcast_arrays(np.asarray(mean, float), np.asarray(sd, float))
    if np.any(~np.isfinite(mean)) or np.any(mean <= 0) or np.any(~np.isfinite(sd)) or np.any(sd < 0):
        raise ValueError('Lognormal requires positive finite means and nonnegative finite SDs.')
    variance = np.zeros_like(mean)
    positive = sd > 0
    variance[positive] = np.logaddexp(0., 2 * (np.log(sd[positive]) - np.log(mean[positive])))
    return np.log(mean) - variance / 2, np.sqrt(variance)


def positive_lognormal(mean, sd, normal_draw):
    """Match arithmetic moments; retain deterministic inputs exactly."""
    mean, sd, z = np.broadcast_arrays(np.asarray(mean, float), np.asarray(sd, float),
                                      np.asarray(normal_draw, float))
    if np.any(~np.isfinite(z)):
        raise ValueError('Non-finite latent draw.')
    mu, sigma = lognormal_moments(mean, sd)
    with np.errstate(over='raise', invalid='raise', under='raise'):
        values = np.exp(mu + sigma * z)
    values = np.where(sd == 0, mean, values)
    if np.any(~np.isfinite(values)) or np.any(values <= 0):
        raise ArithmeticError('Lognormal draw outside positive numerical range.')
    return values


def parameter_draw(mean, sd, seed, iteration, source_group):
    """One value per shared source/ecological group, not per classified cell."""
    z = generator(seed, iteration, source_group).standard_normal()
    return float(positive_lognormal(mean, sd, z))


def _spatial_inputs(mapped, scale, cell_ids):
    mapped, scale = np.asarray(mapped, float), np.asarray(scale, float)
    if mapped.ndim != 1 or mapped.shape != scale.shape or mapped.shape != np.shape(cell_ids):
        raise ValueError('Mapped values, scales and IDs must be matching vectors.')
    if np.any(~np.isfinite(mapped)) or np.any(~np.isfinite(scale)) or np.any(scale < 0):
        raise ValueError('Missing/non-finite input or invalid uncertainty scale.')
    # Duplicate area records of the same source cell must describe one observation.
    ids, first, inverse = np.unique(cell_ids, return_index=True, return_inverse=True)
    if not np.array_equal(mapped, mapped[first][inverse]) or not np.array_equal(scale, scale[first][inverse]):
        raise ValueError('Repeated source-cell IDs have inconsistent values or uncertainty.')
    return mapped, scale


def sample_agb(mapped, scale, cell_ids, *, seed, iteration, stream,
               dependence, zero_policy, acknowledged):
    """Positive-stock lognormal with an explicit uncertain-zero treatment.

    zero_policy is fixed_zero or censored_normal. Both require acknowledgement
    of uncertainty interpretation; neither is silently selected.
    """
    from scipy.special import ndtri
    if acknowledged is not True or zero_policy not in ('fixed_zero', 'censored_normal'):
        raise ValueError('Explicit acknowledgement and zero-stock policy required.')
    mapped, scale = _spatial_inputs(mapped, scale, cell_ids)
    if np.any(mapped < 0):
        raise ValueError('AGB must be nonnegative.')
    z = ndtri(cell_uniforms(cell_ids, seed, iteration, stream, dependence))
    values = mapped.copy()
    positive = mapped > 0
    values[positive] = positive_lognormal(mapped[positive], scale[positive], z[positive])
    uncertain_zero = (mapped == 0) & (scale > 0)
    expected_shift = np.zeros_like(mapped)
    if zero_policy == 'censored_normal':
        values[uncertain_zero] = np.maximum(0., scale[uncertain_zero] * z[uncertain_zero])
        expected_shift[uncertain_zero] = scale[uncertain_zero] / math.sqrt(2 * math.pi)
    return values, dict(expected_mean_shift=expected_shift, sampled_change=values - mapped,
                        uncertain_zero=uncertain_zero,
                        zero_uncertainty_omitted=uncertain_zero & (zero_policy == 'fixed_zero'))


def sample_cover(mapped, scale, cell_ids, *, seed, iteration, stream,
                 dependence, acknowledged):
    """Truncated normal on [0,1]; map is the untruncated location, not the mean."""
    from scipy.stats import truncnorm
    if acknowledged is not True:
        raise ValueError('Bounded-cover model and mean-shift acknowledgement required.')
    mapped, scale = _spatial_inputs(mapped, scale, cell_ids)
    if np.any((mapped < 0) | (mapped > 1)):
        raise ValueError('Canopy must be a fraction between zero and one.')
    u = cell_uniforms(cell_ids, seed, iteration, stream, dependence)
    values, expected, resulting_sd = mapped.copy(), mapped.copy(), np.zeros_like(mapped)
    active = scale > 0
    if active.any():
        a, b = -mapped[active] / scale[active], (1 - mapped[active]) / scale[active]
        values[active] = truncnorm.ppf(u[active], a, b, loc=mapped[active], scale=scale[active])
        expected[active], variance = truncnorm.stats(a, b, loc=mapped[active], scale=scale[active], moments='mv')
        resulting_sd[active] = np.sqrt(variance)
    if any(np.any(~np.isfinite(x)) for x in (values, expected, resulting_sd)) or np.any((values < 0) | (values > 1)):
        raise ArithmeticError('Bounded-cover sampling outside numerical range.')
    return values, dict(expected_mean=expected, resulting_sd=resulting_sd,
                        expected_mean_shift=expected - mapped, sampled_change=values - mapped)


def sample_classes(mapped, codes, counts, cell_ids, *, seed, iteration, stream, acknowledged):
    """Fixed mapped-row/reference-column probabilities with native-cell draws."""
    if acknowledged is not True:
        raise ValueError('Classification model acknowledgement required.')
    mapped, codes, counts = np.asarray(mapped), np.asarray(codes), np.asarray(counts, float)
    if (codes.ndim != 1 or not len(codes) or codes.dtype.kind not in 'iu' or len(np.unique(codes)) != len(codes)
            or mapped.ndim != 1 or mapped.dtype.kind not in 'iu' or mapped.shape != np.shape(cell_ids)
            or counts.shape != (len(codes), len(codes)) or np.any(~np.isfinite(counts))
            or np.any(counts < 0) or np.any(counts.max(axis=1) <= 0) or np.any(~np.isin(mapped, codes))):
        raise ValueError('Invalid classification codes or mapped-row confusion matrix.')
    _spatial_inputs(mapped, np.zeros(mapped.shape), cell_ids)
    # Scaling prevents overflow when finite weighted counts have very large sums.
    scaled=counts/counts.max(axis=1,keepdims=True)
    probabilities = scaled / scaled.sum(axis=1, keepdims=True)
    cdf = np.cumsum(probabilities, axis=1)
    cdf[:, -1] = 1.
    u = cell_uniforms(cell_ids, seed, iteration, stream, 'independent')
    result = np.empty_like(mapped)
    for index, code in enumerate(codes):
        selected = mapped == code
        result[selected] = codes[np.searchsorted(cdf[index], u[selected], side='right')]
    return result


def bootstrap_household_woody_biomass_use(values, *, seed, iteration, stream, design,
                          unit_ids=None, weights=None, acknowledged=False):
    """Resample independent survey units, or explicitly assumed iid households.

    Repeated observations within a supplied unit remain together. Stratified or
    unequal-probability designs require an appropriate external specification.
    """
    values = np.asarray(values, float)
    w = np.ones(values.shape) if weights is None else np.asarray(weights, float)
    if (values.ndim != 1 or not len(values) or w.shape != values.shape
            or np.any(~np.isfinite(values)) or np.any(values < 0)
            or np.any(~np.isfinite(w)) or np.any(w <= 0)):
        raise ValueError('Invalid observations or weights.')
    if acknowledged is not True or design not in ('independent_units', 'assumed_iid'):
        raise ValueError('Explicit supported survey design and acknowledgement required.')
    if design == 'independent_units' and unit_ids is None:
        raise ValueError('Supply independent survey-unit IDs.')
    ids = np.arange(len(values)) if unit_ids is None else np.asarray(unit_ids)
    if ids.shape != values.shape:
        raise ValueError('Survey-unit IDs must match observations.')
    if design == 'assumed_iid' and len(np.unique(ids)) != len(ids):
        raise ValueError('Repeated survey units require independent_units design.')
    _, inverse = np.unique(ids, return_inverse=True)
    numerator = np.bincount(inverse, weights=values * w)
    denominator = np.bincount(inverse, weights=w)
    selected = generator(seed, iteration, stream).integers(len(numerator), size=len(numerator))
    result = float(numerator[selected].sum() / denominator[selected].sum())
    if not math.isfinite(result):
        raise ArithmeticError('Household woody biomass use draw outside finite range.')
    return result
