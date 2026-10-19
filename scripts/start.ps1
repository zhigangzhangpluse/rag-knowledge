# ----------------------------------------------------------------------
# 启动问答 API：默认连接真实服务，-Demo 改用隔离的演示数据库和模型替身。
# 用法示例：powershell -File scripts/start.ps1 -Demo -Port 8001
# 127.0.0.1 只供本机访问，8000 是服务端口，不是数据库名称，也不会因代码公开自动变成公网地址。
# 面试问：为什么这里 workers=1？答：当前后台任务协调按单机设计，多进程需要重新处理任务竞争。
# ----------------------------------------------------------------------
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
