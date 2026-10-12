$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
New-Item -ItemType Directory -Force data/tmp | Out-Null
$env:TEMP = Join-Path $PWD 'data/tmp'
$env:TMP = $env:TEMP
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& ./.venv/Scripts/python.exe -m pytest --basetemp=data/pytest-tmp
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& ./.venv/Scripts/python.exe -m compileall -q app scripts
if ($LASTEXITCODE -ne 0) { throw 'Python syntax check failed.' }
node --check web/app.js
if ($LASTEXITCODE -ne 0) { throw 'JavaScript syntax check failed.' }
