# SPDX-License-Identifier: GPL-3.0-or-later
"""Annual assessment on explicitly prepared eligible area records.

Stock and parameter densities use tonnes of woody dry matter per hectare.
Harvest is tonnes per year; area is hectares. Each area record may represent
part of a source cell. Spatial preparation must prevent double counting.
"""
from dataclasses import dataclass
import math
import numpy as np

from .growth import annual_logistic


@dataclass(frozen=True)
class AnnualResult:
    """Aggregate metrics and aligned per-area-record audit arrays."""

    summary: dict
    cells: dict[str, np.ndarray]


def _array(values, name, *, shape=None, positive=False):
    result = np.array(values, dtype=np.float64, copy=True)
    if result.ndim != 1 or (shape is not None and result.shape != shape):
        raise ValueError(f'{name} must be a matching one-dimensional array.')
    if np.any(~np.isfinite(result)):
        raise ValueError(f'{name} contains missing or non-finite values.')
    invalid = np.any(result <= 0) if positive else np.any(result < 0)
    if invalid:
        raise ValueError(f'{name} must be {"positive" if positive else "nonnegative"}.')
    return result


def stock_from_canopy(cover_fraction, reference_capacity):
    """Derive stock using the same reference-capacity values used for growth.

    For Monte Carlo, callers pass the sampled cover and sampled reference
    capacity. Cover must be a fraction, not a percentage or an eligibility rule.
    """
    cover = _array(cover_fraction, 'Canopy fraction')
    capacity = _array(reference_capacity, 'Reference capacity', shape=cover.shape, positive=True)
    if np.any(cover > 1):
        raise ValueError('Canopy fraction must lie between zero and one.')
    with np.errstate(over='raise', invalid='raise'):
        return cover * capacity


