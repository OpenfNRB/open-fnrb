# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line entry point for supported file-driven assessments."""
import argparse
import json
import sys


def main(argv=None):
    parser=argparse.ArgumentParser(prog='open_fnrb',description='Open fNRB single-year calculation')
    commands=parser.add_subparsers(dest='command',required=True)
    nominal=commands.add_parser('nominal',help='Run nominal calculation and export core audit tables')
    nominal.add_argument('configuration',help='Workflow JSON file')
    nominal.add_argument('--output',required=True,help='New local output directory')
    replay=commands.add_parser('replay',help='Verify and export a completed Monte Carlo iteration')
    replay.add_argument('assessment',help='Existing Monte Carlo assessment directory')
    replay.add_argument('--iteration',type=int,required=True,help='Zero-based completed iteration index')
    replay.add_argument('--output',required=True,help='New directory outside the original assessment')
    replay.add_argument('--gis',action='store_true',help='Also export iteration GeoTIFFs and shapefiles')
    spatial=commands.add_parser('spatial-summary',help='Export verified Monte Carlo stock/flux uncertainty maps')
    spatial.add_argument('assessment')
    spatial.add_argument('--output',required=True)
    spatial.add_argument('--maximum-scratch-bytes',type=int,default=20_000_000_000)
    spatial.add_argument('--cell-block-size',type=int,default=256)
    for name,help_text in [('monte-carlo','Prepare inputs and run nominal plus Monte Carlo'),('resume','Resume a compatible Monte Carlo assessment')]:
        command=commands.add_parser(name,help=help_text)
        command.add_argument('configuration',help='Workflow JSON file')
        command.add_argument('--sampling',required=True,help='Explicit Monte Carlo settings JSON')
        command.add_argument('--output',required=True,help='Assessment output directory')
        command.add_argument('--stop-after',type=int,help='Gracefully stop after this absolute number of completed iterations')
        command.add_argument('--maximum-scratch-bytes',type=int,default=20_000_000_000,help='Disk budget for automatic spatial percentiles')
        command.add_argument('--cell-block-size',type=int,default=256)
        command.add_argument('--full-iteration-gis',action='store_true',help='Also export GIS and data for every draw; may require substantial storage')
    args=parser.parse_args(argv)
    try:
        if args.command=='nominal':
            from .workflow import run_nominal
            result=run_nominal(args.configuration,args.output)
            print('Nominal tables, GIS and Excel summary complete.',file=sys.stderr)
        elif args.command=='replay':
            from .replay import replay_iteration
            result=replay_iteration(args.assessment,args.iteration,args.output,gis=args.gis)
        elif args.command=='spatial-summary':
            from .spatial_summary import export_spatial_summary
            result=export_spatial_summary(args.assessment,args.output,
                maximum_scratch_bytes=args.maximum_scratch_bytes,cell_block_size=args.cell_block_size)
        else:
            from .mc_workflow import run_assessment
            result=run_assessment(args.configuration,args.sampling,args.output,
                resume=args.command=='resume',stop_after=args.stop_after,
                maximum_scratch_bytes=args.maximum_scratch_bytes,cell_block_size=args.cell_block_size,
                full_iteration_gis=args.full_iteration_gis)
            print('Assessment returned; completed Monte Carlo runs include spatial uncertainty exports.',file=sys.stderr)
        print(json.dumps(result,allow_nan=False))
        return 0
    except Exception as error:
        print(f'Assessment failed: {error}',file=sys.stderr)
        return 1


if __name__=='__main__':
    sys.exit(main())
