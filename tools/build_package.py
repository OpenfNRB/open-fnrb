# SPDX-License-Identifier: GPL-3.0-or-later
"""Build a deterministic source archive without publishing it."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile,ZipInfo,ZIP_DEFLATED
from package_files import collect_files,manifest,check_packaged_source


def build(output,root=None):
    root=Path(root or Path(__file__).resolve().parents[1]).resolve()
    output=Path(output).resolve()
    if (root/'RESEARCH_WORKSPACE.json').exists():raise ValueError('Research workspaces cannot build standardised release packages.')
    if output.is_relative_to(root):raise ValueError('Package destination must be outside source.')
    check_packaged_source(root)
    files=collect_files(root);record=manifest(root,files)
    output.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(output,'x',compression=ZIP_DEFLATED) as archive:
        for name,data in [(p.relative_to(root).as_posix(),p.read_bytes()) for p in files]+[
                ('PACKAGE_MANIFEST.json',json.dumps(record,indent=2).encode())]:
            info=ZipInfo('open-fnrb/'+name,date_time=(2000,1,1,0,0,0));info.compress_type=ZIP_DEFLATED
            info.external_attr=0o644<<16;archive.writestr(info,data)
    return dict(archive=str(output),files=len(files),status='package_built')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True)
    args=parser.parse_args();print(json.dumps(build(args.output),indent=2))
