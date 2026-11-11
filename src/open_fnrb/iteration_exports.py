# SPDX-License-Identifier: GPL-3.0-or-later
"""Recoverable GIS export of every completed draw, without resampling."""
import json
from .gis_inputs import fingerprint
from .mc_workflow import verify_fingerprints
from .replay import verified_assessment,replay_iteration
from .monte_carlo import _json as write_json


def export_all_iterations(assessment,writer_token,event):
    verified=verified_assessment(assessment,_writer_token=writer_token)
    payload=verified[3]
    if payload['status'] not in ('precision_met','precision_limit_reached'):
        raise ValueError('Full iteration export requires a completed simulation.')
    checkpoint=fingerprint(assessment/'monte_carlo'/'checkpoint.json')
    parent=assessment/'iteration_exports';parent.mkdir(exist_ok=True)
    identity_path=parent/'source.json'
    if identity_path.exists():
        if json.loads(identity_path.read_text())!=checkpoint:
            raise ValueError('Iteration exports belong to a different checkpoint.')
    else:write_json(identity_path,checkpoint)
    records=[]
    try:
        for iteration in range(len(payload['rows'])):
            folder=parent/f'iteration_{iteration:06d}';folder.mkdir(exist_ok=True)
            receipt=folder/'complete.json'
            if receipt.exists():
                saved=json.loads(receipt.read_text())
                verify_fingerprints(saved['manifest'])
                manifest_path=folder/saved['attempt']/'manifest.json'
                verify_fingerprints(json.loads(manifest_path.read_text()))
                event('iteration_export_reused',iteration=iteration)
            else:
                attempt=1
                while (folder/f'attempt_{attempt:04d}').exists():attempt+=1
                destination=folder/f'attempt_{attempt:04d}'
                event('iteration_export_started',iteration=iteration,attempt=attempt)
                replay_iteration(assessment,iteration,destination,gis=True,
                    _writer_token=writer_token,_verified=verified)
                saved=dict(iteration=iteration,attempt=destination.name,manifest=fingerprint(destination/'manifest.json'))
                write_json(receipt,saved)
                event('iteration_export_complete',iteration=iteration,attempt=attempt)
            if saved['iteration']!=iteration:raise ValueError('Iteration receipt identity mismatch.')
            records.append(dict(iteration=iteration,directory=(folder/saved['attempt']).relative_to(assessment).as_posix(),
                receipt=fingerprint(receipt)))
            write_json(parent/'status.json',dict(status='exporting',completed=len(records),total=len(payload['rows'])))
        if fingerprint(assessment/'monte_carlo'/'checkpoint.json')!=checkpoint:
            raise ValueError('Checkpoint changed during iteration exports.')
        result=dict(status='complete',iterations=len(records),source_checkpoint=checkpoint,records=records)
        write_json(parent/'index.json',result)
        write_json(parent/'status.json',dict(status='complete',completed=len(records),total=len(records)))
        return dict(status='complete',iterations=len(records),index=fingerprint(parent/'index.json'))
    except BaseException as error:
        write_json(parent/'status.json',dict(status='failed',completed=len(records),total=len(payload['rows']),error=str(error)))
        event('iteration_exports_failed',completed=len(records),error_type=type(error).__name__,message=str(error))
        raise
