# SPDX-License-Identifier: GPL-3.0-or-later
"""Connect prepared area records and explicit uncertainty to annual assessments."""
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import numpy as np

from .annual import assess_year, stock_from_canopy,AnnualResult
from .monte_carlo import Draw
from .uncertainty import parameter_draw, sample_agb, sample_cover, bootstrap_household_woody_biomass_use


METRICS = ('fnrb', 'prescribed_annual_harvest_tonnes', 'annual_woody_biomass_regeneration_tonnes', 'realised_harvest_tonnes',
           'start_woody_stock_tonnes', 'end_woody_stock_tonnes', 'unrealised_harvest_tonnes',
           'adjusted_capacity_area_ha', 'zero_prescribed_harvest','eligible_area_ha')


@dataclass(frozen=True)
class ZoneParameters:
    name: str
    increment_mean: float
    increment_sd: float
    capacity_mean: float
    capacity_sd: float
    increment_group: str
    capacity_group: str


def array_identity(array):
    a = np.ascontiguousarray(array)
    return dict(dtype=a.dtype.str, shape=list(a.shape),
                sha256=hashlib.sha256(a.tobytes()).hexdigest())


class Simulation:
    """Prepared-input MC adapter for one area and one spatial dependence case.

    Explicit input acknowledgements and evidence identifiers belong in metadata.
    Separate Simulation instances represent independent/shared-error cases.
    Native-cell IDs must remain stable when an area record is split or reordered.
    """
    def __init__(self, *, area, zone_index, source_cell_ids, mapped_stock, stock_scale,
                 parameters, stock_mode, dependence, zero_policy, prescribed_annual_harvest_tonnes,
                 uncertainty_acknowledged, source_identity, uncertainty_interpretation,
                 harvest_model=None,classification=None):
        self.area = np.array(area, float, copy=True)
        self.zone_index = np.array(zone_index, copy=True)
        self.cell_ids = np.array(source_cell_ids, copy=True)
        self.mapped = np.array(mapped_stock, float, copy=True)
        self.scale = np.array(stock_scale, float, copy=True)
        self.parameters = tuple(parameters)
        self.prescribed_annual_harvest = float(prescribed_annual_harvest_tonnes)
        self.mode, self.dependence, self.zero_policy = stock_mode, dependence, zero_policy
        self.source_identity = source_identity
        self.interpretation = uncertainty_interpretation
        self.classification=classification
        if stock_mode not in ('agb', 'canopy') or dependence not in ('independent', 'shared'):
            raise ValueError('Explicit stock route and supported dependence required.')
        if uncertainty_acknowledged is not True or not source_identity or not uncertainty_interpretation:
            raise ValueError('Source identity, error interpretation and acknowledgement required.')
        if stock_mode == 'agb' and zero_policy not in ('fixed_zero', 'censored_normal'):
            raise ValueError('Explicit AGB zero-stock policy required.')
        if stock_mode == 'canopy' and zero_policy != 'bounded_cover':
            raise ValueError('Canopy route requires the acknowledged bounded_cover policy.')
        if self.area.ndim != 1 or any(x.shape != self.area.shape for x in
                (self.zone_index, self.cell_ids, self.mapped, self.scale)):
            raise ValueError('Prepared input arrays must be matching vectors.')
        if self.zone_index.dtype.kind not in 'iu' or np.any(self.zone_index < 0) or np.any(self.zone_index >= len(self.parameters)):
            raise ValueError('Zone indices must reference parameter records.')
        if self.cell_ids.dtype.kind not in 'iu' or np.any(self.cell_ids < 0):
            raise ValueError('Native source-cell IDs must be nonnegative integers.')
        if not math.isfinite(self.prescribed_annual_harvest) or self.prescribed_annual_harvest < 0:
            raise ValueError('Harvest must be finite and nonnegative.')
        if np.any(~np.isfinite(self.scale)) or np.any(self.scale < 0):
            raise ValueError('Missing or invalid stock uncertainty scale.')
        names, groups = set(), {}
        for p in self.parameters:
            if not isinstance(p, ZoneParameters) or not p.name or p.name in names:
                raise ValueError('Unique named parameter records required.')
            names.add(p.name)
            for kind, mean, sd, group in (
                    ('increment', p.increment_mean, p.increment_sd, p.increment_group),
                    ('capacity', p.capacity_mean, p.capacity_sd, p.capacity_group)):
                if not group or not math.isfinite(mean) or mean <= 0 or not math.isfinite(sd) or sd < 0:
                    raise ValueError('Invalid parameter moments or source group.')
                key = (kind, group)
                if key in groups and groups[key] != (mean, sd):
                    raise ValueError('Shared source parameter has inconsistent moments.')
                groups[key] = (mean, sd)
        self.harvest_model = json.loads(json.dumps(harvest_model or {'kind':'fixed'}, allow_nan=False))
        self._validate_harvest()
        if classification is not None:
            model=classification['model']
            for name in ('cell_ids','mapped'):
                value=np.array(classification[name],copy=True)
                if value.shape!=self.area.shape or value.dtype.kind not in 'iu':
                    raise ValueError('Classification vectors must match candidate records.')
                value.flags.writeable=False;classification[name]=value
            if not set(model.codes)<=set(classification['rules']) or any(type(v) is not bool for v in classification['rules'].values()):
                raise ValueError('Explicit eligibility rules required for all classification outcomes.')
            model.draw(classification['mapped'],classification['cell_ids'],0,0)
            if np.any(~np.isfinite(self.area)) or np.any(self.area<=0) or np.any(~np.isfinite(self.mapped)) or np.any(self.mapped<0):
                raise ValueError('Invalid candidate stock or area.')
            if self.mode=='canopy' and np.any(self.mapped>1):raise ValueError('Canopy must be a fraction.')
        for value in (self.area, self.zone_index, self.cell_ids, self.mapped, self.scale):
            value.flags.writeable = False
        # Validate the nominal data immediately, before any stochastic execution.
        self.nominal()
        _, first, inverse = np.unique(self.cell_ids, return_index=True, return_inverse=True)
        if not np.array_equal(self.mapped, self.mapped[first][inverse]) or not np.array_equal(self.scale, self.scale[first][inverse]):
            raise ValueError('Repeated stock cells have inconsistent observations.')

    def _validate_harvest(self):
        model = self.harvest_model
        kind = model.get('kind')
        if kind == 'fixed':
            return
        if model.get('acknowledged') is not True or not model.get('source_id'):
            raise ValueError('Harvest uncertainty requires acknowledgement and source identity.')
        if kind == 'lognormal':
            sd = model.get('sd')
            if self.prescribed_annual_harvest <= 0 or not isinstance(sd, (int,float)) or not math.isfinite(sd) or sd < 0:
                raise ValueError('Lognormal harvest requires positive mean harvest and nonnegative SD.')
        elif kind == 'household_bootstrap':
            households = float(model['households'])
            values = np.asarray(model['annual_household_woody_biomass_use_tonnes'], float)
            if not math.isfinite(households) or households < 0:
                raise ValueError('Household count must be finite and nonnegative.')
            # Validates design and observations without changing nominal harvest.
            self._sample_harvest(0, 0)
            weights = np.ones(values.shape) if model.get('weights') is None else np.asarray(model['weights'], float)
            expected = households * float(np.average(values, weights=weights))
            if not math.isclose(expected, self.prescribed_annual_harvest, rel_tol=1e-10, abs_tol=1e-10):
                raise ValueError('Nominal harvest differs from household observations and count.')
        else:
            raise ValueError('Unsupported harvest distribution; no inferred conversion.')

    def _sample_harvest(self, seed, iteration):
        model = self.harvest_model
        if model['kind'] == 'fixed':
            return self.prescribed_annual_harvest
        # Stable stream namespace for reproducible harvest draws.
        stream = 'demand/' + model['source_id']
        if model['kind'] == 'lognormal':
            return parameter_draw(self.prescribed_annual_harvest, model['sd'], seed, iteration, stream)
        if model['kind'] == 'household_bootstrap':
            mean = bootstrap_household_woody_biomass_use(model['annual_household_woody_biomass_use_tonnes'], seed=seed, iteration=iteration,
                     stream=stream, design=model['design'], unit_ids=model.get('unit_ids'),
                     weights=model.get('weights'), acknowledged=model['acknowledged'])
            return float(model['households']) * mean
        raise ValueError('Unsupported harvest uncertainty.')

    def nominal(self):
        inc = np.array([p.increment_mean for p in self.parameters])[self.zone_index]
        cap = np.array([p.capacity_mean for p in self.parameters])[self.zone_index]
        stock = self.mapped if self.mode == 'agb' else stock_from_canopy(self.mapped, cap)
        classes=None if self.classification is None else self.classification['mapped']
        return self._assess(stock,cap,inc,self.prescribed_annual_harvest,classes)

    def _assess(self,stock,capacity,increment,prescribed_annual_harvest,classes=None):
        if self.classification is None:return assess_year(self.area,stock,capacity,increment,prescribed_annual_harvest)
        selected=np.array([self.classification['rules'][int(c)] for c in classes],dtype=bool)
        result=assess_year(self.area[selected],stock[selected],capacity[selected],increment[selected],prescribed_annual_harvest)
        # Stable candidate records let replay/maps retain draws with no resource.
        # Zero denotes no eligible-resource contribution, not absent physical biomass.
        cells={}
        for name,values in result.cells.items():
            full=np.zeros(self.area.shape);full[selected]=values;full.flags.writeable=False;cells[name]=full
        cells['eligible_fraction']=selected.astype(float);cells['eligible_fraction'].flags.writeable=False
        return AnnualResult(result.summary,cells)

    @property
    def geometry_filename(self):
        return 'classification_candidates.csv' if self.classification is not None else 'nominal_cells.csv'

    def classification_contract(self):
        if self.classification is None:return None
        c=self.classification;m=c['model']
        return dict(codes=list(m.codes),counts=[list(r) for r in m.counts],source_id=m.source_id,evidence=m.evidence,
            rules={str(k):v for k,v in c['rules'].items()},mapped=array_identity(c['mapped']),cell_ids=array_identity(c['cell_ids']),
            scope='resource eligibility only; ecological zones and household allocation fixed')

    def contract(self):
        return dict(schema='prepared-annual-uncertainty-v1', stock_mode=self.mode,
                    dependence=self.dependence, zero_policy=self.zero_policy,
                    source_identity=self.source_identity, uncertainty_interpretation=self.interpretation,
                    acknowledged=True, parameters=[asdict(p) for p in self.parameters],
                    prescribed_annual_harvest_tonnes=self.prescribed_annual_harvest, harvest_model=self.harvest_model,classification=self.classification_contract(),
                    inputs={name:array_identity(value) for name,value in
                        [('area',self.area),('zone',self.zone_index),('source_cell_ids',self.cell_ids),
                         ('mapped_stock',self.mapped),('stock_scale',self.scale)]})

    def draw(self, seed, iteration):
        result,parameters = self.realization(seed,iteration)
        return Draw({name:float(result.summary[name]) for name in METRICS},parameters)

    def realization(self, seed, iteration):
        """Return the same sampled annual result and parameter record used by MC."""
        inc = np.array([parameter_draw(p.increment_mean,p.increment_sd,seed,iteration,'increment/'+p.increment_group)
                        for p in self.parameters])
        cap = np.array([parameter_draw(p.capacity_mean,p.capacity_sd,seed,iteration,'capacity/'+p.capacity_group)
                        for p in self.parameters])
        kwargs = dict(seed=seed, iteration=iteration, stream=self.mode+'/'+self.source_identity,
                      dependence=self.dependence, acknowledged=True)
        if self.mode == 'agb':
            stock, diagnostic = sample_agb(self.mapped,self.scale,self.cell_ids,zero_policy=self.zero_policy,**kwargs)
            expected_stock_shift = diagnostic['expected_mean_shift']
        else:
            cover, diagnostic = sample_cover(self.mapped,self.scale,self.cell_ids,**kwargs)
            stock = stock_from_canopy(cover,cap[self.zone_index])
            expected_stock_shift = diagnostic['expected_mean_shift'] * cap[self.zone_index]
        prescribed_annual_harvest = self._sample_harvest(seed,iteration)
        classes=None
        if self.classification is not None:
            c=self.classification
            classes=c['model'].draw(c['mapped'],c['cell_ids'],seed,iteration)
        result = self._assess(stock,cap[self.zone_index],inc[self.zone_index],prescribed_annual_harvest,classes)
        parameters = dict(seed=seed,iteration=iteration,increment=inc.tolist(),reference_capacity=cap.tolist(),
                          parameter_names=[p.name for p in self.parameters],prescribed_annual_harvest_tonnes=prescribed_annual_harvest,
                          expected_boundary_stock_shift_tonnes=float(np.dot(expected_stock_shift,result.cells['area_ha'])),
                          spatial_sample_identity=array_identity(stock),
                          spatial_replay='Source-cell IDs, input hashes, seed, iteration and sampler code recorded by run contract')
        if classes is not None:
            parameters['classification']=dict(sampled_classes=classes.tolist(),
                class_cell_ids=self.classification['cell_ids'].tolist(),eligible_area_ha=result.summary['eligible_area_ha'])
        return result,parameters
