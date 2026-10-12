param([switch]$Demo, [int]$Port = 8000)
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$projectPython = Join-Path $PWD '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Please run scripts/setup.ps1 first.' }
$env:TEMP = Join-Path $PWD 'data/tmp'
$env:TMP = $env:TEMP
$env:HF_HOME = Join-Path $PWD 'models/huggingface'
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
if ($Demo) {
    $env:APP_MODE = 'demo'
    $env:DATABASE_URL = 'sqlite:///./data/demo.db'
    $env:DATA_DIR = 'data/demo'
} else {
    $env:APP_MODE = 'production'
    Remove-Item Env:DATABASE_URL -ErrorAction SilentlyContinue
    Remove-Item Env:DATA_DIR -ErrorAction SilentlyContinue
}
& $projectPython -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port $Port --workers 1
