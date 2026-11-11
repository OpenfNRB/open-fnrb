# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproduce a completed Monte Carlo iteration without changing its assessment."""
import csv
import hashlib
import json
import platform
from pathlib import Path
import traceback
import numpy as np
from shapely import from_wkt
from .monte_carlo import digest
from .mc_workflow import simulation_from_nominal,verify_fingerprints
from .gis_inputs import fingerprint,spatial_reference
from .gis_exports import write_raster,write_polygons
from .workflow import write_json


def verified_assessment(assessment,*,_writer_token=None):
    assessment=Path(assessment).resolve(strict=True)
    lock=assessment/'assessment.lock'
    owned=(_writer_token is not None and lock.exists() and
           json.loads(lock.read_text()).get('token')==_writer_token)
    if (lock.exists() and not owned) or (assessment/'monte_carlo'/'run.lock').exists():
        raise ValueError('Assessment is locked; replay a completed checkpoint after its writer stops.')
    mc=assessment/'monte_carlo'
    identity=json.loads((mc/'run.json').read_text())
    checkpoint=json.loads((mc/'checkpoint.json').read_text())
    payload=checkpoint['payload']
    if checkpoint['sha256']!=digest(payload) or payload['identity']!=digest(identity):
        raise ValueError('Checkpoint or run identity integrity check failed.')
    source=Path(__file__).parent
    hashes={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.rglob('*.py'))}
    if hashes!=identity['code']:
        raise ValueError('Replay requires the recorded software version.')
    import scipy
    runtime=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,
                 system=platform.system(),machine=platform.machine())
    if runtime!=identity['runtime']:
        raise ValueError('Replay requires the recorded numerical runtime.')
    verify_fingerprints(identity['contract'])
    if len(payload['rows'])!=len(payload['parameters']):
        raise ValueError('Checkpoint record counts disagree.')
    sampling=identity['contract']['sampling']
    simulation,record=simulation_from_nominal(assessment/'nominal',sampling)
    if simulation.contract()!=identity['contract']['simulation']:
        raise ValueError('Reconstructed simulation differs from its recorded contract.')
    return simulation,record,identity,payload


