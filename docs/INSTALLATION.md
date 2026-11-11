# Windows and QGIS installation

Use the Python environment supplied with your QGIS installation. The tool uses NumPy, SciPy, GDAL/OGR, Shapely, pyproj and openpyxl. Microsoft Excel is not needed to create reports. No automatic package installation or upgrade is performed.

## Verify the environment

Extract the package into a writable location. Keep inputs and results in separate folders. From PowerShell, substituting your actual QGIS installation and package paths:

```powershell
$qgisPython = 'C:\path\to\QGIS\bin\python-qgis.bat'
& $qgisPython 'C:\path\to\open-fnrb\tools\check_environment.py' --output 'C:\path\to\new-environment-report.json'
& $qgisPython 'C:\path\to\open-fnrb\tools\check_installation.py' --output 'C:\path\to\new-installation-check'
```

The environment report lists dependency versions and import failures. The installation check creates only invented inputs and runs nominal/Monte Carlo/replay checks. Its small iteration limit is deliberate; a precision-limit result is expected and is not ecological validation.

Both commands must exit successfully. Inspect their JSON reports. A failed import, process crash or incomplete output is not a passed check. If the runtime fails to start, preserve the error and environment report. A later successful retry alone does not explain an intermittent failure.

## Run an assessment

```powershell
& $qgisPython 'C:\path\to\open-fnrb\run_open_fnrb.py' nominal 'C:\assessments\example\workflow.json' --output 'C:\assessments\example\new-results'
```

Alternatively, from the package folder:

```powershell
.\open-fnrb.ps1 -QgisPython $qgisPython nominal 'C:\assessments\example\workflow.json' --output 'C:\assessments\example\new-results'
```

The launcher does not modify PowerShell execution policy. If local policy prevents running it, use the explicit QGIS Python command above.

Use `--help` for commands. Each new assessment or replay requires a new output directory. For compatible recovery use `resume` with the original workflow, sampling configuration and output directory. Original input paths must remain available for fingerprint verification; portable relocation of an existing audit archive is not supported.
