param([ValidateSet('start','stop','status','restart')][string]$Action='start')
$ErrorActionPreference = 'Stop'
$Repo = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$Python = Join-Path $Repo '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) { Write-Error 'Run setup.bat first.'; exit 1 }
$Stack = Join-Path $Repo 'tools\stack.py'
if ($Action -eq 'restart') {
    & $Python $Stack stop --service maibot
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python $Stack start --service maibot
} else { & $Python $Stack $Action --service maibot }
exit $LASTEXITCODE
