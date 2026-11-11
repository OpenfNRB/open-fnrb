# SPDX-License-Identifier: GPL-3.0-or-later
"""Analytical one-year logistic stock dynamics with constant prescribed harvest.

dB/dt = (4 I/K) B(1-B/K) - h, until B reaches zero. Thereafter
growth and realised harvest are zero (no regeneration floor). No timestep loop.
"""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class AnnualFlux:
    end: np.ndarray
    regeneration: np.ndarray
    realised_harvest: np.ndarray
    unrealised_harvest: np.ndarray
    active_years: np.ndarray


def annual_logistic(start, capacity, peak_increment, prescribed_harvest_rate):
    """Inputs/outputs are t DM/ha; prescribed harvest rate is t DM/ha/year.

    Arrays broadcast. I may be zero for boundary checks; K must be positive.
    Growth is the integrated net biological increment, recovered from the exact
    stock solution and realised removal. It is independently checked against
    quadrature in offline validation, not validated by balance alone.
    """
    values = np.broadcast_arrays(*[np.asarray(x, dtype=np.float64) for x in
                                  (start, capacity, peak_increment, prescribed_harvest_rate)])
    if any(np.any(~np.isfinite(x)) for x in values):
        raise ValueError('Annual inputs must be finite.')
    b0, k, inc, h = [x.ravel() for x in values]
    if np.any(k <= 0) or any(np.any(x < 0) for x in (b0, inc, h)) or np.any(b0 > k):
        raise ValueError('Require K>0, 0<=B0<=K, I>=0 and harvest>=0.')
    with np.errstate(over='ignore', under='ignore', invalid='ignore'):
        derived_rate = 4*(inc/k)
    if np.any(~np.isfinite(derived_rate)) or np.any((inc > 0)&(derived_rate == 0)):
        raise ValueError('Derived rmax outside finite positive numerical range; no clipping or redraw.')
    end = b0.copy()
    active = np.ones_like(b0)
    taken = np.zeros_like(b0)
    zero = b0 == 0
    active[zero] = 0
    linear = (inc == 0) & ~zero
    taken[linear] = np.minimum(h[linear], b0[linear])
    end[linear] = b0[linear] - taken[linear]
    removing = linear & (h > 0)
    active[removing] = np.minimum(1.0, b0[removing]/h[removing])
    no_harvest = (inc > 0) & (h == 0) & ~zero
    if np.any(no_harvest):
        x = b0[no_harvest]/k[no_harvest]
        rate = derived_rate[no_harvest]
        decay = np.exp(-rate)
        end[no_harvest] = k[no_harvest] * x/(x+(1-x)*decay)
    nonlinear = (inc > 0) & (h > 0) & ~zero
    if np.any(nonlinear):
        ix = np.flatnonzero(nonlinear)
        z = 2*b0[ix]/k[ix]-1
        rate = derived_rate[ix]/2  # z' = rate*(s-z^2)
        s = 1-h[ix]/inc[ix]
        if np.any(~np.isfinite(rate)) or np.any(~np.isfinite(s)) or np.any(rate <= 0):
            raise ValueError('Derived rate/discriminant outside finite numerical range.')
        z1 = np.empty_like(z)
        duration = np.ones_like(z)
        positive = s > 0
        if np.any(positive):
            zp, sp, rp = z[positive], s[positive], rate[positive]
            root = np.sqrt(sp)
            hit = np.full_like(zp, np.inf)
            declining = zp < -root
            # Only the lower branch can reach zero for harvest below peak.
            ratio = -root[declining]*(1+zp[declining])/(sp[declining]+zp[declining])
            with np.errstate(divide='ignore', invalid='raise'):
                hit[declining] = np.arctanh(np.minimum(ratio, 1.0))/(rp[declining]*root[declining])
            live = hit > 1
            out = np.full_like(zp, -1.0)
            phi = np.tanh(rp[live]*root[live])/root[live]
            out[live] = (zp[live]+sp[live]*phi)/(1+zp[live]*phi)
            z1[positive] = out
            duration[positive] = np.minimum(1., hit)
        critical = s == 0
        if np.any(critical):
            zc, rc = z[critical], rate[critical]
            hit = np.full_like(zc, np.inf)
            negative = zc < 0
            hit[negative] = (-1/zc[negative]-1)/rc[negative]
            live = hit > 1
            out = np.full_like(zc, -1.)
            out[live] = zc[live]/(1+rc[live]*zc[live])
            z1[critical] = out
            duration[critical] = np.minimum(1., hit)
        supercritical = s < 0
        if np.any(supercritical):
            zs, ss, rs = z[supercritical], s[supercritical], rate[supercritical]
            root = np.sqrt(-ss)
            angle = np.arctan(zs/root)
            hit = (angle+np.arctan(1/root))/(rs*root)
            live = hit > 1
            out = np.full_like(zs, -1.)
            out[live] = root[live]*np.tan(angle[live]-rs[live]*root[live])
            z1[supercritical] = out
            duration[supercritical] = np.minimum(1., hit)
        end[ix] = k[ix]*(z1+1)/2
        active[ix] = duration
        taken[ix] = h[ix]*duration
    regeneration = end-b0+taken
    tolerance = 1e-10*np.maximum(1., k+b0+taken)
    if (np.any(~np.isfinite(end)) or np.any(~np.isfinite(regeneration)) or
        np.any(end < -tolerance) or np.any(end > k+tolerance) or
        np.any(regeneration < -tolerance) or np.any(active < 0) or np.any(active > 1)):
        raise ArithmeticError('Analytical annual solution failed numerical bounds.')
    # Remove floating roundoff only; this is not an input or ecological clamp.
    end = np.clip(end, 0., k)
    regeneration = np.maximum(0., end-b0+taken)
    shape = values[0].shape
    return AnnualFlux(*(x.reshape(shape) for x in
                        (end, regeneration, taken, np.maximum(0., h-taken), active)))
