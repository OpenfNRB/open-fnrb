# SPDX-License-Identifier: GPL-3.0-or-later
"""Explicit conditional class probabilities and candidate resource support."""
import csv
from dataclasses import dataclass
import math
from pathlib import Path
import numpy as np
from shapely import STRtree
from .annual import assess_year,stock_from_canopy
from .gis_inputs import fingerprint,prepare_raster_pair
from .preparation import Support
from .uncertainty import sample_classes


@dataclass(frozen=True)
class ClassificationModel:
    codes: tuple
    counts: tuple
    source_id: str
    evidence: dict

    def draw(self,mapped,cell_ids,seed,iteration):
        return sample_classes(mapped,self.codes,self.counts,cell_ids,seed=seed,iteration=iteration,
            stream='classification/'+self.source_id,acknowledged=True)


def load_classification_matrix(path,*,source_id,orientation,dependence,acknowledged):
    """Load a complete long-form matrix, with mapped rows and reference columns.

    Counts must support P(reference class | mapped class). Transposition or
    correction for a validation sampling design is never inferred here.
    """
    if acknowledged is not True or orientation!='mapped_rows_reference_columns' or dependence!='independent_native_cells':
        raise ValueError('Acknowledge mapped-row conditional probabilities and independent native-class-cell draws.')
    if not isinstance(source_id,str) or not source_id.strip():
        raise ValueError('Classification source/evidence identity required.')
    path=Path(path).resolve(strict=True)
    headers=['mapped_class','reference_class','count']
    if path.suffix.lower()=='.xlsx':
        from openpyxl import load_workbook
        workbook=load_workbook(path,read_only=True,data_only=False)
        try:
            if 'ClassificationMatrix' not in workbook.sheetnames:raise ValueError('ClassificationMatrix worksheet required.')
            rows=[]
            for cells in workbook['ClassificationMatrix'].iter_rows():
                if any(cell.data_type=='f' for cell in cells):raise ValueError('Matrix values must not be formulas.')
                values=[cell.value for cell in cells]
                while values and values[-1] is None:values.pop()
                if values:rows.append(values)
            if not rows or rows[0]!=headers:raise ValueError('Matrix headers must be mapped_class,reference_class,count.')
            if any(len(row)!=3 for row in rows[1:]):raise ValueError('Malformed classification matrix row.')
            records=[dict(zip(headers,row)) for row in rows[1:]]
        finally:workbook.close()
    elif path.suffix.lower()=='.csv':
        with path.open(newline='',encoding='utf-8-sig') as handle:
            reader=csv.DictReader(handle)
            if reader.fieldnames!=headers:raise ValueError('Matrix CSV requires mapped_class,reference_class,count columns in that order.')
            records=list(reader)
    else:raise ValueError('Classification matrix must be CSV or XLSX.')
    entries={}
    for row in records:
            if None in row or any(v is None for v in row.values()):raise ValueError('Malformed classification matrix row.')
            try:
                mapped,reference=int(row['mapped_class']),int(row['reference_class'])
                count=float(row['count'])
            except (ValueError,TypeError) as error:
                raise ValueError('Integer class codes and finite nonnegative counts required.') from error
            if any(isinstance(row[k],bool) for k in headers) or any(isinstance(row[k],float) and not row[k].is_integer() for k in headers[:2]):
                raise ValueError('Integer class codes and numeric counts required; booleans are not counts.')
            if min(mapped,reference)<0:raise ValueError('Nonnegative class codes required.')
            if not math.isfinite(count) or count<0 or (mapped,reference) in entries:
                raise ValueError('Duplicate matrix entry or invalid count.')
            entries[mapped,reference]=count
    codes=tuple(sorted({c for pair in entries for c in pair}))
    if not codes or len(entries)!=len(codes)**2:
        raise ValueError('Supply every class pair, including explicit zero counts.')
    counts=tuple(tuple(entries[a,b] for b in codes) for a in codes)
    sample_classes(np.array(codes),codes,counts,np.arange(len(codes)),seed=0,iteration=0,stream='validation',acknowledged=True)
    return ClassificationModel(codes,counts,source_id,dict(matrix=fingerprint(path),orientation=orientation,
        dependence=dependence,acknowledged=True,source_id=source_id,
        interpretation='Row-normalized conditional probabilities; matrix-estimation uncertainty is not sampled'))


@dataclass(frozen=True)
class ClassificationSupport:
    prepared: Support
    class_cell_ids: np.ndarray
    mapped_classes: np.ndarray
    nominal_eligible: np.ndarray


