# SPDX-License-Identifier: GPL-3.0-or-later
"""Create a separate research copy and immutable baseline record."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
from package_files import collect_files,manifest,check_packaged_source


def create(output,root=None):
    root=Path(root or Path(__file__).resolve().parents[1]).resolve()
    output=Path(output).resolve()
    if output.is_relative_to(root) or root.is_relative_to(output):raise ValueError('Research destination must be separate from the downloaded package.')
    if (root/'RESEARCH_WORKSPACE.json').exists():raise ValueError('Create the research baseline from the original package, not another research copy.')
    verified=check_packaged_source(root)
    files=collect_files(root);baseline=manifest(root,files)
    output.mkdir(parents=True,exist_ok=False)
    try:
        for source in files:
            target=output/source.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        baseline_path=output/'RESEARCH_BASELINE.json'
        baseline_path.write_text(json.dumps(baseline,indent=2),encoding='utf-8')
        marker=dict(schema_version=1,mode='research',created_utc=datetime.now(timezone.utc).isoformat(),
            original_source=str(root),original_packaged_manifest_verified=verified,
            baseline_sha256=hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
            isolation='Separate folder; shared runtime; not an OS security sandbox')
        (output/'RESEARCH_WORKSPACE.json').write_text(json.dumps(marker,indent=2),encoding='utf-8')
        (output/'RESEARCH_NOTES.md').write_text('# Research record\n\nDocument objective, baseline, changes, scientific assumptions, experiments, results and limitations here.\n',encoding='utf-8')
        return dict(workspace=str(output),mode='research',files=len(files),baseline_verified=verified)
    except BaseException as error:
        (output/'RESEARCH_CREATION_FAILED.txt').write_text(str(error),encoding='utf-8')
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(create(args.output),indent=2))
