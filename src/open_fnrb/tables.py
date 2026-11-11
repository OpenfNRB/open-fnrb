# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared, strict CSV and Excel input contracts. No spreadsheet calculation engine."""
import csv
import math
from pathlib import Path

SCHEMAS = {
 'Harvest': ['assessment_id','mode','estimated_annual_harvest_tonnes','households','woody_biomass_use_tonnes_per_household_year','source'],
 'Parameters': ['zone_id','increment_mean','increment_sd','capacity_mean','capacity_sd','increment_group','capacity_group','source'],
 'Eligibility': ['class_code','eligible','source'],
 'Travel': ['assessment_id','round_trip_hours','travelling_share','speed_kmh','edge_tolerance_metres','source'],
 'AdminHouseholds': ['administrative_id','households','source'],
 'Observations': ['observation_id','annual_household_woody_biomass_use_tonnes','weight','unit_id','source'],
}


def number(value,field,*,positive=False):
    if isinstance(value,bool) or value in (None,''):
        raise ValueError(f'{field}: a number is required.')
    try:
        result = float(value)
    except (TypeError,ValueError):
        raise ValueError(f'{field}: invalid number.') from None
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError(f'{field}: finite {"positive" if positive else "nonnegative"} value required.')
    return result


def validate_rows(name,rows):
    if name not in SCHEMAS:
        raise ValueError('Unknown input table.')
    result,seen = [],set()
    for index,row in enumerate(rows,2):
        row = {k:(v.strip() if isinstance(v,str) else v) for k,v in row.items()}
        if set(row) != set(SCHEMAS[name]):
            raise ValueError(f'{name} row {index}: missing or unexpected fields.')
        if all(v in (None,'') for v in row.values()):
            continue
        if any(isinstance(v,str) and v.startswith('=') for v in row.values()):
            raise ValueError(f'{name} row {index}: supply values, not spreadsheet formulas.')
        for field in ('source',SCHEMAS[name][0]):
            if row[field] in (None,''):
                raise ValueError(f'{name} row {index}: {field} is required.')
        text_fields = ['source'] + ([] if name == 'Eligibility' else [SCHEMAS[name][0]])
        for field in text_fields:
            if not isinstance(row[field],str):
                raise ValueError(f'{field}: text is required; preserve identifier formatting.')
        if name == 'Eligibility':
            code = number(row['class_code'],'class_code')
            if code != int(code):
                raise ValueError('class_code must be an integer.')
            row['class_code'] = int(code)
            value = row['eligible']
            if type(value) is bool:
                pass
            elif isinstance(value,str) and value.lower() in ('true','false'):
                row['eligible'] = value.lower() == 'true'
            else:
                raise ValueError('eligible must explicitly be TRUE or FALSE.')
        elif name == 'Harvest':
            if row['mode'] == 'annual_total':
                row['estimated_annual_harvest_tonnes'] = number(row['estimated_annual_harvest_tonnes'],'estimated_annual_harvest_tonnes')
                if any(row[k] not in ('',None) for k in ('households','woody_biomass_use_tonnes_per_household_year')):
                    raise ValueError('Annual-total harvest must leave household fields blank.')
            elif row['mode'] == 'household_count':
                for field in ('households','woody_biomass_use_tonnes_per_household_year'):
                    row[field] = number(row[field],field)
                if row['estimated_annual_harvest_tonnes'] not in ('',None):
                    raise ValueError('Household-count harvest must leave annual total blank.')
            elif row['mode'] == 'built_up_allocation':
                row['woody_biomass_use_tonnes_per_household_year'] = number(row['woody_biomass_use_tonnes_per_household_year'],'woody_biomass_use_tonnes_per_household_year')
                if any(row[k] not in ('',None) for k in ('estimated_annual_harvest_tonnes','households')):
                    raise ValueError('Built-up allocation derives household count; leave total and count blank.')
            else:
                raise ValueError('Harvest mode must be annual_total, household_count or built_up_allocation.')
        elif name == 'Parameters':
            for field in ('increment_mean','increment_sd','capacity_mean','capacity_sd'):
                row[field] = number(row[field],field,positive=field.endswith('_mean'))
            for field in ('increment_group','capacity_group'):
                if not isinstance(row[field],str) or not row[field]:
                    raise ValueError(f'{field} is required; shared sources require shared IDs.')
        elif name == 'AdminHouseholds':
            row['households'] = number(row['households'],'households')
        elif name == 'Observations':
            row['annual_household_woody_biomass_use_tonnes'] = number(row['annual_household_woody_biomass_use_tonnes'],'annual_household_woody_biomass_use_tonnes')
            row['weight'] = number(row['weight'],'weight',positive=True)
            if not isinstance(row['unit_id'],str) or not row['unit_id']:
                raise ValueError('Explicit text survey unit_id required.')
        elif name == 'Travel':
            for field in ('round_trip_hours','travelling_share','speed_kmh','edge_tolerance_metres'):
                row[field] = number(row[field],field,positive=True)
            if row['travelling_share'] > 1:
                raise ValueError('travelling_share must be a fraction no greater than 1.')
            radius = row['round_trip_hours']*row['travelling_share']*row['speed_kmh']*500
            if row['edge_tolerance_metres'] >= radius:
                raise ValueError('Edge tolerance must be smaller than the travel radius.')
        key = row[SCHEMAS[name][0]]
        if key in seen:
            raise ValueError(f'{name}: duplicate identifier {key}.')
        seen.add(key)
        result.append({k:None if v == '' else v for k,v in row.items()})
    if not result:
        raise ValueError(f'{name}: no completed input rows.')
    if name == 'Parameters':
        groups = {}
        for row in result:
            for kind in ('increment','capacity'):
                key = (kind,row[kind+'_group'])
                moments = (row[kind+'_mean'],row[kind+'_sd'])
                if key in groups and groups[key] != moments:
                    raise ValueError('Shared parameter groups require identical moments.')
                groups[key] = moments
    return result


def read_table(path,name):
    path = Path(path)
    if name not in SCHEMAS:
        raise ValueError('Unknown input table.')
    if path.suffix.lower() == '.csv':
        with path.open(encoding='utf-8-sig',newline='') as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != SCHEMAS[name]:
                raise ValueError(f'{name}: headers must match the template exactly.')
            rows = list(reader)
    elif path.suffix.lower() == '.xlsx':
        from openpyxl import load_workbook
        workbook = load_workbook(path,read_only=True,data_only=False)
        try:
            if name not in workbook.sheetnames:
                raise ValueError(f'Missing worksheet {name}.')
            values = workbook[name].iter_rows(values_only=True)
            headers = list(next(values,()))
            if headers != SCHEMAS[name]:
                raise ValueError(f'{name}: headers must match the template exactly.')
            rows = [dict(zip(headers,row)) for row in values]
        finally:
            workbook.close()
    else:
        raise ValueError('Input tables must be CSV or XLSX.')
    return validate_rows(name,rows)