def prepare_classification_support(*,classes,model,rules,area_measure,**raster_arguments):
    """Prepare every nonexcluded area that is eligible now or could become so.

    Ecological-zone parameters and household harvest remain fixed by this
    component. Class sampling changes resource eligibility only.
    """
    if any(type(code) is not int or type(flag) is not bool for code,flag in rules.items()):
        raise ValueError('Explicit integer-class eligibility rules required.')
    if not set(model.codes)<=set(rules):raise ValueError('Eligibility rules must cover every possible reference class.')
    if any(c['class_code'] not in model.codes for c in classes.cells):
        raise ValueError('Matrix must cover every mapped class in the domain.')
    possible={code:rules[code] or any(count>0 and rules[target] for target,count in zip(model.codes,row))
              for code,row in zip(model.codes,model.counts)}
    candidates=[c for c in classes.cells if possible[c['class_code']]]
    base=prepare_raster_pair(**raster_arguments,eligibility=[c['geometry'] for c in candidates])
    if base.audit['area_method']!=area_measure.method:
        raise ValueError('Candidate splitting must use the prepared grid area measure.')
    geometries=[c['geometry'] for c in candidates]
    tree=STRtree(geometries)
    records=[]
    for index,geometry in enumerate(base.geometries):
        for match in sorted(tree.query(geometry)):
            cell=candidates[int(match)];part=geometry.intersection(cell['geometry'])
            if part.area>0:
                records.append((area_measure(part)/10000,index,part,cell['source_cell_id'],cell['class_code']))
    area=np.array([r[0] for r in records],float)
    indices=np.array([r[1] for r in records],dtype=np.int64)
    if not math.isclose(float(area.sum()),float(base.area_ha.sum()),rel_tol=1e-9,abs_tol=1e-10):
        raise ValueError('Candidate class intersections do not reconcile with prepared area.')
    ids=np.array([r[3] for r in records],dtype=np.int64)
    mapped=np.array([r[4] for r in records],dtype=np.int64)
    nominal=np.array([rules[int(c)] for c in mapped],dtype=bool)
    arrays=[area,base.source_cell_ids[indices],base.zone_index[indices],base.mapped_stock[indices],base.stock_scale[indices]]
    for a in (*arrays,ids,mapped,nominal):a.flags.writeable=False
    audit=dict(base.audit,records=len(records),support_role='potential resource; not nominal eligible area',
        classification=model.evidence,nominal_eligible_area_ha=float(area[nominal].sum()),
        candidate_area_ha=float(area.sum()))
    return ClassificationSupport(Support(*arrays,tuple(r[2] for r in records),audit),ids,mapped,nominal)


def assess_classified_year(support,model,rules,*,seed,iteration,stock_mode,mapped_stock,
                           reference_capacity,peak_increment,prescribed_annual_harvest_tonnes):
    """Calculate using sampled eligible hectares; return selected record IDs.

    Stock/growth uncertainty can be supplied as already sampled vectors. Shared
    class-cell IDs ensure all fragments of a classification cell draw together.
    """
    classes=model.draw(support.mapped_classes,support.class_cell_ids,seed,iteration)
    if not set(model.codes)<=set(rules) or any(type(rules[c]) is not bool for c in model.codes):
        raise ValueError('Boolean eligibility rules required for every matrix class.')
    selected=np.array([rules[int(c)] for c in classes],dtype=bool)
    shape=support.prepared.area_ha.shape
    values=[np.asarray(v,float) for v in (mapped_stock,reference_capacity,peak_increment)]
    if any(v.shape!=shape or np.any(~np.isfinite(v)) for v in values):
        raise ValueError('Sampled stock and parameter vectors must match all candidate records.')
    stock,capacity,increment=values
    if np.any(stock<0) or np.any(capacity<=0) or np.any(increment<0):
        raise ValueError('Invalid sampled stock or parameters on candidate resource.')
    if stock_mode=='canopy':stock=stock_from_canopy(stock,capacity)
    elif stock_mode!='agb':raise ValueError('Supported stock route required.')
    result=assess_year(support.prepared.area_ha[selected],stock[selected],capacity[selected],increment[selected],prescribed_annual_harvest_tonnes)
    return result,dict(record_indices=np.flatnonzero(selected).tolist(),sampled_classes=classes.tolist(),
        classification_cell_ids=support.class_cell_ids.tolist(),scope='resource eligibility only; zones and household allocation fixed')
