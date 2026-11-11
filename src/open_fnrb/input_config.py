# SPDX-License-Identifier: GPL-3.0-or-later
"""Versioned file-based tabular intake and household harvest resolution."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
from .tables import read_table, number
from .gis_inputs import fingerprint
from .simulation import ZoneParameters
from .uncertainty import bootstrap_household_woody_biomass_use


def unique_object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON configuration key: {key}.')
        result[key] = value
    return result


def fields(value,required,optional=()):
    if not isinstance(value,dict) or not set(required) <= set(value) or set(value)-set(required)-set(optional):
        raise ValueError(f'Configuration requires {sorted(required)}; optional fields: {sorted(optional)}.')


@dataclass(frozen=True)
class TabularInputs:
    assessment_id: str
    tables: dict
    harvest_uncertainty: dict
    audit: dict

    def selected(self,table):
        rows = [r for r in self.tables[table] if r['assessment_id'] == self.assessment_id]
        if len(rows) != 1:
            raise ValueError(f'{table} must have one record for assessment {self.assessment_id}.')
        return rows[0]

    def parameters(self):
        return tuple(ZoneParameters(r['zone_id'],r['increment_mean'],r['increment_sd'],
                    r['capacity_mean'],r['capacity_sd'],r['increment_group'],r['capacity_group'])
                     for r in self.tables['Parameters'])

    def eligibility(self):
        return {r['class_code']:r['eligible'] for r in self.tables['Eligibility']}

    def resolve_harvest(self,*,allocations=None):
        """Resolve central harvest and the uncertainty adapter for Simulation.

        Built-up allocation records come from the spatial preparation layer and
        must match the supplied administrative totals. They remain in the audit.
        """
        row = self.selected('Harvest')
        mode = row['mode']
        if allocations is not None and mode != 'built_up_allocation':
            raise ValueError('Spatial household allocations supplied for a different harvest mode.')
        households = None
        if mode == 'annual_total':
            prescribed_annual_harvest = row['estimated_annual_harvest_tonnes']
        else:
            if mode == 'household_count':
                households = row['households']
            else:
                if allocations is None or 'AdminHouseholds' not in self.tables:
                    raise ValueError('Built-up harvest requires complete spatial allocations and administrative totals.')
                allocations = list(allocations)
                expected = {r['administrative_id']:r['households'] for r in self.tables['AdminHouseholds']}
                actual = [r['administrative_id'] for r in allocations]
                if len(set(actual)) != len(actual) or set(actual) != set(expected):
                    raise ValueError('Spatial allocation identifiers must match administrative household totals exactly.')
                for allocation in allocations:
                    total = expected[allocation['administrative_id']]
                    count = number(allocation['households_allocated'],'households_allocated')
                    if allocation['households_total'] != total or count > total:
                        raise ValueError('Spatial allocation does not match the supplied household total.')
                    full = number(allocation['full_support_m2'],'full_support_m2',positive=True)
                    inside = number(allocation['inside_support_m2'],'inside_support_m2')
                    if inside > full or not math.isclose(count,total*inside/full,rel_tol=1e-10,abs_tol=1e-10):
                        raise ValueError('Spatial household allocation does not reconcile with built-up support.')
                households = math.fsum(r['households_allocated'] for r in allocations)
            prescribed_annual_harvest = households*row['woody_biomass_use_tonnes_per_household_year']
        if not math.isfinite(prescribed_annual_harvest):
            raise ValueError('Annual harvest exceeds finite numeric range.')
        model = dict(self.harvest_uncertainty)
        if model['kind'] == 'lognormal':
            if prescribed_annual_harvest <= 0:
                raise ValueError('Lognormal harvest requires positive central harvest.')
        elif model['kind'] == 'household_bootstrap':
            if households is None:
                raise ValueError('Observation bootstrap requires household-based harvest.')
            obs = self.tables['Observations']
            values = [r['annual_household_woody_biomass_use_tonnes'] for r in obs]
            weights = [r['weight'] for r in obs]
            mean = math.fsum(x*w for x,w in zip(values,weights))/math.fsum(weights)
            if not math.isclose(mean,row['woody_biomass_use_tonnes_per_household_year'],rel_tol=1e-10,abs_tol=1e-10):
                raise ValueError('Central household woody biomass use must equal the weighted mean of supplied observations.')
            model.update(households=households,annual_household_woody_biomass_use_tonnes=values,
                         weights=weights,unit_ids=[r['unit_id'] for r in obs])
        return dict(prescribed_annual_harvest_tonnes=prescribed_annual_harvest,harvest_model=model,
                    audit=dict(harvest_input_record=row,households=households,allocations=allocations))


def load_tabular_config(path):
    """Resolve CSV/XLSX paths relative to a JSON file, with strict field names.

    This intake is the tabular section of the workflow. GIS configuration and
    run/export settings are not inferred from it.
    """
    path = Path(path).resolve(strict=True)
    config = json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=unique_object,
                        parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f'Invalid JSON number {x}.')))
    fields(config,{'schema_version','assessment_id','tables','harvest_uncertainty'})
    if type(config['schema_version']) is not int or config['schema_version'] != 2:
        raise ValueError('Unsupported tabular configuration schema version.')
    if not isinstance(config['assessment_id'],str) or not config['assessment_id'].strip():
        raise ValueError('A nonempty text assessment_id is required.')
    fields(config['tables'],{'Harvest','Parameters','Eligibility'},{'Travel','AdminHouseholds','Observations'})
    tables,files = {},{}
    for name,reference in config['tables'].items():
        if not isinstance(reference,str) or not reference:
            raise ValueError('Each table reference must be a CSV/XLSX path.')
        target = (path.parent/reference).resolve(strict=True)
        tables[name] = read_table(target,name)
        files[name] = fingerprint(target)
    model = config['harvest_uncertainty']
    if not isinstance(model,dict):
        raise ValueError('Explicit harvest uncertainty settings required.')
    kind = model.get('kind')
    if kind == 'fixed':
        fields(model,{'kind'})
    elif kind in ('lognormal','household_bootstrap'):
        fields(model,{'kind','source_id','acknowledged','sd' if kind == 'lognormal' else 'design'})
        if model['acknowledged'] is not True or not isinstance(model['source_id'],str) or not model['source_id'].strip():
            raise ValueError('Harvest uncertainty requires an acknowledgement and source identifier.')
        if kind == 'lognormal':
            model['sd'] = number(model['sd'],'annual harvest SD')
        else:
            if 'Observations' not in tables:
                raise ValueError('Household bootstrap requires an Observations table.')
            obs = tables['Observations']
            bootstrap_household_woody_biomass_use([r['annual_household_woody_biomass_use_tonnes'] for r in obs],seed=0,iteration=0,
                stream='input_validation',design=model['design'],unit_ids=[r['unit_id'] for r in obs],
                weights=[r['weight'] for r in obs],acknowledged=True)
    else:
        raise ValueError('Supported harvest uncertainty: fixed, lognormal or household_bootstrap.')
    if 'Observations' in tables and kind != 'household_bootstrap':
        raise ValueError('Observations table is present but not selected for bootstrap sampling.')
    result = TabularInputs(config['assessment_id'],tables,model,
                           dict(configuration=fingerprint(path),resolved_config=config,table_files=files))
    result.selected('Harvest')
    if 'Travel' in tables:
        result.selected('Travel')
    if result.selected('Harvest')['mode'] == 'built_up_allocation':
        if 'AdminHouseholds' not in tables:
            raise ValueError('Built-up allocation requires an AdminHouseholds table.')
    elif 'AdminHouseholds' in tables:
        raise ValueError('Administrative totals supplied for a different harvest mode.')
    if result.selected('Harvest')['mode'] != 'built_up_allocation':
        result.resolve_harvest()
    return result
