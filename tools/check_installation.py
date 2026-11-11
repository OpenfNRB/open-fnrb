# SPDX-License-Identifier: GPL-3.0-or-later
"""Exercise installed source with invented data and preserve verification evidence."""
import argparse
import json
from pathlib import Path
import sys
import traceback


def check(output):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    status=output/'installation_check.json'
    status.write_text(json.dumps(dict(status='running')),encoding='utf-8')
    try:
        from check_environment import inspect_environment
        environment=inspect_environment()
        (output/'environment.json').write_text(json.dumps(environment,indent=2),encoding='utf-8')
        if environment['status']!='passed':raise RuntimeError('Dependency imports failed; inspect environment.json.')
        root=Path(__file__).resolve().parents[1]
        sys.path.insert(0,str(root/'src'));sys.path.insert(0,str(root/'examples'))
        from create_nominal_example import create
        from open_fnrb.workflow import run_nominal
        from open_fnrb.mc_workflow import run_assessment
        from open_fnrb.replay import replay_iteration
        from open_fnrb.provenance import execution_identity
        package=execution_identity()
        nominal={}
        for mode in ('agb','canopy'):
            config=create(output/(mode+'_inputs'),stock_mode=mode)
            nominal[mode]=run_nominal(config,output/(mode+'_nominal'))['fnrb']
        config=create(output/'classified_inputs',classification_uncertainty=True)
        sampling=config.parent/'sampling.json';settings=json.loads(sampling.read_text())
        settings['settings'].update(initial_iterations=32,maximum_iterations=32,checkpoint_interval=8)
        sampling.write_text(json.dumps(settings,indent=2),encoding='utf-8')
        run_assessment(config,sampling,output/'assessment',stop_after=5)
        completed=run_assessment(config,sampling,output/'assessment',resume=True)
        replay=replay_iteration(output/'assessment',3,output/'replay',gis=True)
        if completed['pending_exports'] or replay['verification']!='exact':raise RuntimeError('Required audit outputs did not complete.')
        result=dict(status='passed',package=package,nominal_fnrb=nominal,
            monte_carlo_status=completed['monte_carlo']['status'],iterations=completed['monte_carlo']['iterations'],
            replay=replay,scope='Synthetic installation check; 32 draws are not uncertainty precision or ecological acceptance.')
        status.write_text(json.dumps(result,indent=2),encoding='utf-8');return result
    except BaseException as error:
        status.write_text(json.dumps(dict(status='failed',error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc()),indent=2),encoding='utf-8')
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(check(args.output),indent=2))
