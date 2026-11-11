# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact native-cell MC summaries reconstructed from verified completed draws."""
import csv
import json
from pathlib import Path
import shutil
import tempfile
import traceback
import numpy as np
from shapely import from_wkt
from shapely.ops import unary_union
from .replay import verified_assessment
from .workflow import write_json
from .gis_inputs import fingerprint,spatial_reference
from .gis_exports import write_raster,write_polygons


def export_spatial_summary(assessment,output,*,maximum_scratch_bytes=20_000_000_000,cell_block_size=256,_writer_token=None):
    """Aggregate fragments per native cell BEFORE summarising sampled outcomes.

    Exact P10/median/P90 use temporary disk-backed draws and bounded cell blocks.
    All completed draws are included. Interrupted/failed runs are rejected;
    precision-limit results retain that limitation explicitly.
    """
    assessment=Path(assessment).resolve(strict=True);output=Path(output).resolve()
    if output.is_relative_to(assessment) and (_writer_token is None or output.parent!=assessment/'spatial_exports'):
        raise ValueError('Spatial summary output must be outside the assessment.')
    output.mkdir(parents=True,exist_ok=False)
    def event(step,**details):
        with (output/'events.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(step=step,**details),allow_nan=False)+'\n')
    write_json(output/'status.json',dict(status='validating'))
    try:
        if type(maximum_scratch_bytes) is not int or maximum_scratch_bytes<=0 or type(cell_block_size) is not int or cell_block_size<=0:
            raise ValueError('Positive integer scratch budget and cell block size required.')
        simulation,record,identity,payload=verified_assessment(assessment,_writer_token=_writer_token)
        if payload['status'] not in ('precision_met','precision_limit_reached'):
            raise ValueError('Spatial summaries require a completed Monte Carlo run.')
        checkpoint=fingerprint(assessment/'monte_carlo'/'checkpoint.json')
        count=len(payload['rows'])
        if count<2:raise ValueError('At least two completed iterations are required.')
        source_ids,inverse=np.unique(simulation.cell_ids,return_inverse=True)
        area=np.bincount(inverse,weights=simulation.area,minlength=len(source_ids))
        names=[n for n in simulation.nominal().cells if n!='area_ha']
        required=count*len(source_ids)*len(names)*8
        if required>maximum_scratch_bytes or required>shutil.disk_usage(output).free*.9:
            raise ValueError(f'Exact spatial percentiles require {required} scratch bytes; budget or free space is insufficient.')
        metadata=record['preparation'];shape=tuple(metadata['shape']);affine=metadata['transform']
        r0,c0=metadata['source_origin'];width=metadata['source_shape'][1]
        rr=source_ids//width-r0;cc=source_ids%width-c0
        crs=spatial_reference(record['crs_wkt']);layers=[]
        stats_names=('mean','median','standard_deviation','p10','p90')
        area_name='candidate_area_ha' if simulation.classification is not None else 'area_ha'
        support_label='fixed candidate area' if simulation.classification is not None else 'eligible area'
        columns={'source_cell_id':source_ids,area_name:area}
        units={'source_cell_id':'identifier',area_name:'ha'}
        event('reconstructing',iterations=count,native_cells=len(source_ids),scratch_bytes=required)
        with tempfile.TemporaryDirectory(prefix='spatial_samples_',dir=output) as scratch:
            data=np.memmap(Path(scratch)/'draws.bin',dtype='float64',mode='w+',
                           shape=(len(names),len(source_ids),count)) if required else None
            try:
                for iteration in range(count):
                    result,parameters=simulation.realization(identity['settings']['seed'],iteration)
                    if [float(result.summary[n]) for n in identity['metric_names']]!=payload['rows'][iteration] or parameters!=payload['parameters'][iteration]:
                        raise ValueError(f'Exact replay verification failed at iteration {iteration}.')
                    for m,name in enumerate(names):
                        if data is not None:
                            data[m,:,iteration]=np.bincount(inverse,weights=result.cells[name]*simulation.area,minlength=len(source_ids))
                    if (iteration+1)%100==0:event('replayed',iterations=iteration+1)
                if data is not None:data.flush()
                gis=output/'gis';gis.mkdir()
                for m,name in enumerate(names):
                    summaries={stat:np.empty(len(source_ids)) for stat in stats_names}
                    for lo in range(0,len(source_ids),cell_block_size):
                        hi=min(lo+cell_block_size,len(source_ids));block=np.array(data[m,lo:hi,:],copy=True)
                        q=np.quantile(block,[.1,.5,.9],axis=1)
                        summaries['mean'][lo:hi]=block.mean(axis=1)
                        summaries['standard_deviation'][lo:hi]=block.std(axis=1,ddof=1)
                        summaries['p10'][lo:hi],summaries['median'][lo:hi],summaries['p90'][lo:hi]=q
                    density_unit='fraction' if name in ('active_year_fraction','eligible_fraction') else ('t_dry_matter/ha/year' if name=='peak_increment_t_ha_year' else 't_dry_matter/ha')
                    for stat,values in summaries.items():
                        field=name+'_'+stat;density=values/area
                        columns[field]=density;units[field]=density_unit
                        grid=np.full(shape,np.nan);grid[rr,cc]=density
                        layers.append(write_raster(gis/(field+'.tif'),grid,affine,crs,units=density_unit,
                            support=f'{stat} across {count} draws of resource contribution per {support_label}; ineligible records contribute zero; fragments aggregated within each draw'))
                        if name=='eligible_fraction':
                            eligible_field='eligible_area_ha_'+stat
                            columns[eligible_field]=values;units[eligible_field]='ha'
                            total=np.full(shape,np.nan);total[rr,cc]=values
                            layers.append(write_raster(gis/(eligible_field+'.tif'),total,affine,crs,units='ha',support=f'{stat} of sampled eligible area within each native stock cell'))
                        if name not in ('active_year_fraction','eligible_fraction'):
                            total=np.full(shape,np.nan);total[rr,cc]=values
                            layers.append(write_raster(gis/(field+'_total.tif'),total,affine,crs,
                                units='t_dry_matter/year' if name=='peak_increment_t_ha_year' else 't_dry_matter',
                                support=f'{stat} across {count} draws of native-cell totals; percentile totals are not additive across cells'))
                with (assessment/'nominal'/simulation.geometry_filename).open(newline='',encoding='utf-8') as f:
                    geometry_rows=list(csv.DictReader(f))
                if len(geometry_rows)!=len(simulation.area):raise ValueError('Prepared geometry count mismatch.')
                groups=[[] for _ in source_ids]
                for i,row in enumerate(geometry_rows):
                    if int(row['record_id'])!=i or int(row['source_cell_id'])!=simulation.cell_ids[i]:
                        raise ValueError('Prepared geometry identity mismatch.')
                    groups[inverse[i]].append(from_wkt(row['geometry_wkt']))
                geometries=[unary_union(group) for group in groups]
                layers.append(write_polygons(gis/'spatial_uncertainty.shp',geometries,columns,crs,units=units))
                with (output/'spatial_uncertainty.csv').open('w',newline='',encoding='utf-8') as f:
                    writer=csv.writer(f);writer.writerow(columns)
                    for i in range(len(source_ids)):writer.writerow([v[i] for v in columns.values()])
                np.savez_compressed(output/'spatial_uncertainty.npz',**columns)
            finally:
                if data is not None:
                    data.flush();data._mmap.close();del data
        if fingerprint(assessment/'monte_carlo'/'checkpoint.json')!=checkpoint:
            raise ValueError('Assessment checkpoint changed during spatial reconstruction.')
        write_json(output/'gis'/'layers.json',dict(layers=layers,crs_wkt=record['crs_wkt']))
        summary=dict(status='complete',iterations=count,source_status=payload['status'],verification='all_iterations_exact',
            source_checkpoint=checkpoint,source_run=fingerprint(assessment/'monte_carlo'/'run.json'),
            statistics=list(stats_names),native_cells=len(source_ids),scratch_bytes=required,
            area_support=support_label,
            interpretation='Conditional eligible-resource contributions, including zero contribution when sampled ineligible; not total physical landscape biomass. No pixel-level fNRB. Cell percentiles and standard deviations must not be summed to estimate assessment uncertainty.')
        write_json(output/'summary.json',summary);event('complete',iterations=count)
        write_json(output/'status.json',dict(status='complete',source_status=payload['status']))
        write_json(output/'manifest.json',dict(files=[fingerprint(p) for p in sorted(output.rglob('*')) if p.is_file()]))
        return summary
    except BaseException as error:
        event('failed',error_type=type(error).__name__,message=str(error))
        write_json(output/'status.json',dict(status='failed',error=str(error)))
        write_json(output/'failure.json',dict(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc()))
        raise
