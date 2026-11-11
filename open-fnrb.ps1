# SPDX-License-Identifier: GPL-3.0-or-later
param(
    [Parameter(Mandatory=$true)] [string] $QgisPython,
    [Parameter(ValueFromRemainingArguments=$true)] [string[]] $ToolArguments
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $QgisPython -PathType Leaf)) {
    throw 'Supply the full path to the installed QGIS python-qgis.bat launcher.'
}
& $QgisPython (Join-Path $PSScriptRoot 'run_open_fnrb.py') @ToolArguments
exit $LASTEXITCODE
