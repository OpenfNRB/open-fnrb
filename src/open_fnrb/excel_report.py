# SPDX-License-Identifier: GPL-3.0-or-later
"""Populate the packaged Excel report layout using standard-library OOXML.

The workbook reports computed values; it neither calculates fNRB nor executes
user formulas. GIS and full-precision machine records remain the detailed audit.
"""
import math
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
from zipfile import ZipFile,ZIP_DEFLATED

TEMPLATE=Path(__file__).parent/'resources'/'summary_template.xlsx'
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
ET.register_namespace('',NS)


def unit(name):
    if name=='fnrb' or 'ratio' in name or name=='harvest_realisation_fraction':return 'fraction'
    if name.endswith('_tonnes'):return 't dry woody biomass'
    if name.endswith('_ha'):return 'ha'
    if name=='zero_prescribed_harvest':return 'flag'
    return 'text'


def label(name):
    if name=='fnrb':return 'fNRB'
    return name.replace('_',' ')


def sheet_rows(nominal,record,mc,sampling):
    summary=[(label(k),v if v is not None else 'Not applicable',unit(k),unit(k)=='fraction') for k,v in nominal.items()]
    uncertainty=[]
    if mc is None:
        uncertainty=[('Monte Carlo','Not requested',None,None,None,None,None,'',False)]
    else:
        for name,stats in mc['summaries'].items():
            uncertainty.append((label(name),nominal.get(name),stats['mean'],stats['median'],stats['standard_deviation'],stats['p10'],stats['p90'],unit(name),unit(name)=='fraction'))
        if not uncertainty:uncertainty=[('Monte Carlo','No completed draws',None,None,None,None,None,'',False)]
    inputs=[]
    for key in ('stock_source','uncertainty_source'):
        source=record['preparation'][key]
        inputs.append((label(key),source['source'],f"Version {source['version']}; date {source['date']}; units {source['units']}",False))
    for name,source in record['tabular']['table_files'].items():
        inputs.append((name,Path(source['path']).name,'SHA-256 '+source['sha256'],False))
    inputs.extend([
        ('Stock route',record['resolved_config']['stock_mode'],'Starting-stock method',False),
        ('Area method',record['preparation']['area_method'],'See run_record.json for CRS and native-grid support',False),
        ('Annual harvest estimate source',record['harvest']['audit']['harvest_input_record']['source'],'Household-use proxy requires documented sourcing assumptions',False)])
    if sampling:
        inputs.extend([('Stock dependence',sampling['stock']['dependence'],'Explicit scenario; not guaranteed uncertainty bounds',False),
                       ('Zero-stock policy',sampling['stock']['zero_policy'],'Explicit configured choice',False),
                       ('Parameter dependence',sampling['parameters']['dependence'],'Shared source groups; growth and capacity independent',False)])
    diagnostics=[
        ('Execution mode',record.get('package_identity',{}).get('mode','unrecorded'),
         'Research results are experimental; package verification is not methodological approval',False),
        ('Calculation period','One year','Concurrent logistic growth and uniform prescribed harvesting',False),
        ('Zero prescribed harvest',nominal['zero_prescribed_harvest'],'Zero fNRB is a reporting convention when harvest is zero',False),
        ('Prescribed annual harvest',nominal['prescribed_annual_harvest_tonnes'],'Prescribed annual harvest, including unrealised harvest',False),
        ('Unrealised harvest',nominal['unrealised_harvest_tonnes'],'Not transferred automatically to other source cells',False),
        ('Capacity-adjusted area',nominal['adjusted_capacity_area_ha'],'Hectares where initial stock exceeded reference capacity',False),
        ('Run record','nominal/run_record.json' if mc is not None else 'run_record.json','Complete inputs, assumptions, runtime and source fingerprints',False),
        ('Land-cover uncertainty','Sampled resource eligibility' if mc is not None and record.get('classification_model') else 'Fixed',
         'Ecological zones and household allocation remain fixed; matrix uncertainty is not sampled' if mc is not None and record.get('classification_model') else 'No classification sampling in these results',False)]
    if record.get('classification_model'):
        evidence=record['classification_model']['evidence']
        inputs.append(('Classification matrix',Path(evidence['matrix']['path']).name,
            evidence['source_id']+'; SHA-256 '+evidence['matrix']['sha256'],False))
    if mc:
        diagnostics.extend([
            ('Monte Carlo status',mc['status'],'precision_limit_reached means the target was not met; interrupted means partial results',False),
            ('Completed iterations',mc['iterations'],'All completed draws are retained',False),
            ('P10–P90','Central 80% of sampled outcomes','Conditional on model and inputs; not complete uncertainty coverage',False),
            ('No-household woody biomass use draw fraction',mc['summaries'].get('zero_prescribed_harvest',{}).get('mean','Not available'),'Included in fNRB summaries using the agreed zero-harvest convention',True)])
        if sampling:
            diagnostics.extend([('Random seed',sampling['settings']['seed'],'Reproduction also requires recorded code and inputs',False),
                ('Precision target',sampling['settings']['precision_target'],'Absolute fNRB numerical precision target',False)])
        for item in mc['precision_history']:
            diagnostics.append((f"Precision check at {item['iterations']} draws",item['checks']['fnrb']['passed'],
                                f"Consecutive passing checks: {item['consecutive_passes']}",False))
    else:
        diagnostics.append(('Uncertainty','Not assessed','Nominal-only results do not include uncertainty statistics',False))
    return {'Summary':summary,'Uncertainty':uncertainty,'Inputs':inputs,'Diagnostics':diagnostics}


