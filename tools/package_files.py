# SPDX-License-Identifier: GPL-3.0-or-later
"""Allowlisted source-package collection; no outputs or local history."""
import hashlib
import json
from pathlib import Path

ROOT_FILES=('.gitattributes','.gitignore','LICENSE','COPYRIGHT.md','README.md','AGENTS.md','run_open_fnrb.py','open-fnrb.ps1')
DIRECTORIES=('src','docs','examples','templates','tests','tools')
EXTENSIONS={'.py','.md','.mmd','.txt','.csv','.json','.xlsx','.ps1','.tif','.gpkg'}


def collect_files(root):
    root=Path(root).resolve()
    result=[]
    for name in ROOT_FILES:
        path=root/name
        if not path.is_file():raise ValueError(f'Missing package file: {name}')
        result.append(path)
    for folder in DIRECTORIES:
        for path in sorted((root/folder).rglob('*')):
            if path.is_symlink():raise ValueError(f'Symlinks are not package content: {path}')
            if not path.is_file() or '__pycache__' in path.parts:continue
            if path.suffix.lower() not in EXTENSIONS or path.name.endswith('.inspect.ndjson'):
                raise ValueError(f'Unexpected file in package source: {path.relative_to(root)}')
            result.append(path)
    return sorted(result,key=lambda p:p.relative_to(root).as_posix())


def manifest(root,files):
    return dict(schema_version=1,files=[dict(path=p.relative_to(root).as_posix(),bytes=p.stat().st_size,
        sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files])


def verify_manifest(root,value):
    root=Path(root).resolve()
    for entry in value['files']:
        path=(root/entry['path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():raise ValueError('Manifest path is missing or outside the package.')
        if path.stat().st_size!=entry['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
            raise ValueError(f'Changed package file: {entry["path"]}')


def check_packaged_source(root):
    path=Path(root)/'PACKAGE_MANIFEST.json'
    if path.exists():verify_manifest(root,json.loads(path.read_text(encoding='utf-8')))
    return path.exists()