def assess_year(area_ha, starting_stock, reference_capacity, peak_increment,
                prescribed_annual_harvest_tonnes, *, chunk_size=16384):
    """Calculate one year with uniform prescribed harvesting and fixed-peak capacity adjustment.

    Parameter arrays are assigned to each area record before this call. No
    geographical identifiers, source products or class codes are implicit.
    Unrealised harvest is retained, not redistributed. Zero harvest returns zero
    fNRB with an explicit flag. An empty eligible area retains full harvest.
    """
    if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
        raise ValueError('Chunk size must be a positive integer.')
    if isinstance(prescribed_annual_harvest_tonnes, (bool, np.bool_)):
        raise ValueError('Harvest must be a finite nonnegative number.')
    prescribed_annual_harvest = float(prescribed_annual_harvest_tonnes)
    if not math.isfinite(prescribed_annual_harvest) or prescribed_annual_harvest < 0:
        raise ValueError('Harvest must be finite and nonnegative.')
    area = _array(area_ha, 'Eligible area', positive=True)
    stock = _array(starting_stock, 'Starting stock', shape=area.shape)
    reference = _array(reference_capacity, 'Reference capacity', shape=area.shape, positive=True)
    increment = _array(peak_increment, 'Peak increment', shape=area.shape)
    effective = np.maximum(reference, stock)
    total_area = float(area.sum())
    if not math.isfinite(total_area):
        raise ValueError('Total eligible area is outside numerical range.')
    prescribed_harvest_density = np.full(area.shape, prescribed_annual_harvest / total_area if total_area else 0.)
    if np.any(~np.isfinite(prescribed_harvest_density)):
        raise ValueError('Prescribed harvest density is outside numerical range.')

    ending = np.empty_like(stock)
    regeneration = np.empty_like(stock)
    realised_harvest = np.empty_like(stock)
    unrealised_harvest_density = np.empty_like(stock)
    active = np.empty_like(stock)
    totals = dict(start=0., end=0., regeneration=0., realised_harvest=0., depletion=0.)
    for lo in range(0, len(area), chunk_size):
        section = slice(lo, lo + chunk_size)
        flux = annual_logistic(stock[section], effective[section], increment[section], prescribed_harvest_density[section])
        ending[section], regeneration[section], realised_harvest[section] = flux.end, flux.regeneration, flux.realised_harvest
        unrealised_harvest_density[section], active[section] = flux.unrealised_harvest, flux.active_years
        residual = (stock[section] + flux.regeneration - flux.realised_harvest - flux.end) * area[section]
        scale = np.maximum(1., (stock[section] + flux.regeneration + flux.realised_harvest) * area[section])
        if np.any(np.abs(residual) > 1e-6 * scale):
            raise ArithmeticError('Annual stock conservation failed.')
        removed = float(np.sum(flux.realised_harvest * area[section]))
        depleted = float(np.sum(np.maximum(0., stock[section] - flux.end) * area[section]))
        if depleted > removed + 1e-6 * max(1., removed):
            raise ArithmeticError('Stock depletion exceeds realised harvest.')
        totals['start'] += float(np.sum(stock[section] * area[section]))
        totals['end'] += float(np.sum(flux.end * area[section]))
        totals['regeneration'] += float(np.sum(flux.regeneration * area[section]))
        totals['realised_harvest'] += removed
        totals['depletion'] += min(depleted, removed)
    if not all(math.isfinite(value) for value in totals.values()):
        raise ArithmeticError('Annual aggregate outside numerical range.')
    if totals['realised_harvest'] > prescribed_annual_harvest + 1e-9 * max(1., prescribed_annual_harvest):
        raise ArithmeticError('Realised harvest exceeds annual harvest.')
    non_renewable_biomass = max(0., prescribed_annual_harvest - totals['regeneration'])
    adjusted = stock > reference
    summary = dict(
        metric='annual_harvest_regeneration_fnrb', fnrb=non_renewable_biomass / prescribed_annual_harvest if prescribed_annual_harvest else 0.,
        zero_prescribed_harvest=prescribed_annual_harvest == 0., eligible_area_ha=total_area, prescribed_annual_harvest_tonnes=prescribed_annual_harvest,
        annual_woody_biomass_regeneration_tonnes=totals['regeneration'], non_renewable_biomass_tonnes=non_renewable_biomass,
        start_woody_stock_tonnes=totals['start'], end_woody_stock_tonnes=totals['end'],
        realised_harvest_tonnes=totals['realised_harvest'], unrealised_harvest_tonnes=max(0., prescribed_annual_harvest - totals['realised_harvest']),
        harvest_realisation_fraction=totals['realised_harvest'] / prescribed_annual_harvest if prescribed_annual_harvest else None,
        stock_depletion_tonnes=totals['depletion'],
        stock_depletion_ratio_diagnostic=totals['depletion'] / totals['realised_harvest'] if totals['realised_harvest'] else None,
        stock_and_regeneration_shortfall_tonnes=max(0., prescribed_annual_harvest - totals['start'] - totals['regeneration']),
        adjusted_capacity_area_ha=float(area[adjusted].sum()),
        adjusted_capacity_starting_stock_tonnes=float(np.sum(area[adjusted] * stock[adjusted])),
        capacity_adjustment_tonnes=float(np.sum(area * (effective - reference))),
        effective_capacity_stock_tonnes=float(np.dot(area, effective)),
    )
    cells = dict(area_ha=area, starting_stock_t_ha=stock,
                 reference_capacity_t_ha=reference, effective_capacity_t_ha=effective,
                 capacity_adjustment_t_ha=effective - reference, peak_increment_t_ha_year=increment,
                 prescribed_harvest_t_ha=prescribed_harvest_density, realised_harvest_t_ha=realised_harvest,
                 annual_regeneration_t_ha=regeneration, closing_stock_t_ha=ending,
                 unrealised_harvest_t_ha=unrealised_harvest_density, active_year_fraction=active)
    if any(np.any(~np.isfinite(value)) for value in cells.values()):
        raise ArithmeticError('Annual audit array outside numerical range.')
    for value in cells.values():
        value.flags.writeable = False
    return AnnualResult(summary, cells)
