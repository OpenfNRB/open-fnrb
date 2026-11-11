# SPDX-License-Identifier: GPL-3.0-or-later
"""Package and research-mode identity, recorded without changing source."""
import hashlib
import json
from pathlib import Path
from .gis_inputs import fingerprint

VERSION='1.0.1'


def execution_identity():
    root=Path(__file__).resolve().parents[2]
    marker=root/'RESEARCH_WORKSPACE.json'
    if marker.exists():
        value=json.loads(marker.read_text(encoding='utf-8'));baseline=root/'RESEARCH_BASELINE.json'
        if value.get('mode')!='research' or hashlib.sha256(baseline.read_bytes()).hexdigest()!=value.get('baseline_sha256'):
            raise ValueError('Research marker or baseline record is invalid.')
        return dict(version=VERSION,mode='research',status='experimental',marker=fingerprint(marker),baseline=fingerprint(baseline))
    manifest=root/'PACKAGE_MANIFEST.json'
    if manifest.exists():
        value=json.loads(manifest.read_text(encoding='utf-8'))
        for entry in value['files']:
            path=(root/entry['path']).resolve()
            if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size!=entry['bytes'] or hashlib.sha256(path.read_bytes()).hexdigest()!=entry['sha256']:
                raise ValueError(f'Package differs from its baseline: {entry["path"]}. Use a separate research workspace for edits.')
        return dict(version=VERSION,mode='standardised',status='packaged_source_verified',manifest=fingerprint(manifest))
    return dict(version=VERSION,mode='unpackaged',status='source_without_package_manifest')
