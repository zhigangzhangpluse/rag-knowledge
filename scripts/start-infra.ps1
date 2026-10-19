# ----------------------------------------------------------------------
# 启动 Milvus 和 Redis：先确认 Docker 引擎可用，再校验 Compose 并等待健康检查。
# 用法示例：powershell -File scripts/start-infra.ps1 -DockerPath docker
# 容器进程启动不等于服务已就绪，--wait 可以减少应用太早连接导致的失败。
# 面试问：健康检查成功证明模型可用吗？答：不能，这里只检查基础服务，模型需要另外验证。
# ----------------------------------------------------------------------
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
