param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force data/tmp | Out-Null
$env:TEMP = Join-Path $PWD 'data/tmp'
$env:TMP = $env:TEMP
& $Python -c "import sys; assert sys.version_info >= (3, 11), 'Python 3.11+ is required'"
if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11+ or provide -Python with its full path.' }
if (-not (Test-Path '.venv/Scripts/python.exe')) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
}
& ./.venv/Scripts/python.exe -m pip install -r requirements.lock.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
if (-not (Test-Path '.env')) { Copy-Item .env.example .env }
Write-Host 'Setup complete. Configure .env, then run scripts/start.ps1.'