def _cell(reference,value,style):
    cell=ET.Element(f'{{{NS}}}c',{'r':reference,'s':style})
    if value is None:return cell
    if isinstance(value,bool):
        cell.set('t','b');ET.SubElement(cell,f'{{{NS}}}v').text='1' if value else '0'
    elif isinstance(value,(int,float)):
        if not math.isfinite(value):raise ValueError('Nonfinite Excel report value.')
        ET.SubElement(cell,f'{{{NS}}}v').text=repr(value)
    else:
        text=str(value)
        if len(text)>32767:raise ValueError('Excel report cell exceeds the text limit.')
        cell.set('t','inlineStr');inline=ET.SubElement(cell,f'{{{NS}}}is')
        ET.SubElement(inline,f'{{{NS}}}t').text=text
    return cell


def export_excel(path,nominal,record,*,mc=None,sampling=None,replace=False):
    """Write a typed, formula-free summary; replacement is explicit for resume."""
    path=Path(path)
    if path.exists() and not replace:raise FileExistsError(path)
    rows=sheet_rows(nominal,record,mc,sampling)
    with ZipFile(TEMPLATE) as source:
        contents={item.filename:source.read(item.filename) for item in source.infolist()}
    for index,(name,records) in enumerate(rows.items(),1):
        key=f'xl/worksheets/sheet{index}.xml';root=ET.fromstring(contents[key])
        data=root.find(f'{{{NS}}}sheetData')
        styles={}
        for row in list(data):
            if row.get('r') in ('7','8'):
                styles[row.get('r')]={''.join(filter(str.isalpha,c.get('r'))):c.get('s','0') for c in row}
            if int(row.get('r'))>=7:data.remove(row)
        for i,record_row in enumerate(records,7):
            values,percentage=record_row[:-1],record_row[-1]
            height='48' if name in ('Inputs','Diagnostics') else '28'
            row=ET.SubElement(data,f'{{{NS}}}row',{'r':str(i),'ht':height,'customHeight':'1'})
            for col,value in enumerate(values,1):
                letter=chr(64+col)
                percent=percentage and col>1 and col<len(values) and isinstance(value,(int,float)) and not isinstance(value,bool)
                style=styles['8' if percent else '7'].get(letter,'0')
                if isinstance(value,(bool,int)) and not percent:
                    style=styles['7'].get('A','0')
                row.append(_cell(f'{letter}{i}',value,style))
        last_col='H' if name=='Uncertainty' else 'C'
        dimension=root.find(f'{{{NS}}}dimension')
        if dimension is None:
            dimension=ET.Element(f'{{{NS}}}dimension')
            # OOXML places dimension immediately after optional sheetPr.
            root.insert(1 if root.find(f'{{{NS}}}sheetPr') is not None else 0,dimension)
        dimension.set('ref',f'A1:{last_col}{max(6,len(records)+6)}')
        contents[key]=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    # Atomic replacement keeps an interrupted refresh from corrupting a report.
    fd,temp=tempfile.mkstemp(prefix='.summary-',suffix='.xlsx',dir=path.parent);os.close(fd)
    try:
        with ZipFile(temp,'w',ZIP_DEFLATED) as dest:
            for name,data in contents.items():dest.writestr(name,data)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return path