def replay_iteration(assessment,iteration,output,*,gis=False,_writer_token=None,_verified=None):
    assessment=Path(assessment).resolve(strict=True)
    output=Path(output).resolve()
    if output.is_relative_to(assessment) and (_writer_token is None or not output.is_relative_to(assessment/'iteration_exports')):
        raise ValueError('Replay output must be separate from the original assessment.')
    output.mkdir(parents=True,exist_ok=False)
    write_json(output/'status.json',dict(status='validating',iteration=iteration))
    try:
        if type(iteration) is not int or iteration<0:
            raise ValueError('Iteration must be a nonnegative zero-based index.')
        if _verified is not None and _writer_token is None:
            raise ValueError('Cached verification requires the assessment writer.')
        simulation,record,identity,payload=(_verified if _verified is not None else
            verified_assessment(assessment,_writer_token=_writer_token))
        mc=assessment/'monte_carlo'
        if iteration>=len(payload['rows']):
            raise ValueError('Requested iteration was not completed in this checkpoint.')
        result,parameters=simulation.realization(identity['settings']['seed'],iteration)
        metrics=[float(result.summary[name]) for name in identity['metric_names']]
        if metrics!=payload['rows'][iteration] or parameters!=payload['parameters'][iteration]:
            raise ValueError('Replayed metrics or parameter draws differ from the saved iteration.')
        arrays=dict(source_cell_id=simulation.cell_ids,zone_index=simulation.zone_index,**result.cells)
        if simulation.classification is not None:
            arrays.update(candidate_area_ha=simulation.area,class_cell_id=simulation.classification['cell_ids'],
                mapped_class=simulation.classification['mapped'],sampled_class=np.array(parameters['classification']['sampled_classes'],dtype=np.int64))
        np.savez_compressed(output/'iteration_cells.npz',**arrays)
        with (output/'iteration_cells.csv').open('w',newline='',encoding='utf-8') as handle:
            writer=csv.writer(handle);writer.writerow(['record_id',*arrays])
            for i in range(len(simulation.area)):
                writer.writerow([i,*[a[i] for a in arrays.values()]])
        write_json(output/'iteration.json',dict(iteration=iteration,seed=identity['settings']['seed'],
                    result=result.summary,parameters=parameters,verification='exact',
                    source_checkpoint=fingerprint(mc/'checkpoint.json'),source_run=fingerprint(mc/'run.json')))
        layers=[]
        if gis:
            directory=output/'gis';directory.mkdir()
            if simulation.classification is not None:
                with (assessment/'nominal'/'classification_cells.csv').open(newline='',encoding='utf-8') as handle:
                    class_records=list(csv.DictReader(handle))
                class_ids=np.array([int(r['source_cell_id']) for r in class_records],dtype=np.int64)
                mapped=np.array([int(r['class_code']) for r in class_records],dtype=np.int64)
                sampled=simulation.classification['model'].draw(mapped,class_ids,identity['settings']['seed'],iteration)
                source=record['classification']['source'];c,r,w,h=record['classification']['native_window'];t=source['transform']
                affine=(t[0]+c*t[1]+r*t[2],t[1],t[2],t[3]+c*t[4]+r*t[5],t[4],t[5])
                grid=np.full((h,w),np.nan)
                grid[class_ids//source['shape'][1]-r,class_ids%source['shape'][1]-c]=sampled
                layers.append(write_raster(directory/'sampled_class.tif',grid,affine,spatial_reference(source['crs_wkt']),
                    units='class_code',support='Sampled reference class on the original classification grid; domain-intersecting cells'))
                write_json(output/'classification_draw.json',dict(source_cell_ids=class_ids.tolist(),mapped_classes=mapped.tolist(),sampled_classes=sampled.tolist()))
            metadata=record['preparation'];shape=tuple(metadata['shape']);transform=metadata['transform']
            row0,col0=metadata['source_origin'];width=metadata['source_shape'][1]
            rows=simulation.cell_ids//width-row0;cols=simulation.cell_ids%width-col0
            area=np.zeros(shape);np.add.at(area,(rows,cols),simulation.area)
            crs=spatial_reference(record['crs_wkt'])
            eligible=np.zeros(shape);np.add.at(eligible,(rows,cols),result.cells['area_ha'])
            layers.append(write_raster(directory/'eligible_area.tif',np.where(area>0,eligible,np.nan),
                        transform,crs,units='ha',support='Sum of eligible fragments per native stock cell'))
            support_label='candidate-area' if simulation.classification is not None else 'eligible-area'
            if simulation.classification is not None:
                layers.append(write_raster(directory/'candidate_area.tif',np.where(area>0,area,np.nan),transform,crs,units='ha',support='Fixed potential resource area'))
            units={}
            for name,values in result.cells.items():
                if name=='area_ha':continue
                unit='fraction' if name in ('active_year_fraction','eligible_fraction') else ('t_dry_matter/ha/year' if name=='peak_increment_t_ha_year' else 't_dry_matter/ha')
                units[name]=unit
                total=np.zeros(shape);np.add.at(total,(rows,cols),values*simulation.area)
                density=np.full(shape,np.nan);np.divide(total,area,out=density,where=area>0)
                layers.append(write_raster(directory/(name+'.tif'),density,transform,crs,units=unit,
                    support=f'Iteration {iteration}: {support_label}-weighted resource contribution across native-cell fragments; zero contribution on sampled ineligible records'))
                if name not in ('active_year_fraction','eligible_fraction'):
                    layers.append(write_raster(directory/(name+'_total.tif'),np.where(area>0,total,np.nan),transform,crs,
                        units='t_dry_matter/year' if name=='peak_increment_t_ha_year' else 't_dry_matter',
                        support=f'Iteration {iteration}: sum across eligible fragments in each native stock cell'))
            with (assessment/'nominal'/simulation.geometry_filename).open(encoding='utf-8',newline='') as handle:
                records=list(csv.DictReader(handle))
            if len(records)!=len(simulation.area) or any(int(r['record_id'])!=i for i,r in enumerate(records)):
                raise ValueError('Prepared geometry records do not match the replayed array order.')
            layers.append(write_polygons(directory/'iteration_records.shp',[from_wkt(r['geometry_wkt']) for r in records],
                    dict(record_id=np.arange(len(records)),**arrays),crs,units=dict(units,area_ha='ha',candidate_area_ha='ha')))
            write_json(directory/'layers.json',dict(iteration=iteration,layers=layers,crs_wkt=record['crs_wkt'],
                      note='Eligible-resource contributions; zeros on ineligible candidate records do not mean zero physical biomass. These are not pixel-level fNRB indicators.'))
        summary=dict(status='replayed',iteration=iteration,verification='exact',fnrb=result.summary['fnrb'],gis=gis)
        write_json(output/'status.json',summary)
        write_json(output/'manifest.json',dict(files=[fingerprint(p) for p in sorted(output.rglob('*')) if p.is_file()]))
        return summary
    except BaseException as error:
        write_json(output/'status.json',dict(status='failed',iteration=iteration,error=str(error)))
        write_json(output/'failure.json',dict(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc()))
        raise
