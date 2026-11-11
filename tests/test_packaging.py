# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import importlib.util
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from build_package import build
from create_research_workspace import create
from package_files import collect_files,manifest


class PackagingTests(unittest.TestCase):
    def test_archive_determinism_and_research_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            temp=Path(temporary)
            source=ROOT
            if (ROOT/'RESEARCH_WORKSPACE.json').exists():
                # Exercise release packaging with a disposable source fixture;
                # the real research workspace must remain unpackageable.
                with self.assertRaisesRegex(ValueError,'Research workspaces'):
                    build(temp/'forbidden.zip',ROOT)
                source=temp/'source_fixture'
                for path in collect_files(ROOT):
                    target=source/path.relative_to(ROOT)
                    target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(path,target)
            build(temp/'a.zip',source);build(temp/'b.zip',source)
            self.assertEqual((temp/'a.zip').read_bytes(),(temp/'b.zip').read_bytes())
            with ZipFile(temp/'a.zip') as archive:
                self.assertFalse(any('__pycache__' in n or '.git/' in n for n in archive.namelist()))
                self.assertIn(b'Version 3, 29 June 2007',archive.read('open-fnrb/LICENSE'))
                self.assertIn(b'GPL-3.0-or-later',archive.read('open-fnrb/COPYRIGHT.md'))
                self.assertIn(b'* text=auto eol=lf',archive.read('open-fnrb/.gitattributes'))
                self.assertIn(b'__pycache__/',archive.read('open-fnrb/.gitignore'))
                self.assertEqual(sum(n.startswith('open-fnrb/docs/diagrams/') and n.endswith('.mmd')
                                     for n in archive.namelist()),4)
                archive.extractall(temp/'download')
            baseline=temp/'download'/'open-fnrb'
            before=manifest(baseline,collect_files(baseline))
            with self.assertRaisesRegex(ValueError,'separate'):create(baseline/'research',baseline)
            research=temp/'research';create(research,baseline)
            self.assertEqual((research/'LICENSE').read_bytes(),(baseline/'LICENSE').read_bytes())
            self.assertEqual((research/'COPYRIGHT.md').read_bytes(),(baseline/'COPYRIGHT.md').read_bytes())
            self.assertTrue((research/'RESEARCH_WORKSPACE.json').exists())
            target=research/'src'/'open_fnrb'/'annual.py'
            target.write_text(target.read_text()+'\n# Research-only experiment\n')
            self.assertEqual(manifest(baseline,collect_files(baseline)),before)
            with self.assertRaisesRegex(ValueError,'Research workspaces'):build(temp/'research.zip',research)
            with self.assertRaises(FileExistsError):create(research,baseline)
            # Use a fresh process so provenance resolves from the copied source.
            code="import sys,json;sys.path.insert(0,sys.argv[1]);from open_fnrb.provenance import execution_identity;print(json.dumps(execution_identity()))"
            process=subprocess.run([sys.executable,'-c',code,str(research/'src')],capture_output=True,text=True)
            self.assertEqual(process.returncode,0,process.stderr)
            self.assertEqual(json.loads(process.stdout)['mode'],'research')
            original=subprocess.run([sys.executable,'-c',code,str(baseline/'src')],capture_output=True,text=True)
            self.assertEqual(original.returncode,0,original.stderr)
            self.assertEqual(json.loads(original.stdout)['mode'],'standardised')
            (baseline/'README.md').write_text('Modified download')
            changed=subprocess.run([sys.executable,'-c',code,str(baseline/'src')],capture_output=True,text=True)
            self.assertNotEqual(changed.returncode,0)
            self.assertIn('differs from its baseline',changed.stderr)
            with self.assertRaisesRegex(ValueError,'Changed package file'):create(temp/'invalid_research',baseline)
