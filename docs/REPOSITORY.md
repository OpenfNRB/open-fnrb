# Repository setup and verification

## Repository contents

Use the contents of the `open-fnrb` directory as the repository root. Include `.gitattributes`, `.gitignore`, `PACKAGE_MANIFEST.json`, the source directories, documentation, templates, synthetic examples, licence and copyright notice. The system and business-process Mermaid sources are in `docs/diagrams`.

Keep real assessment inputs, household records, credentials, results, local environments, caches and development history outside the repository. Review the selected files before uploading. The supplied ignore rules exclude common local working folders; they cannot identify private data saved under arbitrary filenames.

The downloadable release ZIP and its checksum can be attached to a repository release separately. They do not need to be committed alongside the source.

## Exact source bytes

`PACKAGE_MANIFEST.json` records file sizes and SHA-256 hashes. Source text uses LF line endings. `.gitattributes` enforces LF checkouts across Windows and other systems, including when `core.autocrlf` is enabled, so the verified source bytes remain consistent. Binary GIS and workbook assets are explicitly marked as binary.

Upload `.gitattributes` with the other source files. Avoid editors or upload transformations that rewrite source files. Verify a fresh checkout before using it for an assessment. Source verification checks file integrity; it is not a digital signature or scientific approval.

## Verify a checkout

From the repository root in PowerShell, select the actual QGIS Python launcher:

```powershell
$qgisPython = 'C:\path\to\QGIS\bin\python-qgis.bat'
& $qgisPython -c "import sys;sys.path.insert(0,'tools');from package_files import check_packaged_source;assert check_packaged_source('.');print('Source manifest verified')"
```

Run the synthetic test suite using the same environment:

```powershell
& $qgisPython -c "import sys,unittest;sys.path.insert(0,'src');suite=unittest.defaultTestLoader.discover('tests');result=unittest.TextTestRunner(verbosity=2).run(suite);sys.exit(not result.wasSuccessful())"
```

The test suite requires the QGIS environment and dependencies described in [installation](INSTALLATION.md). Its subprocess checks inherit that environment. General-purpose Python alone is not a substitute for the supported GIS runtime.

For an end-to-end installation check, use a new folder outside the repository:

```powershell
& $qgisPython tools/check_installation.py --output 'C:\assessments\installation-check'
```

Inspect the resulting report. The short Monte Carlo installation run deliberately uses a small iteration limit and may report a numerical precision limit.

## Source changes and release packaging

Keep a downloaded assessment package unchanged. Create a separate research workspace for model experiments as described in `AGENTS.md`. Maintainer-approved release changes require their own review and a refreshed source manifest before packaging; a matching version string alone does not prove source equivalence.

The packaging utility includes `.gitattributes` and `.gitignore` and excludes Git metadata, local caches and assessment folders. The configured remote, branch and repository access settings are managed by the repository owner.
