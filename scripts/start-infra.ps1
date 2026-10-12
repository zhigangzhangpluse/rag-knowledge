# Start Milvus and Redis using Docker from PATH or an explicit executable path.
param([string]$DockerPath = 'docker')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
$dockerCommand = (Get-Command $DockerPath -ErrorAction Stop).Source
& $dockerCommand info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) {
    throw 'Docker engine is not ready. Restart Windows if required, then open Docker Desktop and finish first-run setup.'
}
& $dockerCommand compose --file compose.yaml config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Compose configuration is invalid.' }
& $dockerCommand compose --file compose.yaml up -d --wait --wait-timeout 180
if ($LASTEXITCODE -ne 0) { throw 'Infrastructure did not become healthy. Inspect docker compose ps and logs.' }
& $dockerCommand compose --file compose.yaml ps
