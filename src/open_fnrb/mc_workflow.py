# SPDX-License-Identifier: GPL-3.0-or-later
"""Monte Carlo execution and compatible restart from file-driven preparation."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import traceback
import uuid
import numpy as np
from .input_config import load_tabular_config,fields,unique_object
from .gis_inputs import fingerprint
from .workflow import run_nominal,write_json
from .simulation import Simulation,METRICS
from .monte_carlo import Settings,run
from .excel_report import export_excel


def verify_fingerprints(value,seen=None):
    """Check every referenced input/code/output fingerprint, once per file."""
    seen={} if seen is None else seen
    if isinstance(value,dict):
        if {'path','sha256','bytes'} <= set(value):
            path=value['path']
            if path not in seen:
                seen[path]=fingerprint(path)
            actual=seen[path]
            if actual['sha256']!=value['sha256'] or actual['bytes']!=value['bytes']:
                raise ValueError(f'Changed file prevents restart: {path}.')
        for child in value.values():verify_fingerprints(child,seen)
    elif isinstance(value,list):
        for child in value:verify_fingerprints(child,seen)


def load_sampling(path):
    path=Path(path).resolve(strict=True)
    config=json.loads(path.read_text(encoding='utf-8-sig'),object_pairs_hook=unique_object,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError(f'Invalid JSON number {x}.')))
    fields(config,{'schema_version','stock','parameters','settings'})
    if type(config['schema_version']) is not int or config['schema_version']!=1:
        raise ValueError('Unsupported Monte Carlo configuration version.')
    fields(config['stock'],{'dependence','zero_policy','acknowledged'})
    if config['stock']['acknowledged'] is not True:
        raise ValueError('Stock distribution/dependence assumptions require acknowledgement.')
    fields(config['parameters'],{'dependence','acknowledged'})
    if config['parameters']!={'dependence':'independent_shared_groups','acknowledged':True}:
        raise ValueError('Explicit acknowledgement of independent growth/capacity source-group draws required.')
    fields(config['settings'],{'seed','initial_iterations','extension_iterations','maximum_iterations','precision_target'},
           {'required_passes','checkpoint_interval'})
    settings=Settings(**config['settings']);settings.validate()
    return config,settings,fingerprint(path)


def simulation_from_nominal(directory,sampling):
    directory=Path(directory)
    record=json.loads((directory/'run_record.json').read_text(encoding='utf-8'))
    from .provenance import execution_identity
    if record.get('package_identity')!=execution_identity():
        raise ValueError('Execution mode or package identity differs from the recorded assessment.')
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    seen={};verify_fingerprints(record,seen);verify_fingerprints(manifest,seen)
    tabular=load_tabular_config(record['tabular']['configuration']['path'])
    harvest_inputs=record['harvest']
    stock=record['preparation']['stock_source']
    identity=json.dumps(dict(source=stock['source'],version=stock['version'],
                 hashes=[f['sha256'] for f in stock['files']]),sort_keys=True)
    class_model=record.get('classification_model')
    filename='classification_candidates.npz' if class_model is not None else 'prepared_nominal.npz'
    with np.load(directory/filename,allow_pickle=False) as arrays:
        classification=None
        if class_model is not None:
            from .classification import ClassificationModel
            model=ClassificationModel(tuple(class_model['codes']),tuple(tuple(r) for r in class_model['counts']),
                class_model['source_id'],class_model['evidence'])
            classification=dict(model=model,rules={int(k):v for k,v in class_model['rules'].items()},
                cell_ids=arrays['class_cell_id'],mapped=arrays['mapped_class'])
        simulation=Simulation(area=arrays['area_ha'],zone_index=arrays['zone_index'],
            source_cell_ids=arrays['source_cell_id'],mapped_stock=arrays['mapped_stock'],stock_scale=arrays['stock_uncertainty'],
            parameters=tabular.parameters(),stock_mode=record['resolved_config']['stock_mode'],
            dependence=sampling['stock']['dependence'],zero_policy=sampling['stock']['zero_policy'],
            prescribed_annual_harvest_tonnes=harvest_inputs['prescribed_annual_harvest_tonnes'],harvest_model=harvest_inputs['harvest_model'],
            uncertainty_acknowledged=True,source_identity=identity,
            uncertainty_interpretation=record['resolved_config']['uncertainty_interpretation'],classification=classification)
    saved=json.loads((directory/'nominal.json').read_text(encoding='utf-8'))
    reconstructed=simulation.nominal().summary
    if class_model is None:
        equivalent=reconstructed==saved
    else:
        # Candidate intersections may split nominal records; allow only rounding.
        equivalent=all(np.isclose(reconstructed[k],v,rtol=1e-10,atol=1e-10) if isinstance(v,(int,float)) and not isinstance(v,bool)
            else reconstructed[k]==v for k,v in saved.items())
    if not equivalent:
        raise ValueError('Reconstructed nominal calculation does not match the prepared run.')
    return simulation,record


def run_assessment(config_path,sampling_path,output,*,resume=False,stop_after=None,
                   maximum_scratch_bytes=20_000_000_000,cell_block_size=256,full_iteration_gis=False):
    """Nominal preparation followed by auditable MC. Incompatible resumes do not
    replace the previous top-level result, checkpoint or scientific contract.
    """
    if type(maximum_scratch_bytes) is not int or maximum_scratch_bytes<=0 or type(cell_block_size) is not int or cell_block_size<=0:
        raise ValueError('Positive integer scratch budget and cell block size required.')
    output=Path(output).resolve()
    if resume:
        if not output.is_dir():raise ValueError('No assessment directory to resume.')
    else:
        output.mkdir(parents=True,exist_ok=False)
    lock=output/'assessment.lock'
    descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    writer_token=uuid.uuid4().hex
    os.write(descriptor,json.dumps({'pid':os.getpid(),'token':writer_token}).encode());os.close(descriptor)
    def event(kind,**details):
        with (output/'attempts.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(dict(time=datetime.now(timezone.utc).isoformat(),event=kind,**details),allow_nan=False)+'\n')
    mc_status_before=None
    exporting=False
    try:
        event('resume_requested' if resume else 'started')
        # Once requested, retain the export obligation on subsequent resumes.
        request=output/'iteration_export_request.json'
        full_iteration_gis=bool(full_iteration_gis or request.exists())
        sampling,settings,sampling_file=load_sampling(sampling_path)
        config_file=fingerprint(config_path)
        contract_files=dict(workflow=config_file,sampling=sampling_file)
        if resume:
            saved=json.loads((output/'assessment.json').read_text(encoding='utf-8'))
            if saved['files']!=contract_files:
                raise ValueError('Changed workflow or sampling configuration; start a new assessment.')
            verify_fingerprints(saved)
        else:
            write_json(output/'assessment.json',dict(files=contract_files,sampling=sampling))
            write_json(output/'status.json',dict(status='preparing'))
            run_nominal(config_path,output/'nominal')
        simulation,record=simulation_from_nominal(output/'nominal',sampling)
        from .stock_diagnostics import export_cover_diagnostics
        export_cover_diagnostics(simulation, output)
        if full_iteration_gis and not request.exists():
            write_json(request,dict(full_iteration_gis=True))
        contract=dict(simulation=simulation.contract(),sampling=sampling,files=contract_files,
                      nominal_record=fingerprint(output/'nominal'/'run_record.json'),
                      nominal_arrays=fingerprint(output/'nominal'/'prepared_nominal.npz'))
        mc_status=output/'monte_carlo'/'status.json'
        mc_status_before=mc_status.read_bytes() if mc_status.exists() else None
        result=run(simulation.draw,settings=settings,contract=contract,metric_names=METRICS,
            fnrb_fields=['fnrb'],output=output/'monte_carlo',resume=resume,stop_after=stop_after)
        summary=dict(nominal=simulation.nominal().summary,monte_carlo=result,
            uncertainty_scope=('Conditional on selected distributions and independent native-cell resource classification; ecological zones and household allocation fixed'
                if simulation.classification is not None else 'Conditional on selected distributions, spatial dependence and fixed land-cover classes'),
            full_iteration_gis_requested=full_iteration_gis,
            pending_exports=['spatial Monte Carlo summaries']+(['full-iteration GIS'] if full_iteration_gis else []))
        export_excel(output/'summary.xlsx',summary['nominal'],record,mc=result,sampling=sampling,replace=resume)
        write_json(output/'summary.json',summary)
        if result['status'] in ('precision_met','precision_limit_reached'):
            exporting=True
            write_json(output/'status.json',dict(status='exporting',monte_carlo_status=result['status'],iterations=result['iterations']))
            event('spatial_export_started',maximum_scratch_bytes=maximum_scratch_bytes,cell_block_size=cell_block_size)
            spatial=complete_spatial_export(output,writer_token,maximum_scratch_bytes,cell_block_size)
            summary['spatial_export']=spatial
            summary['pending_exports']=['full-iteration GIS'] if full_iteration_gis else []
            write_json(output/'summary.json',summary)
            event('spatial_export_complete',directory=spatial['directory'])
            if full_iteration_gis:
                from .iteration_exports import export_all_iterations
                summary['iteration_export']=export_all_iterations(output,writer_token,event)
                summary['pending_exports']=[]
                write_json(output/'summary.json',summary)
        write_json(output/'status.json',dict(status=result['status'],iterations=result['iterations'],
            output_scope='nominal_and_monte_carlo_tables_excel_and_spatial_summaries' if exporting else 'nominal_gis_and_monte_carlo_tables_excel',pending_exports=summary['pending_exports']))
        event('returned',status=result['status'],iterations=result['iterations'])
        write_json(output/'manifest.json',dict(files=[fingerprint(p) for p in sorted(output.rglob('*'))
            if p.is_file() and p not in (output/'manifest.json',lock,output/'attempts.jsonl')],
            append_only_logs=['attempts.jsonl']))
        return summary
    except BaseException as error:
        event('resume_failed' if resume else 'failed',error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc())
        if exporting:
            write_json(output/'status.json',dict(status='export_failed',monte_carlo_status=result['status'],
                iterations=result['iterations'],error=str(error),pending_exports=summary['pending_exports']))
        elif not resume:
            write_json(output/'status.json',dict(status='failed',error=str(error)))
        elif mc_status_before is not None:
            current=output/'monte_carlo'/'status.json'
            if current.exists() and current.read_bytes()!=mc_status_before:
                state=json.loads(current.read_text())
                write_json(output/'status.json',dict(status=state['status'],
                    iterations=state['completed_iterations'],error=str(error)))
        raise
    finally:
        lock.unlink()


def complete_spatial_export(output,writer_token,maximum_scratch_bytes,cell_block_size):
    """Reuse a verified complete export or preserve failed attempts and retry.

    Scratch and block limits affect resources only and can change on resume.
    The simulation checkpoint and all completed draws remain unchanged.
    """
    from .spatial_summary import export_spatial_summary
    checkpoint=fingerprint(output/'monte_carlo'/'checkpoint.json')
    state_path=output/'spatial_export.json'
    if state_path.exists():
        state=json.loads(state_path.read_text())
        if state['source_checkpoint']==checkpoint:
            verify_fingerprints(state['manifest'])
            manifest=json.loads(Path(state['manifest']['path']).read_text())
            verify_fingerprints(manifest)
            return state
    parent=output/'spatial_exports';parent.mkdir(exist_ok=True)
    attempt=1
    while (parent/f'attempt_{attempt:04d}').exists():attempt+=1
    directory=parent/f'attempt_{attempt:04d}'
    export_spatial_summary(output,directory,maximum_scratch_bytes=maximum_scratch_bytes,
        cell_block_size=cell_block_size,_writer_token=writer_token)
    state=dict(directory=directory.relative_to(output).as_posix(),source_checkpoint=checkpoint,
        manifest=fingerprint(directory/'manifest.json'))
    write_json(state_path,state)
    return state
